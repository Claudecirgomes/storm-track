from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

from backend.app.core.security import (
    create_session_token,
    digest_session_token,
    hash_password,
    verify_password,
)

_DUMMY_PASSWORD_HASH = hash_password("stormtrack-dummy-password-for-timing")


MAX_ACCOUNTS = 5
MAX_USERS = 4


class AccountError(Exception):
    """Base exception for account operations."""


class AccountLimitError(AccountError):
    pass


class AccountConflictError(AccountError):
    pass


class AccountNotFoundError(AccountError):
    pass


class AccountProtectionError(AccountError):
    pass


class AuthenticationError(AccountError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _log(connection: sqlite3.Connection, event_code: str, severity: str,
         actor_id: str | None = None, details: dict | None = None) -> None:
    connection.execute(
        "INSERT INTO operation_logs(id, actor_id, event_code, severity, details, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, event_code, severity,
         json.dumps(details or {}, separators=(",", ":")), _stamp(utc_now())),
    )


def provision_account(connection: sqlite3.Connection, username: str,
                      password: str, role: str, *, actor_id: str | None = None) -> dict:
    username = username.strip()
    role = role.upper().strip()
    if not username or len(username) > 80:
        raise ValueError("Username must contain 1 to 80 characters")
    if role not in {"ADMIN", "USER"}:
        raise ValueError("Role must be ADMIN or USER")
    password_hash = hash_password(password)
    account_id = str(uuid.uuid4())
    timestamp = _stamp(utc_now())
    try:
        connection.execute("BEGIN IMMEDIATE")
        if actor_id is not None:
            _require_administrator(connection, actor_id)
        total = connection.execute("SELECT COUNT(*) AS n FROM user_accounts WHERE deleted_at IS NULL").fetchone()["n"]
        users = connection.execute(
            "SELECT COUNT(*) AS n FROM user_accounts WHERE role = 'USER' AND deleted_at IS NULL"
        ).fetchone()["n"]
        admins = connection.execute(
            "SELECT COUNT(*) AS n FROM user_accounts WHERE role = 'ADMIN'"
        ).fetchone()["n"]
        if total >= MAX_ACCOUNTS or (role == "USER" and users >= MAX_USERS):
            raise AccountLimitError("Pilot account limit reached (1 ADMIN + up to 4 USER)")
        if role == "ADMIN" and admins >= 1:
            raise AccountConflictError("The pilot already has its single ADMIN account")
        connection.execute(
            "INSERT INTO user_accounts(id, username, password_hash, role, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?)",
            (account_id, username, password_hash, role, timestamp, timestamp),
        )
        _log(connection, "ACCOUNT_PROVISIONED", "INFO", actor_id, {"role": role, "target_id": account_id})
        connection.commit()
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise AccountConflictError("Username already exists or account constraint failed") from exc
    except Exception:
        connection.rollback()
        raise
    return {"id": account_id, "username": username, "role": role, "status": "ACTIVE"}


def authenticate_and_issue_session(connection: sqlite3.Connection, username: str,
                                   password: str, ttl_minutes: int) -> tuple[dict, str, str]:
    # Serialize login with resets, blocking and deletion: an old password cannot
    # create a session after a concurrent reset has already invalidated sessions.
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT id, username, password_hash, role, status FROM user_accounts "
            "WHERE ascii_nocase(username) = ascii_nocase(?) AND deleted_at IS NULL", (username.strip(),),
        ).fetchone()
        password_ok = verify_password(password, row["password_hash"] if row else _DUMMY_PASSWORD_HASH)
        if row is None or row["status"] != "ACTIVE" or not password_ok:
            _log(connection, "LOGIN_REJECTED", "WARNING")
            connection.commit()
            raise AuthenticationError("Invalid credentials")
        now = utc_now()
        expires_at = _stamp(now + timedelta(minutes=ttl_minutes))
        token = create_session_token()
        connection.execute(
            "INSERT INTO sessions(id, account_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row["id"], digest_session_token(token), _stamp(now), expires_at),
        )
        _log(connection, "LOGIN_SUCCEEDED", "INFO", row["id"])
        connection.commit()
        return ({"id": row["id"], "username": row["username"], "role": row["role"]}, token, expires_at)
    except Exception:
        connection.rollback()
        raise


def resolve_session(connection: sqlite3.Connection, token: str) -> dict | None:
    row = connection.execute(
        "SELECT a.id, a.username, a.role, a.status, s.expires_at "
        "FROM sessions s JOIN user_accounts a ON a.id = s.account_id "
        "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND a.deleted_at IS NULL",
        (digest_session_token(token),),
    ).fetchone()
    if row is None or row["status"] != "ACTIVE":
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return None
    if expires.tzinfo is None:
        return None
    if expires <= utc_now():
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def revoke_session(connection: sqlite3.Connection, token: str) -> None:
    connection.execute(
        "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (_stamp(utc_now()), digest_session_token(token)),
    )


