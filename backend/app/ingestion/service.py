from datetime import datetime, timezone
import json
import sqlite3
import uuid

from backend.app.adapters import noaa_goes19_glm as glm
from backend.app.observations.service import (
    IngestionBlocked, ingest_observation, record_data_quality, record_source_health,
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_run(connection: sqlite3.Connection, *, product_id: str, started_at: str, status: str,
               objects_seen: int = 0, observations_written: int = 0,
               error_code: str | None = None, details: dict | None = None) -> None:
    connection.execute(
        "INSERT INTO collection_runs(id, product_id, started_at, finished_at, status, objects_seen, "
        "observations_written, error_code, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), product_id, started_at, _stamp(), status, objects_seen,
         observations_written, error_code,
         json.dumps(details or {}, sort_keys=True, separators=(",", ":"))),
    )


def collect_goes19_glm(connection: sqlite3.Connection, product_id: str, *, now=None,
                       lookback_minutes: int = 5) -> dict:
    """Run one bounded poll for the GOES-19 GLM flash product.

    This checks all local gates again at execution time. It only persists NOAA
    observations and never derives a storm, risk level, forecast, or alert.
    """
    started_at = _stamp()
    product = connection.execute(
        "SELECT p.*, s.provider_code, s.id AS source_id FROM source_products p "
        "JOIN data_sources s ON s.id = p.source_id WHERE p.id = ?", (product_id,)
    ).fetchone()
    if product is None:
        raise ValueError("source product not found")
    if product["provider_code"] != "NOAA" or product["product_code"] != glm.PRODUCT_CODE:
        raise ValueError("no adapter is registered for this source product")
    if (not product["enabled"] or not product["terms_reference"] or
            not product["terms_reference"].strip() or
            any(product[field] != "VERIFIED" for field in ("access_status", "collection_status", "storage_status"))):
        _write_run(connection, product_id=product_id, started_at=started_at, status="BLOCKED",
                   error_code="SOURCE_GATES_NOT_PASSED")
        record_source_health(connection, product["source_id"], "UNKNOWN", "Source gates are not passed")
        return {"status": "BLOCKED", "objects_seen": 0, "observations_written": 0}

    objects_seen = observations_written = 0
    try:
        # Rescan the bounded recent window: late-arriving objects may have an
        # older key than the last key seen. Observation de-duplication makes
        # overlapping polls safe; the cursor is informational, not a filter.
        objects = glm.list_recent_objects(now=now, after_key=None,
                                          lookback_minutes=lookback_minutes)
        for item in objects:
            objects_seen += 1
            raw = glm.download_object(item)
            parsed = glm.parse_netcdf(raw)
            result = ingest_observation(
                connection,
                product_id,
                observed_at=item.observed_at,
                deduplication_key=item.key,
                data_type="LIGHTNING_FLASHES",
                normalized_payload={
                    "provider": "NOAA",
                    "satellite": "GOES-19",
                    "instrument": "GLM",
                    "product": glm.PRODUCT_CODE,
                    "flash_count": parsed["flash_count"],
                    "source_key": item.key,
                },
                geometry=parsed["geometry"],
                raw_reference="https://noaa-goes19.s3.amazonaws.com/" + item.key,
            )
            if result["status"] in {"CREATED", "REVISION_APPENDED"}:
                observations_written += 1
            record_data_quality(
                connection, result["observation_id"], completeness=None,
                delay_seconds=None, availability="AVAILABLE",
                resolution="GLM-L2-LCFA: ponto de flash; resolução efetiva não inferida",
            )
            connection.execute(
                "INSERT INTO ingestion_cursors(product_id, last_object_key, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(product_id) DO UPDATE SET last_object_key=excluded.last_object_key, "
                "updated_at=excluded.updated_at",
                (product_id, item.key, _stamp()),
            )
        status = "SUCCEEDED" if objects else "NO_DATA"
        _write_run(connection, product_id=product_id, started_at=started_at, status=status,
                   objects_seen=objects_seen, observations_written=observations_written)
        record_source_health(connection, product["source_id"], "AVAILABLE")
        return {"status": status, "objects_seen": objects_seen,
                "observations_written": observations_written}
    except glm.AdapterError as exc:
        _write_run(connection, product_id=product_id, started_at=started_at, status="FAILED",
                   objects_seen=objects_seen, observations_written=observations_written,
                   error_code=exc.code)
        record_source_health(connection, product["source_id"], "DEGRADED", exc.code)
        return {"status": "FAILED", "objects_seen": objects_seen,
                "observations_written": observations_written, "error_code": exc.code}
    except IngestionBlocked:
        _write_run(connection, product_id=product_id, started_at=started_at, status="BLOCKED",
                   objects_seen=objects_seen, observations_written=observations_written,
                   error_code="SOURCE_GATES_NOT_PASSED")
        record_source_health(connection, product["source_id"], "UNKNOWN", "Source gates are not passed")
        return {"status": "BLOCKED", "objects_seen": objects_seen,
                "observations_written": observations_written}
    except Exception:
        _write_run(connection, product_id=product_id, started_at=started_at, status="FAILED",
                   objects_seen=objects_seen, observations_written=observations_written,
                   error_code="INTERNAL_COLLECTION_ERROR")
        record_source_health(connection, product["source_id"], "DEGRADED", "INTERNAL_COLLECTION_ERROR")
        return {"status": "FAILED", "objects_seen": objects_seen,
                "observations_written": observations_written,
                "error_code": "INTERNAL_COLLECTION_ERROR"}


def run_enabled_products(database_path, *, lookback_minutes: int = 5) -> list[dict]:
    from backend.app.core.db import connect

    connection = connect(database_path)
    try:
        products = connection.execute(
            "SELECT p.id, s.provider_code, p.product_code FROM source_products p "
            "JOIN data_sources s ON s.id = p.source_id WHERE p.enabled = 1 ORDER BY s.provider_code, p.product_code"
        ).fetchall()
        results = []
        for product in products:
            if product["provider_code"] == "NOAA" and product["product_code"] == glm.PRODUCT_CODE:
                results.append({"product_id": product["id"], **collect_goes19_glm(
                    connection, product["id"], lookback_minutes=lookback_minutes)})
        return results
    finally:
        connection.close()
