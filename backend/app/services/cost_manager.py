"""Cost Manager — controle financeiro (§8 do adendo).

Responsabilidades:
- Manter orçamento mensal em BRL e taxa USD->BRL configuráveis.
- Registrar reservas de sessão (antes de iniciar GPU) e cobranças reais.
- Regras: avisar em 70%, bloquear novas gerações em 90%, nunca iniciar
  tarefa que ultrapasse o saldo; reservar margem para armazenamento/tráfego.
- Separar ESTIMATIVA de COBRANÇA EFETIVA (cobrança real vem do adaptador
  de charges da Vast.ai).
- Não prometer limite absoluto de cobrança: o bloqueio é interno; cobranças
  externas não previstas são tratadas como override no ledger com aviso.

Persistência da Fase 1: arquivo JSON sob `data_dir` (substituído por
PostgreSQL na Fase 6; a interface já é async e centralizada).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger("localvideo.cost")

LEDGER_FILE = "cost_ledger.json"
SETTINGS_FILE = "cost_settings.json"


class BudgetState(StrEnum):
    OK = "OK"
    ALERT_70 = "ALERT_70"
    BLOCK_90 = "BLOCK_90"
    LIMIT_REACHED = "LIMIT_REACHED"


@dataclass
class LedgerEntry:
    ts: float
    kind: str  # "reservation" | "settlement" | "release" | "external_override"
    usd: float
    brl: float
    instance_id: int | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "usd": round(self.usd, 6),
            "brl": round(self.brl, 6),
            "instance_id": self.instance_id,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        return cls(
            ts=float(data["ts"]),
            kind=str(data["kind"]),
            usd=float(data["usd"]),
            brl=float(data["brl"]),
            instance_id=data.get("instance_id"),
            note=str(data.get("note", "")),
        )


@dataclass
class BudgetStatus:
    budget_brl: float
    committed_brl: float          # reservas ativas + acúmulo da sessão + cobranças reais do período
    external_brl: float           # cobranças reais informadas pelo provedor (charges)
    session_accrual_brl: float
    remaining_brl: float
    utilization: float
    state: BudgetState
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_brl": round(self.budget_brl, 2),
            "committed_brl": round(self.committed_brl, 2),
            "external_brl": round(self.external_brl, 2),
            "session_accrual_brl": round(self.session_accrual_brl, 2),
            "remaining_brl": round(self.remaining_brl, 2),
            "utilization": round(self.utilization, 4),
            "state": self.state.value,
            "warnings": self.warnings,
        }


@dataclass
class StartDecision:
    allowed: bool
    reasons: list[str]
    estimated_session_brl: float
    estimated_session_usd: float


class CostManager:
    def __init__(
        self,
        *,
        data_dir: str = "./data",
        monthly_budget_brl: float = 100.0,
        usd_to_brl_rate: float = 5.40,
        alert_threshold: float = 0.70,
        block_threshold: float = 0.90,
        storage_reserve_brl: float = 5.0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self.data_dir / LEDGER_FILE
        self._settings_path = self.data_dir / SETTINGS_FILE
        self.monthly_budget_brl = monthly_budget_brl
        self.usd_to_brl_rate = usd_to_brl_rate
        self.alert_threshold = alert_threshold
        self.block_threshold = block_threshold
        self.storage_reserve_brl = storage_reserve_brl
        self._lock = asyncio.Lock()
        self._entries: list[LedgerEntry] = []
        # Pools contábeis (BRL): reservas ativas vs. custo real acumulado.
        self._reserved_brl: float = 0.0
        self._spent_brl: float = 0.0
        self._external_brl: float = 0.0
        self._load()
        self._load_settings()

    # ------------------------------------------------------------------
    # Conversões
    # ------------------------------------------------------------------
    def usd_to_brl(self, usd: float) -> float:
        return usd * self.usd_to_brl_rate

    # ------------------------------------------------------------------
    # Estimativa (≠ cobrança efetiva)
    # ------------------------------------------------------------------
    def estimate_session(
        self,
        hourly_price_usd: float,
        hours: float,
        *,
        storage_monthly_usd: float = 0.0,
        bandwidth_usd: float = 0.0,
    ) -> dict[str, Any]:
        gpu_usd = max(hourly_price_usd, 0.0) * max(hours, 0.0)
        storage_usd = (storage_monthly_usd / 730.0) * max(hours, 0.0)
        total_usd = gpu_usd + storage_usd + max(bandwidth_usd, 0.0)
        return {
            "hours": hours,
            "gpu_hourly_usd": round(hourly_price_usd, 4),
            "gpu_total_usd": round(gpu_usd, 4),
            "storage_total_usd": round(storage_usd, 4),
            "bandwidth_usd": round(bandwidth_usd, 4),
            "total_usd": round(total_usd, 4),
            "total_brl": round(self.usd_to_brl(total_usd), 2),
            "is_estimate": True,
            "note": (
                "Estimativa baseada no preço publicado da oferta. A cobrança "
                "efetiva vem da Vast.ai e pode diferir (charges reais)."
            ),
        }

    # ------------------------------------------------------------------
    # Decisão de início
    # ------------------------------------------------------------------
    async def can_start(self, estimated_session_usd: float) -> StartDecision:
        estimated_brl = self.usd_to_brl(estimated_session_usd)
        async with self._lock:
            status = self._compute_status()
            reasons: list[str] = []

            if status.state is BudgetState.LIMIT_REACHED:
                reasons.append("Orçamento mensal esgotado (>= 100%).")
            if status.state is BudgetState.BLOCK_90:
                reasons.append(
                    f"Orçamento atingiu {self.block_threshold:.0%} — novas gerações bloqueadas."
                )
            if estimated_brl > status.remaining_brl:
                reasons.append(
                    f"Estimativa da sessão (R$ {estimated_brl:.2f}) excede o saldo "
                    f"disponível (R$ {status.remaining_brl:.2f})."
                )
            if status.remaining_brl < self.storage_reserve_brl:
                reasons.append(
                    "Saldo abaixo da reserva mínima de armazenamento/tráfego "
                    f"(R$ {self.storage_reserve_brl:.2f})."
                )

            allowed = not reasons
            if allowed and status.state is BudgetState.ALERT_70:
                reasons.append(
                    f"Atenção: orçamento consumido acima de {self.alert_threshold:.0%}."
                )
            return StartDecision(
                allowed=allowed,
                reasons=reasons,
                estimated_session_brl=round(estimated_brl, 2),
                estimated_session_usd=round(estimated_session_usd, 4),
            )

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------
    async def reserve(self, estimated_session_usd: float, instance_id: int | None = None) -> None:
        async with self._lock:
            brl = self.usd_to_brl(estimated_session_usd)
            self._reserved_brl += brl
            self._append(
                LedgerEntry(
                    ts=time.time(),
                    kind="reservation",
                    usd=estimated_session_usd,
                    brl=brl,
                    instance_id=instance_id,
                    note="reserva estimada para sessão",
                )
            )

    async def settle(self, actual_usd: float, instance_id: int | None = None, note: str = "") -> None:
        """Registra cobrança real: consome reserva equivalente e passa a custo.

        committed = reservas_ativas + custo_real — liquidar R$X de uma reserva
        de R$X mantém o total comprometido (o dinheiro foi gasto de fato).
        """
        async with self._lock:
            brl = self.usd_to_brl(actual_usd)
            consumed = min(brl, self._reserved_brl)
            self._reserved_brl -= consumed
            self._spent_brl += brl
            self._append(
                LedgerEntry(
                    ts=time.time(),
                    kind="settlement",
                    usd=actual_usd,
                    brl=brl,
                    instance_id=instance_id,
                    note=note or "cobrança real registrada",
                )
            )

    async def release(self, estimated_session_usd: float, instance_id: int | None = None) -> None:
        """Remove reserva não consumida (sessão encerrada sem cobrança equivalente)."""
        async with self._lock:
            brl = self.usd_to_brl(estimated_session_usd)
            self._reserved_brl = max(self._reserved_brl - brl, 0.0)
            self._append(
                LedgerEntry(
                    ts=time.time(),
                    kind="release",
                    usd=-estimated_session_usd,
                    brl=-brl,
                    instance_id=instance_id,
                    note="reserva liberada",
                )
            )

    async def record_external_charges(self, actual_usd: float) -> list[str]:
        """Registra cobranças externas não previstas (§8) e devolve avisos.

        Exemplo: cobrança de storage quando a instância já foi destruída, ou
        tráfego cobrado fora do nosso controle. Entram como custo real.
        """
        async with self._lock:
            brl = self.usd_to_brl(actual_usd)
            self._spent_brl += brl
            self._external_brl += brl
            self._append(
                LedgerEntry(
                    ts=time.time(),
                    kind="external_override",
                    usd=actual_usd,
                    brl=brl,
                    instance_id=None,
                    note="cobrança externa não prevista (informada pelo provedor)",
                )
            )
            status = self._compute_status()
            return status.warnings

    async def apply_external_usage(self, charges_usd: float, note: str = "charges Vast.ai") -> None:
        """Consome cobranças reais lidas da Vast.ai contra a(s) reserva(s).

        A parte cobrada dentro das reservas vira settlement; o excedente
        entra como external_override (com aviso).
        """
        async with self._lock:
            brl = self.usd_to_brl(charges_usd)
            consumed = min(brl, self._reserved_brl)
            self._reserved_brl -= consumed
            self._spent_brl += brl
            excess_brl = brl - consumed
            self._external_brl += max(excess_brl, 0.0)
            if consumed > 0:
                self._append(
                    LedgerEntry(
                        ts=time.time(),
                        kind="settlement",
                        usd=consumed / self.usd_to_brl_rate,
                        brl=consumed,
                        instance_id=None,
                        note=note,
                    )
                )
            if excess_brl > 0:
                self._append(
                    LedgerEntry(
                        ts=time.time(),
                        kind="external_override",
                        usd=excess_brl / self.usd_to_brl_rate,
                        brl=excess_brl,
                        instance_id=None,
                        note="excedente sobre reservas (cobrança acima da estimativa)",
                    )
                )

    # ------------------------------------------------------------------
    # Configuração de orçamento (§11: limite mensal configurável no painel)
    # ------------------------------------------------------------------
    async def update_budget(
        self,
        monthly_budget_brl: float | None = None,
        usd_to_brl_rate: float | None = None,
    ) -> BudgetStatus:
        """Atualiza limite mensal e/ou taxa USD→BRL e persiste em
        `cost_settings.json` (sobrevive a reinícios até migrar p/ PostgreSQL).
        """
        async with self._lock:
            if monthly_budget_brl is not None:
                if monthly_budget_brl <= 0:
                    raise ValueError("Orçamento mensal deve ser positivo.")
                self.monthly_budget_brl = float(monthly_budget_brl)
            if usd_to_brl_rate is not None:
                if usd_to_brl_rate <= 0:
                    raise ValueError("Taxa USD→BRL deve ser positiva.")
                self.usd_to_brl_rate = float(usd_to_brl_rate)
            self._save_settings()
            return self._compute_status()

    def _save_settings(self) -> None:
        try:
            self._settings_path.write_text(
                json.dumps(
                    {
                        "monthly_budget_brl": self.monthly_budget_brl,
                        "usd_to_brl_rate": self.usd_to_brl_rate,
                        "updated_at": time.time(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover
            logger.error("Falha ao salvar configuração de custos: %s", exc)

    def _load_settings(self) -> None:
        """Preferência do painel sobrepõe o default do ambiente, se existir."""
        if not self._settings_path.exists():
            return
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data.get("monthly_budget_brl"):
                    self.monthly_budget_brl = float(data["monthly_budget_brl"])
                if data.get("usd_to_brl_rate"):
                    self.usd_to_brl_rate = float(data["usd_to_brl_rate"])
        except (OSError, ValueError) as exc:
            logger.error("Falha ao carregar configuração de custos: %s", exc)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    async def budget_status(self, session_accrual_brl: float = 0.0) -> BudgetStatus:
        async with self._lock:
            return self._compute_status(session_accrual_brl)

    def _compute_status(self, session_accrual_brl: float = 0.0) -> BudgetStatus:
        committed = (
            self._reserved_brl
            + self._spent_brl
            + max(session_accrual_brl, 0.0)
        )
        remaining = self.monthly_budget_brl - committed
        utilization = committed / self.monthly_budget_brl if self.monthly_budget_brl > 0 else 1.0

        if utilization >= 1.0:
            state = BudgetState.LIMIT_REACHED
        elif utilization >= self.block_threshold:
            state = BudgetState.BLOCK_90
        elif utilization >= self.alert_threshold:
            state = BudgetState.ALERT_70
        else:
            state = BudgetState.OK

        warnings: list[str] = []
        if state is BudgetState.ALERT_70:
            warnings.append(
                f"Orçamento em {utilization:.0%} do limite mensal (alerta em {self.alert_threshold:.0%})."
            )
        if state is BudgetState.BLOCK_90:
            warnings.append(
                f"Orçamento em {utilization:.0%} — novas gerações serão bloqueadas "
                f"a partir de {self.block_threshold:.0%}."
            )
        if state is BudgetState.LIMIT_REACHED:
            warnings.append("Orçamento mensal esgotado. Nenhuma nova sessão de GPU será iniciada.")
        if self._external_brl > 0:
            warnings.append(
                f"Cobranças externas não previstas somam R$ {self._external_brl:.2f} neste mês."
            )

        return BudgetStatus(
            budget_brl=self.monthly_budget_brl,
            committed_brl=committed,
            external_brl=self._external_brl,
            session_accrual_brl=session_accrual_brl,
            remaining_brl=max(remaining, 0.0),
            utilization=utilization,
            state=state,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------
    def _append(self, entry: LedgerEntry) -> None:
        self._entries.append(entry)
        self._save()

    def _save(self) -> None:
        try:
            payload = [entry.to_dict() for entry in self._entries[-2000:]]
            self._ledger_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # pragma: no cover - disco cheio etc.
            logger.error("Falha ao salvar ledger de custos: %s", exc)

    def _load(self) -> None:
        if not self._ledger_path.exists():
            return
        try:
            data = json.loads(self._ledger_path.read_text(encoding="utf-8"))
            self._entries = [LedgerEntry.from_dict(item) for item in data if isinstance(item, dict)]
        except (OSError, ValueError, KeyError) as exc:
            logger.error("Falha ao carregar ledger de custos: %s", exc)
            self._entries = []
        # Reconstrói os pools contábeis a partir do histórico.
        self._reserved_brl = 0.0
        self._spent_brl = 0.0
        self._external_brl = 0.0
        for entry in self._entries:
            self._apply_to_pools(entry)

    def _apply_to_pools(self, entry: LedgerEntry) -> None:
        if entry.kind == "reservation":
            self._reserved_brl += entry.brl
        elif entry.kind == "release":
            self._reserved_brl = max(self._reserved_brl + entry.brl, 0.0)  # brl negativo
        elif entry.kind == "settlement":
            consumed = min(entry.brl, self._reserved_brl)
            self._reserved_brl -= consumed
            self._spent_brl += entry.brl
        elif entry.kind == "external_override":
            self._spent_brl += entry.brl
            self._external_brl += entry.brl

    async def ledger(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [entry.to_dict() for entry in self._entries[-200:]]
