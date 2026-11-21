"""Serviço de volumes persistentes (GET/PUT /api/v0/volumes).

Endpoints oficiais usados:
- Listagem:  GET /api/v0/volumes?owner=me&type=all
             -> {"volumes": [Volume...]}  (Volume.machine_id = host físico)
- Aluguel:   PUT /api/v0/volumes  (body {id, size})  [operação de cobrança]

REGRAS DO ADENDO (§5):
- Volume local da Vast.ai é fisicamente vinculado à máquina onde foi criado;
  `validate_host_affinity` impede associar volume a oferta de outro host.
- O adaptador NÃO implementa exclusão de volumes — de propósito. A exclusão
  só deve existir no futuro com dupla confirmação do usuário.
"""

from __future__ import annotations

import logging

from .vast_client import VastHttpClient
from .vast_exceptions import VastError, VastVolumeError, VastVolumeHostMismatchError
from .vast_schemas import VastOffer, VastVolume

logger = logging.getLogger("localvideo.vast.volumes")

VOLUMES_PATH = "/api/v0/volumes"


class VastVolumesService:
    def __init__(self, http: VastHttpClient, mutation_gate: MutationGate) -> None:  # noqa: F821
        self.http = http
        self.gate = mutation_gate

    async def list(self, *, volume_type: str = "all") -> list[VastVolume]:
        """Lista todos os volumes alugados pela conta."""
        _, data = await self.http.request(
            "GET", VOLUMES_PATH, query={"owner": "me", "type": volume_type}
        )
        raw = data.get("volumes") or []
        return [VastVolume.model_validate(item) for item in raw]

    async def get(self, volume_id: int) -> VastVolume | None:
        for volume in await self.list():
            if volume.id == volume_id:
                return volume
        return None

    async def rent(self, offer_id: int, size_gb: int) -> str:
        """Aluga/cria um volume a partir de uma oferta de volume.

        PUT /api/v0/volumes {id, size} -> {"success": true, "volume_name": "V.xxxx"}
        Operação de COBRANÇA: passa pelo portão de mutações.
        """
        self.gate.require()
        _, data = await self.http.request(
            "PUT", VOLUMES_PATH, json_body={"id": offer_id, "size": size_gb}, idempotency=True
        )
        volume_name = data.get("volume_name")
        if data.get("success") is not True:
            raise VastVolumeError(
                str(data.get("msg") or "Falha ao alugar volume."),
                code=data.get("error") or "vast_volume_rent_failed",
                detail=data,
            )
        logger.info("Vast.ai: volume alugado (%s, %d GB)", volume_name, size_gb)
        return str(volume_name or "")

    # ------------------------------------------------------------------
    # Afinidade host <-> volume
    # ------------------------------------------------------------------
    @staticmethod
    def validate_host_affinity(volume: VastVolume, offer: VastOffer) -> None:
        """Garante que a oferta roda no MESMO host físico do volume.

        Documentação oficial: "A volume is physically tied to the machine it
        was created on. It can only be attached to instances running on the
        same physical machine."
        """
        if volume.machine_id is None:
            raise VastVolumeError(
                f"Volume {volume.id} sem machine_id registrado; impossível validar afinidade.",
                code="vast_volume_unknown_host",
            )
        if offer.machine_id != volume.machine_id:
            raise VastVolumeHostMismatchError(
                f"Volume {volume.id} pertence ao host {volume.machine_id}, "
                f"mas a oferta {offer.id} é do host {offer.machine_id}. "
                "Volumes locais da Vast.ai só podem ser usados no mesmo host físico.",
                code="vast_volume_host_mismatch",
                detail={"volume_machine_id": volume.machine_id, "offer_machine_id": offer.machine_id},
            )

    @staticmethod
    def assert_offer_supports_volume(offer: VastOffer) -> None:
        """Sinaliza se a oferta não consegue usar volume (§4: não selecionar
        oferta que não consiga utilizar o volume registrado).

        O campo oficial `avail_vol_ask_id` indica ask de volume disponível no
        host; se ausente e o host é outro que o do volume, o seletor já filtra.
        Aqui só registramos diagnóstico.
        """
        if offer.avail_vol_ask_id is None:
            logger.debug(
                "Oferta %s (host %s) sem ask de volume disponível — "
                "usável apenas se o volume já registrado for deste host.",
                offer.id,
                offer.machine_id,
            )


def build_volume_info(volume_id: int, mount_path: str = "/data", size_gb: int | None = None) -> dict:
    """Monta o campo `volume_info` oficial (associar volume na criação).

    Forma validada no SDK oficial (build_volume_info):
    {"mount_path": str, "create_new": bool, "volume_id": int, "size"?: int}
    """
    info: dict = {"mount_path": mount_path, "create_new": False, "volume_id": volume_id}
    if size_gb is not None:
        info["size"] = size_gb
    return info


__all__ = ["VastVolumesService", "VastVolumeHostMismatchError", "VastError", "build_volume_info"]
