"""Auditoria de operações financeiras e administrativas (§10 do adendo).

Registro em JSON lines (`data/audit.log`): timestamp, ator (papel/rótulo
NÃO sensível), ação, resultado. Nunca registra credenciais nem chaves.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("localvideo.audit")


class AuditLogger:
    def __init__(self, data_dir: str = "./data") -> None:
        self.path = Path(data_dir) / "audit.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        actor: str,
        action: str,
        result: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "ts": time.time(),
            "actor": actor,
            "action": action,
            "result": result,
        }
        if details:
            # Blindagem: remover quaisquer campos que possam carregar segredos.
            safe = {
                k: v
                for k, v in details.items()
                if not any(
                    token in k.lower() for token in ("key", "token", "secret", "password", "credential")
                )
            }
            entry["details"] = safe
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:  # pragma: no cover
            logger.error("Falha ao gravar auditoria: %s", exc)

    def tail(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:  # pragma: no cover
            return []
        entries: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return entries
