"""Fail-closed connector scaffolding for sources without an approved profile."""

from dataclasses import dataclass
from typing import Any


class SourceProfileRequired(RuntimeError):
    """Raised until a source's technical and governance contract is documented."""


@dataclass(frozen=True)
class SourceProfile:
    provider_code: str
    product_code: str
    source_name: str
    required_profile: tuple[str, ...] = (
        "endpoint_and_protocol",
        "authentication_or_public_access",
        "payload_format_and_schema",
        "cadence_and_coverage",
        "terms_and_attribution",
        "access_collection_and_storage_approval",
    )


class PendingSourceConnector:
    """Independent connector placeholder; deliberately performs no network I/O."""

    profile: SourceProfile

    def fetch(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        raise SourceProfileRequired(
            f"{self.profile.provider_code}/{self.profile.product_code} is disabled: "
            "complete and approve its source profile before connecting."
        )