_ACCOUNT_FIELDS = "id, username, role, status, created_at, updated_at"


def _require_administrator(connection: sqlite3.Connection, actor_id: str) -> None:
    actor = connection.execute(
        "SELECT role, status, deleted_at FROM user_accounts WHERE id = ?", (actor_id,),
    ).fetchone()
    if actor is None or actor["role"] != "ADMIN" or actor["status"] != "ACTIVE" or actor["deleted_at"]:
        raise AccountProtectionError("Acesso restrito ao administrador ativo.")


def list_accounts(connection: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in connection.execute(
        f"SELECT {_ACCOUNT_FIELDS} FROM user_accounts WHERE deleted_at IS NULL "
        "ORDER BY CASE role WHEN 'ADMIN' THEN 0 ELSE 1 END, ascii_nocase(username)"
    ).fetchall()]


def update_account(connection: sqlite3.Connection, account_id: str, changes: dict,
                   actor_id: str) -> dict:
    if not changes or set(changes) - {"username", "password", "status"}:
        raise ValueError("Informe nome, senha ou estado de acesso para alterar.")
    normalized = dict(changes)
    if "username" in normalized:
        value = normalized["username"]
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
            raise ValueError("O nome deve conter de 1 a 80 caracteres.")
        normalized["username"] = value.strip()
    password_hash = None
    if "password" in normalized:
        if not isinstance(normalized["password"], str):
            raise ValueError("Informe uma senha válida.")
        password_hash = hash_password(normalized["password"])
    if "status" in normalized and normalized["status"] not in {"ACTIVE", "DISABLED"}:
        raise ValueError("O acesso deve ser ACTIVE ou DISABLED.")
    connection.execute("BEGIN IMMEDIATE")
    try:
        _require_administrator(connection, actor_id)
        row = connection.execute(
            f"SELECT {_ACCOUNT_FIELDS} FROM user_accounts WHERE id = ? AND deleted_at IS NULL",
            (account_id,),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError("Conta não encontrada.")
        if row["role"] == "ADMIN" and normalized.get("status") == "DISABLED":
            raise AccountProtectionError("A conta do administrador não pode ser bloqueada.")
        username = normalized.get("username", row["username"])
        access_status = normalized.get("status", row["status"])
        timestamp = _stamp(utc_now())
        connection.execute(
            "UPDATE user_accounts SET username = ?, status = ?, updated_at = ? WHERE id = ?",
            (username, access_status, timestamp, account_id),
        )
        if password_hash is not None:
            connection.execute("UPDATE user_accounts SET password_hash = ? WHERE id = ?", (password_hash, account_id))
        sessions_revoked = password_hash is not None or access_status == "DISABLED" or username != row["username"]
        if sessions_revoked:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE account_id = ? AND revoked_at IS NULL",
                (timestamp, account_id),
            )
        _log(connection, "ACCOUNT_UPDATED", "INFO", actor_id, {
            "target_id": account_id, "username": username,
            "changed_fields": sorted(normalized), "sessions_revoked": sessions_revoked,
        })
        result = dict(connection.execute(f"SELECT {_ACCOUNT_FIELDS} FROM user_accounts WHERE id = ?", (account_id,)).fetchone())
        connection.commit()
        return {**result, "sessions_revoked": sessions_revoked}
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise AccountConflictError("Já existe uma conta com esse nome.") from exc
    except Exception:
        connection.rollback()
        raise


def delete_account(connection: sqlite3.Connection, account_id: str, actor_id: str) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        _require_administrator(connection, actor_id)
        row = connection.execute(
            "SELECT id, username, role FROM user_accounts WHERE id = ? AND deleted_at IS NULL", (account_id,),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError("Conta não encontrada.")
        if row["role"] == "ADMIN":
            raise AccountProtectionError("A conta do administrador não pode ser excluída.")
        timestamp = _stamp(utc_now())
        # Retain the account ID for audit links, but remove login credentials and
        # release both the username and the pilot user slot.
        connection.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
        connection.execute(
            "UPDATE user_accounts SET username = ?, password_hash = 'deleted', status = 'DISABLED', "
            "deleted_at = ?, updated_at = ? WHERE id = ?",
            (f"deleted:{account_id}", timestamp, timestamp, account_id),
        )
        _log(connection, "ACCOUNT_DELETED", "INFO", actor_id, {
            "target_id": account_id, "username": row["username"], "role": row["role"],
        })
        connection.commit()
    except Exception:
        connection.rollback()
        raise
