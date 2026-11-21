"""Storage Manager (registro de volumes) — Fase 1 (§5 do adendo).

O banco de dados definitivo (PostgreSQL) entra na Fase 6; aqui usamos um
registro em arquivo JSON com os campos exigidos pelo adendo:

- Identificador do volume (ID na Vast.ai)
- Identificador do host físico (machine_id)
- Capacidade contratada (GB)
- Espaço utilizado (GB) — atualizado pelo worker nas fases seguintes
- Caminho de montagem (/data)
- Estado de disponibilidade
- Última verificação (timestamp)

Regras: nunca apagar volume automaticamente; volumes são vinculados a um host
físico; registros sobrevivem ao encerramento das instâncias.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("localvideo.storage")

REGISTRY_FILE = "storage_registry.json"


class VolumeState(StrEnum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    HOST_UNAVAILABLE = "HOST_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    DECOMMISSIONED = "DECOMMISSIONED"


class VolumeRecord(BaseModel):
    volume_id: int = Field(description="ID do volume na Vast.ai")
    machine_id: int | None = Field(description="Host físico ao qual o volume está vinculado.")
    capacity_gb: float
    used_gb: float = 0.0
    mount_path: str = "/data"
    state: VolumeState = VolumeState.UNKNOWN
    storage_monthly_usd: float = 0.0
    last_checked: float = Field(default_factory=time.time)
    note: str = ""


class StorageRegistry:
    """Registro persistente (JSON) de volumes; interface pronta para DB."""

    def __init__(self, data_dir: str = "./data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / REGISTRY_FILE
        self._lock = asyncio.Lock()
        self._volumes: dict[int, VolumeRecord] = {}
        self._load()

    # ------------------------------------------------------------------
    async def upsert(self, record: VolumeRecord) -> VolumeRecord:
        async with self._lock:
            record.last_checked = time.time()
            self._volumes[record.volume_id] = record
            self._save()
            return record

    async def get(self, volume_id: int) -> VolumeRecord | None:
        async with self._lock:
            return self._volumes.get(volume_id)

    async def list(self) -> list[VolumeRecord]:
        async with self._lock:
            return sorted(self._volumes.values(), key=lambda v: v.volume_id)

    async def for_host(self, machine_id: int) -> list[VolumeRecord]:
        async with self._lock:
            return [
                record
                for record in self._volumes.values()
                if record.machine_id == machine_id
                and record.state in (VolumeState.AVAILABLE, VolumeState.IN_USE)
            ]

    async def mark_state(self, volume_id: int, state: VolumeState, note: str = "") -> None:
        async with self._lock:
            record = self._volumes.get(volume_id)
            if record is None:
                return
            record.state = state
            record.note = note
            record.last_checked = time.time()
            self._save()

    async def update_usage(self, volume_id: int, used_gb: float) -> None:
        async with self._lock:
            record = self._volumes.get(volume_id)
            if record is None:
                return
            record.used_gb = max(0.0, used_gb)
            record.last_checked = time.time()
            self._save()

    async def remove(self, volume_id: int) -> None:
        """Exclusão manual somente — NUNCA chamada automaticamente (§5)."""
        async with self._lock:
            self._volumes.pop(volume_id, None)
            self._save()

    # ------------------------------------------------------------------
    def _save(self) -> None:
        try:
            payload = [record.model_dump(mode="json") for record in self._volumes.values()]
            self._path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            logger.error("Falha ao salvar registro de armazenamento: %s", exc)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data:
                record = VolumeRecord.model_validate(item)
                self._volumes[record.volume_id] = record
        except (OSError, ValueError) as exc:
            logger.error("Falha ao carregar registro de armazenamento: %s", exc)
            self._volumes = {}

    def to_public(self, record: VolumeRecord) -> dict[str, Any]:
        """Representação pública (sem IDs sensíveis do provedor além do volume)."""
        return {
            "volume_id": record.volume_id,
            "machine_id": record.machine_id,
            "capacity_gb": record.capacity_gb,
            "used_gb": record.used_gb,
            "free_gb": max(record.capacity_gb - record.used_gb, 0.0),
            "mount_path": record.mount_path,
            "state": record.state.value,
            "storage_monthly_usd": record.storage_monthly_usd,
            "last_checked": record.last_checked,
            "note": record.note,
        }
