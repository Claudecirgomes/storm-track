from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid


GATE_FIELDS = ("access_status", "collection_status", "storage_status")
HEALTH_STATES = {"AVAILABLE", "DEGRADED", "UNAVAILABLE", "UNKNOWN"}


class IngestionBlocked(ValueError):
    """The product has not passed the local collection and storage gates."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_observed_at(value: str) -> tuple[datetime, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("observed_at must be an ISO-8601 timestamp with a UTC offset")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a UTC offset")
    offset = parsed.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return parsed, canonical, offset


def _canonical_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload and geometry must contain JSON-compatible finite values") from exc


def ingest_observation(
    connection: sqlite3.Connection,
    product_id: str,
    *,
    observed_at: str,
    deduplication_key: str,
    data_type: str,
    normalized_payload,
    geometry=None,
    original_unit: str | None = None,
    raw_reference: str | None = None,
) -> dict:
    """Persist one observation or append a new immutable content revision.

    This is an internal persistence service, not an enabled collector or API.
    """
    if not isinstance(product_id, str) or not product_id.strip():
        raise ValueError("product_id is required")
    if not isinstance(deduplication_key, str) or not deduplication_key.strip() or len(deduplication_key) > 500:
        raise ValueError("deduplication_key must contain 1 to 500 characters")
    if not isinstance(data_type, str) or not data_type.strip() or len(data_type) > 100:
        raise ValueError("data_type must contain 1 to 100 characters")
    _, observed_utc, original_offset = _parse_observed_at(observed_at)
    payload_json = _canonical_json(normalized_payload)
    geometry_json = None if geometry is None else _canonical_json(geometry)
    content_hash = hashlib.sha256(
        _canonical_json({
            "observed_at_utc": observed_utc,
            "data_type": data_type.strip(),
            "payload": json.loads(payload_json),
            "geometry": None if geometry_json is None else json.loads(geometry_json),
            "original_unit": original_unit,
        }).encode("utf-8")
    ).hexdigest()
    received_at = utc_now().isoformat(timespec="microseconds").replace("+00:00", "Z")

    connection.execute("BEGIN IMMEDIATE")
    try:
        product = connection.execute(
            "SELECT access_status, collection_status, storage_status, terms_reference, enabled "
            "FROM source_products WHERE id = ?", (product_id,)
        ).fetchone()
        if product is None:
            raise ValueError("source product not found")
        if (not product["enabled"] or not product["terms_reference"] or
                not product["terms_reference"].strip() or
                any(product[field] != "VERIFIED" for field in GATE_FIELDS)):
            raise IngestionBlocked("product is not verified and enabled for local collection and storage")

        existing = connection.execute(
            "SELECT artifact_id FROM observations WHERE product_id = ? AND deduplication_key = ?",
            (product_id, deduplication_key.strip()),
        ).fetchone()
        if existing is not None:
            observation_id = existing["artifact_id"]
            latest = connection.execute(
                "SELECT revision_number, content_hash FROM observation_revisions "
                "WHERE observation_id = ? ORDER BY revision_number DESC LIMIT 1", (observation_id,)
            ).fetchone()
            if latest is None:
                raise RuntimeError("observation has no immutable revision")
            if latest["content_hash"] == content_hash:
                connection.commit()
                return {"status": "DUPLICATE_IGNORED", "observation_id": observation_id,
                        "revision_number": latest["revision_number"]}
            revision_number = latest["revision_number"] + 1
            connection.execute(
                "INSERT INTO observation_revisions(id, observation_id, revision_number, content_hash, "
                "observed_at_utc, original_timestamp, original_offset, data_type, normalized_payload_json, "
                "geometry_json, original_unit, received_at_utc, raw_reference) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), observation_id, revision_number, content_hash,
                 observed_utc, observed_at.strip(), original_offset, data_type.strip(), payload_json,
                 geometry_json, original_unit, received_at, raw_reference),
            )
            connection.execute(
                "INSERT INTO operation_logs(id, actor_id, event_code, severity, details, occurred_at) "
                "VALUES (?, NULL, 'OBSERVATION_REVISION_APPENDED', 'INFO', ?, ?)",
                (str(uuid.uuid4()), json.dumps({"observation_id": observation_id,
                 "revision_number": revision_number, "product_id": product_id}, separators=(",", ":")), received_at),
            )
            connection.commit()
            return {"status": "REVISION_APPENDED", "observation_id": observation_id,
                    "revision_number": revision_number}

        observation_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO data_artifacts(id, artifact_type, content_hash, raw_reference, created_at) "
            "VALUES (?, 'OBSERVATION', ?, ?, ?)",
            (observation_id, content_hash, raw_reference, received_at),
        )
        connection.execute(
            "INSERT INTO observations(artifact_id, product_id, observed_at_utc, received_at_utc, "
            "original_timestamp, original_offset, deduplication_key, data_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (observation_id, product_id, observed_utc, received_at, observed_at.strip(),
             original_offset, deduplication_key.strip(), data_type.strip()),
        )
        connection.execute(
            "INSERT INTO observation_revisions(id, observation_id, revision_number, content_hash, "
            "observed_at_utc, original_timestamp, original_offset, data_type, normalized_payload_json, "
            "geometry_json, original_unit, received_at_utc, raw_reference) "
            "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), observation_id, content_hash, observed_utc, observed_at.strip(),
             original_offset, data_type.strip(), payload_json, geometry_json, original_unit,
             received_at, raw_reference),
        )
        connection.execute(
            "INSERT INTO operation_logs(id, actor_id, event_code, severity, details, occurred_at) "
            "VALUES (?, NULL, 'OBSERVATION_INGESTED', 'INFO', ?, ?)",
            (str(uuid.uuid4()), json.dumps({"observation_id": observation_id,
             "product_id": product_id, "revision_number": 1}, separators=(",", ":")), received_at),
        )
        connection.commit()
        return {"status": "CREATED", "observation_id": observation_id, "revision_number": 1}
    except Exception:
        connection.rollback()
        raise


def record_data_quality(connection: sqlite3.Connection, observation_id: str, *, completeness: float | None,
                        delay_seconds: int | None, availability: str, resolution: str | None = None) -> str:
    if availability not in HEALTH_STATES:
        raise ValueError("availability must be AVAILABLE, DEGRADED, UNAVAILABLE or UNKNOWN")
    if completeness is not None and (isinstance(completeness, bool) or not isinstance(completeness, (int, float)) or not 0 <= completeness <= 1):
        raise ValueError("completeness must be between 0 and 1 or unknown")
    if delay_seconds is not None and (isinstance(delay_seconds, bool) or not isinstance(delay_seconds, int) or delay_seconds < 0):
        raise ValueError("delay_seconds must be a non-negative integer or unknown")
    assessment_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO data_quality_assessments(id, observation_id, assessed_at, completeness, delay_seconds, availability, resolution) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (assessment_id, observation_id, utc_now().isoformat(timespec="seconds"), completeness,
         delay_seconds, availability, resolution),
    )
    return assessment_id


def record_source_health(connection: sqlite3.Connection, source_id: str, status: str,
                         failure_reason: str | None = None) -> str:
    if status not in HEALTH_STATES:
        raise ValueError("status must be AVAILABLE, DEGRADED, UNAVAILABLE or UNKNOWN")
    health_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO source_health(id, source_id, checked_at, status, failure_reason) VALUES (?, ?, ?, ?, ?)",
        (health_id, source_id, utc_now().isoformat(timespec="seconds"), status, failure_reason),
    )
    return health_id


def list_observations(connection: sqlite3.Connection, *, limit: int = 100,
                      data_type: str | None = None) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    params: list[object] = []
    where = ""
    if data_type:
        where = "WHERE o.data_type = ?"
        params.append(data_type)
    params.append(limit)
    rows = connection.execute(
        "SELECT o.artifact_id AS id, o.product_id, s.provider_code, p.product_code, o.data_type, "
        "o.observed_at_utc, o.received_at_utc, r.normalized_payload_json, r.geometry_json "
        "FROM observations o JOIN source_products p ON p.id=o.product_id "
        "JOIN data_sources s ON s.id=p.source_id "
        "JOIN observation_revisions r ON r.observation_id=o.artifact_id AND r.revision_number=("
        "SELECT MAX(r2.revision_number) FROM observation_revisions r2 WHERE r2.observation_id=o.artifact_id) "
        f"{where} ORDER BY o.observed_at_utc DESC LIMIT ?", params
    ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["normalized_payload"] = json.loads(item.pop("normalized_payload_json"))
        geometry_json = item.pop("geometry_json")
        item["geometry"] = json.loads(geometry_json) if geometry_json else None
        output.append(item)
    return output


def observations_geojson(connection: sqlite3.Connection, *, limit: int = 20,
                         max_features: int = 5_000) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if isinstance(max_features, bool) or not isinstance(max_features, int) or not 1 <= max_features <= 10_000:
        raise ValueError("max_features must be between 1 and 10000")
    observations = list_observations(connection, limit=limit, data_type="LIGHTNING_FLASHES")
    features = []
    for observation in observations:
        geometry = observation["geometry"]
        if not isinstance(geometry, dict) or geometry.get("type") != "FeatureCollection":
            continue
        for feature in geometry.get("features", []):
            if len(features) >= max_features:
                break
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                continue
            properties = dict(feature.get("properties") or {})
            properties.update({
                "observed_at": observation["observed_at_utc"],
                "provider": observation["provider_code"],
                "product": observation["product_code"],
                "observation_id": observation["id"],
            })
            features.append({"type": "Feature", "geometry": feature.get("geometry"),
                             "properties": properties})
        if len(features) >= max_features:
            break
    return {"type": "FeatureCollection", "features": features,
            "metadata": {"data_state": "AVAILABLE" if features else "NO_OBSERVATIONS",
                         "source": "NOAA GOES-19 GLM", "data_type": "LIGHTNING_FLASHES",
                         "redistribution_enabled": False}}
