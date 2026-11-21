"""Adaptador Vast.ai do Control Plane.

Módulos:
- vast_client     : cliente HTTP com retry/backoff/idempotência
- vast_offers     : busca de ofertas (POST /api/v0/bundles/)
- vast_instances  : criação/consulta/estado/destruição de instâncias
- vast_volumes    : volumes persistentes + afinidade de host
- vast_billing    : cobranças reais (GET /api/v0/charges/)
- vast_schemas    : modelos Pydantic espelhando a API oficial
- vast_exceptions : erros tipados mapeados das respostas oficiais

A chave da Vast.ai vive somente no servidor de controle e nunca sai deste
pacote para camadas superiores (§3/§10 do adendo).
"""

from .vast_billing import VastBillingService
from .vast_client import VastClientConfig, VastHttpClient
from .vast_exceptions import (
    VastAuthError,
    VastError,
    VastInstanceCreateError,
    VastInstanceNotFoundError,
    VastInstanceUnrecoverableError,
    VastOfferUnavailableError,
    VastRateLimitError,
    VastServerError,
    VastTransportError,
    VastVolumeError,
    VastVolumeHostMismatchError,
)
from .vast_instances import MutationGate, VastInstancesService
from .vast_offers import VastOffersService
from .vast_schemas import (
    CreateInstanceRequest,
    HardwareRequirements,
    RentalType,
    VastInstance,
    VastOffer,
    VastVolume,
    VolumeAttachment,
)
from .vast_volumes import VastVolumesService

__all__ = [
    "VastClientConfig",
    "VastHttpClient",
    "VastOffersService",
    "VastInstancesService",
    "VastVolumesService",
    "VastBillingService",
    "MutationGate",
    "HardwareRequirements",
    "CreateInstanceRequest",
    "VolumeAttachment",
    "RentalType",
    "VastOffer",
    "VastInstance",
    "VastVolume",
    "VastError",
    "VastAuthError",
    "VastRateLimitError",
    "VastServerError",
    "VastTransportError",
    "VastOfferUnavailableError",
    "VastInstanceCreateError",
    "VastInstanceNotFoundError",
    "VastInstanceUnrecoverableError",
    "VastVolumeError",
    "VastVolumeHostMismatchError",
]
