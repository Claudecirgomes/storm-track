"""Inspect or transfer a consistent SQLite snapshot to PostgreSQL.

Inspection is the default and never connects to a destination. Applying a
migration requires --apply and STORMTRACK_DATABASE_URL. Existing local sessions
are intentionally omitted so that everyone signs in again after the cutover.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys

from backend.app.core.config import get_settings
from backend.app.core.db import connect, initialize_database


# Parent tables precede children. Never derive SQL identifiers from external data.
TABLE_COLUMNS = {
    "user_accounts": ("id", "username", "password_hash", "role", "status", "created_at", "updated_at", "deleted_at"),
    "data_sources": ("id", "provider_code", "name", "created_at"),
    "source_products": ("id", "source_id", "product_code", "access_status", "collection_status", "storage_status",
                        "redistribution_status", "terms_reference", "access_verified_at", "enabled", "created_at"),
    "operation_logs": ("id", "actor_id", "event_code", "severity", "details", "occurred_at"),
    "data_artifacts": ("id", "artifact_type", "content_hash", "raw_reference", "created_at"),
    "observations": ("artifact_id", "product_id", "observed_at_utc", "received_at_utc", "original_timestamp",
                     "original_offset", "deduplication_key", "data_type"),
    "observation_revisions": ("id", "observation_id", "revision_number", "content_hash", "observed_at_utc",
                             "original_timestamp", "original_offset", "data_type", "normalized_payload_json",
                             "geometry_json", "original_unit", "received_at_utc", "raw_reference"),
    "data_quality_assessments": ("id", "observation_id", "assessed_at", "completeness", "delay_seconds",
                                "availability", "resolution"),
    "source_health": ("id", "source_id", "checked_at", "status", "failure_reason"),
    "collection_runs": ("id", "product_id", "started_at", "finished_at", "status", "objects_seen",
                        "observations_written", "error_code", "details_json"),
    "ingestion_cursors": ("product_id", "last_object_key", "updated_at"),
    "sessions": ("id", "account_id", "token_hash", "created_at", "expires_at", "revoked_at"),
}


class MigrationError(RuntimeError):
    """An error whose message contains no row contents or credentials."""


@dataclass(frozen=True)
class TableSummary:
    source_rows: int
    destination_rows: int


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's original message can repeat a secret passed by mistake.
        super().error("Argumentos inválidos. Use --help para consultar as opções.")


def _sqlite(connection):
    return isinstance(connection, sqlite3.Connection)


def _table_names(connection):
    if _sqlite(connection):
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    else:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'stormtrack' AND table_type = 'BASE TABLE'"
        )
    return {row[0] for row in rows}


def _columns(connection, table):
    if _sqlite(connection):
        return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    return {row[0] for row in connection.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'stormtrack' AND table_name = ?",
        (table,),
    )}


def _validate_schema(connection, *, allow_legacy=False):
    if _table_names(connection) != set(TABLE_COLUMNS):
        raise MigrationError("O esquema deve conter exatamente as tabelas esperadas do StormTrack.")
    missing_deleted_at = False
    for table, expected in TABLE_COLUMNS.items():
        actual = _columns(connection, table)
        if actual == set(expected):
            continue
        if allow_legacy and table == "user_accounts" and actual == set(expected) - {"deleted_at"}:
            missing_deleted_at = True
            continue
        raise MigrationError(f"Esquema incompatível na tabela {table}.")
    return missing_deleted_at


@contextmanager
def source_snapshot(source_path):
    """Take a consistent backup in memory through a read-only source connection."""
    source = None
    snapshot = sqlite3.connect(":memory:", isolation_level=None)
    snapshot.row_factory = sqlite3.Row
    try:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise MigrationError("O banco SQLite de origem não existe.")
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        source.execute("PRAGMA query_only = ON")
        source.backup(snapshot)
        source.close()
        source = None
        legacy = _validate_schema(snapshot, allow_legacy=True)
        if legacy:
            snapshot.execute("ALTER TABLE user_accounts ADD COLUMN deleted_at TEXT")
        if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise MigrationError("A verificação de integridade do banco de origem falhou.")
        if snapshot.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationError("O banco de origem contém referências inválidas.")
        snapshot.execute("PRAGMA query_only = ON")
        yield snapshot
    finally:
        if source is not None:
            source.close()
        snapshot.close()


def _select(table):
    return "SELECT " + ", ".join(f'"{column}"' for column in TABLE_COLUMNS[table]) + f' FROM "{table}"'


def _canonical(value):
    if value is None:
        return ["null"]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and not math.isfinite(value):
            raise MigrationError("Foi encontrado um valor numérico não finito.")
        number = Decimal(str(value))
        if not number.is_finite():
            raise MigrationError("Foi encontrado um valor numérico não finito.")
        # SQLite REAL and PostgreSQL DOUBLE PRECISION may return 1.0 or 1.
        return ["number", "0" if number == 0 else str(number.normalize())]
    if isinstance(value, (bytes, memoryview)):
        return ["bytes", bytes(value).hex()]
    raise MigrationError("Foi encontrado um tipo de dado não suportado pela transferência.")


def content_digest(connection, table):
    """Hash every selected column, independent of database row-order/collation."""
    row_hashes = []
    for row in connection.execute(_select(table)):
        payload = json.dumps([_canonical(row[index]) for index in range(len(TABLE_COLUMNS[table]))],
                             ensure_ascii=False, separators=(",", ":"))
        row_hashes.append(hashlib.sha256(payload.encode("utf-8")).digest())
    digest = hashlib.sha256()
    for row_hash in sorted(row_hashes):
        digest.update(row_hash)
    return len(row_hashes), digest.digest()


def inspect_snapshot(snapshot):
    return {
        table: TableSummary(
            source_rows=snapshot.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
            destination_rows=0 if table == "sessions" else snapshot.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0],
        )
        for table in TABLE_COLUMNS
    }


def transfer_snapshot(snapshot, destination):
    """Copy and verify into an empty initialized target in one transaction.

    A SQLite target is supported only by this internal helper for isolated tests.
    The public migration entry point requires a PostgreSQL URL.
    """
    _validate_schema(snapshot)
    _validate_schema(destination)
    transaction_started = False
    try:
        destination.execute("BEGIN IMMEDIATE")
        transaction_started = True
        if not _sqlite(destination):
            tables = ", ".join(f'"{table}"' for table in TABLE_COLUMNS)
            # All tables are locked before emptiness checks, preventing a race
            # with provisioning, audit, collection or session writes.
            destination.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")
        for table in TABLE_COLUMNS:
            if destination.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] != 0:
                raise MigrationError(f"O destino precisa estar vazio; a tabela {table} contém registros.")
        for table, columns in TABLE_COLUMNS.items():
            if table == "sessions":
                continue
            statement = (
                f'INSERT INTO "{table}" (' + ", ".join(f'"{column}"' for column in columns)
                + ") VALUES (" + ", ".join("?" for _ in columns) + ")"
            )
            for row in snapshot.execute(_select(table)):
                destination.execute(statement, tuple(row))
        for table in TABLE_COLUMNS:
            if table == "sessions":
                if destination.execute('SELECT COUNT(*) FROM "sessions"').fetchone()[0] != 0:
                    raise MigrationError("A verificação das sessões vazias falhou.")
                continue
            if content_digest(snapshot, table) != content_digest(destination, table):
                raise MigrationError(f"A verificação de conteúdo falhou na tabela {table}.")
        destination.execute("COMMIT")
        transaction_started = False
        return inspect_snapshot(snapshot)
    except Exception:
        if transaction_started:
            destination.execute("ROLLBACK")
        raise


def migrate(source_path, *, apply=False, database_url=None, connect_fn=None, initialize_fn=None):
    """Inspect by default; optional injected callbacks make verification offline."""
    if apply and (
        not isinstance(database_url, str)
        or not database_url.strip().lower().startswith(("postgresql://", "postgres://"))
    ):
        raise MigrationError("Configure STORMTRACK_DATABASE_URL com uma conexão PostgreSQL antes de aplicar.")
    with source_snapshot(source_path) as snapshot:
        if not apply:
            return inspect_snapshot(snapshot)
        initialize = initialize_fn if initialize_fn is not None else initialize_database
        connection_factory = connect_fn if connect_fn is not None else connect
        initialize(database_url)
        destination = connection_factory(database_url)
        try:
            return transfer_snapshot(snapshot, destination)
        finally:
            destination.close()


def main(argv=None):
    parser = _SafeArgumentParser(description="Inspeciona ou transfere o SQLite do StormTrack para PostgreSQL/Supabase.")
    parser.add_argument("--source", type=Path, help="Caminho do SQLite de origem; padrão: STORMTRACK_DATA_DIR/stormtrack.sqlite3.")
    parser.add_argument("--apply", action="store_true", help="Aplica no destino configurado em STORMTRACK_DATABASE_URL.")
    args = parser.parse_args(argv)
    try:
        source_path = args.source if args.source is not None else get_settings().database_path
        report = migrate(source_path, apply=args.apply, database_url=os.getenv("STORMTRACK_DATABASE_URL"))
        for table, summary in report.items():
            print(f"{table}: origem={summary.source_rows}; destino={summary.destination_rows}")
        if args.apply:
            print("Transferência concluída e verificada. Faça login novamente no novo servidor.")
        else:
            print("Inspeção concluída; nenhum dado foi transferido. Sessões não serão transferidas.")
        return 0
    except MigrationError as error:
        print(f"Transferência não aplicada: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Driver errors can include the DSN, passwords or failed row contents.
        print("Não foi possível concluir. Verifique o esquema, a conexão e as permissões do destino.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

