import json
import sqlite3
import uuid

from backend.app.accounts.service import utc_now
from backend.app.sources.candidates import integration_status


GATE_FIELDS = ("access_status", "collection_status", "storage_status", "redistribution_status")
ALLOWED_GATE_STATES = {"PENDING", "VERIFIED", "BLOCKED"}


def create_source_product(connection: sqlite3.Connection, provider_code: str, source_name: str,
                          product_code: str, terms_reference: str | None = None,
                          actor_id: str | None = None) -> dict:
    provider_code = provider_code.strip().upper()
    source_name = source_name.strip()
    product_code = product_code.strip()
    if terms_reference is not None:
        terms_reference = terms_reference.strip() or None
    if not provider_code or not source_name or not product_code:
        raise ValueError("provider_code, source_name and product_code are required")
    connection.execute("BEGIN IMMEDIATE")
    try:
        source = connection.execute(
            "SELECT id, name FROM data_sources WHERE ascii_nocase(provider_code) = ascii_nocase(?)", (provider_code,)
        ).fetchone()
        if source:
            source_id = source["id"]
            source_name = source["name"]
        else:
            source_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO data_sources(id, provider_code, name, created_at) VALUES (?, ?, ?, ?)",
                (source_id, provider_code, source_name, utc_now().isoformat(timespec="seconds")),
            )
        product_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO source_products(id, source_id, product_code, terms_reference, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (product_id, source_id, product_code, terms_reference, utc_now().isoformat(timespec="seconds")),
        )
        _write_log(connection, actor_id, "SOURCE_PRODUCT_CREATED", {"provider_code": provider_code, "product_code": product_code})
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {
        "id": product_id,
        "provider_code": provider_code,
        "source_name": source_name,
        "product_code": product_code,
        "access_status": "PENDING",
        "collection_status": "PENDING",
        "storage_status": "PENDING",
        "redistribution_status": "PENDING",
        "enabled": False,
    }


def update_source_product(connection: sqlite3.Connection, product_id: str,
                          changes: dict, actor_id: str) -> dict | None:
    allowed_fields = set(GATE_FIELDS) | {"terms_reference", "enabled"}
    if not changes or not set(changes).issubset(allowed_fields):
        raise ValueError("Provide one or more supported source-product fields")
    for field in GATE_FIELDS:
        if field in changes and changes[field] not in ALLOWED_GATE_STATES:
            raise ValueError(f"Invalid value for {field}")
    if "terms_reference" in changes and changes["terms_reference"] is not None:
        changes["terms_reference"] = changes["terms_reference"].strip() or None
    if "enabled" in changes and not isinstance(changes["enabled"], bool):
        raise ValueError("enabled must be true or false")

    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT p.*, s.provider_code FROM source_products p "
            "JOIN data_sources s ON s.id = p.source_id WHERE p.id = ?", (product_id,)
        ).fetchone()
        if row is None:
            connection.rollback()
            return None
        current = dict(row)
        merged = {field: current[field] for field in GATE_FIELDS}
        merged.update({key: value for key, value in changes.items() if key in GATE_FIELDS})
        terms_reference = changes.get("terms_reference", current["terms_reference"])
        if terms_reference is not None:
            terms_reference = terms_reference.strip() or None
        enabled = changes.get("enabled", bool(current["enabled"]))
        required_gates = all(merged[field] == "VERIFIED" for field in ("access_status", "collection_status", "storage_status"))
        any_verified_gate = any(value == "VERIFIED" for value in merged.values())
        if any_verified_gate and not terms_reference:
            raise ValueError("Verified gate statuses require a terms/evidence reference")
        if enabled and (not required_gates or not terms_reference):
            raise ValueError("Enabling collection requires verified access, collection and storage plus a terms/evidence reference")
        if merged["redistribution_status"] == "VERIFIED" and (not required_gates or not terms_reference):
            raise ValueError("Verified redistribution requires verified access, collection and storage plus a terms/evidence reference")
        if not required_gates:
            enabled = False

        updates = dict(changes)
        updates["enabled"] = int(enabled)
        if "access_status" in changes and merged["access_status"] == "VERIFIED":
            updates["access_verified_at"] = utc_now().isoformat(timespec="seconds")
        elif "access_status" in changes:
            updates["access_verified_at"] = None
        assignments = ", ".join(f"{name} = ?" for name in updates)
        connection.execute(
            f"UPDATE source_products SET {assignments} WHERE id = ?",
            (*updates.values(), product_id),
        )
        _write_log(connection, actor_id, "SOURCE_PRODUCT_UPDATED", {
            "provider_code": current["provider_code"],
            "product_code": current["product_code"],
            "changed_fields": sorted(changes),
            "gate_changes": {key: value for key, value in changes.items() if key in GATE_FIELDS},
            "terms_reference_present": bool(terms_reference),
            "enabled": enabled,
        })
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return next((item for item in list_source_products(connection) if item["id"] == product_id), None)


def _write_log(connection: sqlite3.Connection, actor_id: str | None, event_code: str, details: dict) -> None:
    connection.execute(
        "INSERT INTO operation_logs(id, actor_id, event_code, severity, details, occurred_at) "
        "VALUES (?, ?, ?, 'INFO', ?, ?)",
        (str(uuid.uuid4()), actor_id, event_code,
         json.dumps(details, separators=(",", ":")), utc_now().isoformat(timespec="seconds")),
    )


def list_source_products(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        "SELECT p.id, s.provider_code, s.name AS source_name, p.product_code, "
        "p.access_status, p.collection_status, p.storage_status, p.redistribution_status, "
        "p.terms_reference, p.access_verified_at, p.enabled "
        "FROM source_products p JOIN data_sources s ON s.id = p.source_id "
        "ORDER BY s.provider_code, p.product_code"
    ).fetchall()
    return [dict(row) | {"enabled": bool(row["enabled"]),
                         "integration_status": integration_status(row["provider_code"], row["product_code"])}
            for row in rows]
