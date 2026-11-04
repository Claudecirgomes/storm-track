"""Source catalogue entries. Candidates are not connections or approvals."""

import sqlite3
from datetime import datetime, timezone
import uuid


PENDING_CANDIDATES = (
    ("NOAA", "NOAA GOES-19", "GLM-L2-LCFA"),
    ("NOAA", "NOAA GOES-19", "ABI-L2-MCMIPF"),
    ("SIMEPAR", "SIMEPAR", "RADAR-PR"),
    ("SMN", "Servicio Meteorológico Nacional Argentina", "SINARAME-RADAR"),
    ("INUMET", "Instituto Uruguayo de Meteorología", "RADAR-UY"),
    ("DEFESA_CIVIL_RS", "Defesa Civil do Rio Grande do Sul", "ALERTAS-RS"),
    ("CPTEC", "CPTEC/INPE", "PRODUTO-SATELITE-RADAR"),
)


def integration_status(provider_code: str, product_code: str) -> str:
    if provider_code == "NOAA" and product_code == "GLM-L2-LCFA":
        return "ADAPTER_IMPLEMENTED_NOT_CONNECTED"
    if provider_code == "NOAA" and product_code == "ABI-L2-MCMIPF":
        return "DIRECT_IN_APP_IMAGES_ACTIVE_NO_ARCHIVE"
    return "CONNECTOR_SCAFFOLD_PENDING_SOURCE_PROFILE"


def ensure_candidate_products(connection: sqlite3.Connection) -> None:
    """Seed visible PENDING rows, never evidence, approvals, or enabled feeds."""
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for provider, name, product_code in PENDING_CANDIDATES:
            row = connection.execute(
                "SELECT id FROM data_sources WHERE ascii_nocase(provider_code) = ascii_nocase(?)", (provider,)
            ).fetchone()
            source_id = row["id"] if row else str(uuid.uuid4())
            if not row:
                connection.execute(
                    "INSERT INTO data_sources(id, provider_code, name, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (source_id, provider, name, timestamp),
                )
            exists = connection.execute(
                "SELECT 1 FROM source_products WHERE source_id = ? AND product_code = ?",
                (source_id, product_code),
            ).fetchone()
            if not exists:
                connection.execute(
                    "INSERT INTO source_products(id, source_id, product_code, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), source_id, product_code, timestamp),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
