from dataclasses import dataclass
from enum import StrEnum


class GateStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CollectionGate:
    access_status: GateStatus
    collection_status: GateStatus
    storage_status: GateStatus
    redistribution_status: GateStatus
    enabled: bool


def collection_is_allowed(gate: CollectionGate) -> bool:
    """Local collection needs verified access, collection and storage.

    Redistribution is an independent permission and is deliberately not implied
    by local collection. It must be checked separately before any export/share.
    """
    return (
        gate.enabled
        and gate.access_status is GateStatus.VERIFIED
        and gate.collection_status is GateStatus.VERIFIED
        and gate.storage_status is GateStatus.VERIFIED
    )


def redistribution_is_allowed(gate: CollectionGate) -> bool:
    return collection_is_allowed(gate) and gate.redistribution_status is GateStatus.VERIFIED
