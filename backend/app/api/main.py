from contextlib import asynccontextmanager
import asyncio
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.app.accounts.service import (
    AccountConflictError,
    AccountLimitError,
    AccountNotFoundError,
    AccountProtectionError,
    AuthenticationError,
    delete_account,
    list_accounts,
    provision_account,
    update_account,
    authenticate_and_issue_session,
    resolve_session,
    revoke_session,
)
from backend.app.core.config import get_settings
from backend.app.core.db import connect, initialize_database, database_health
from backend.app.ingestion.scheduler import scheduler_loop
from backend.app.observations.service import list_observations, observations_geojson
from backend.app.sources.candidates import ensure_candidate_products
from backend.app.sources.service import create_source_product, list_source_products, update_source_product
from backend.app.analysis.status import analysis_status
from backend.app.adapters.noaa_goes19_abi import (
    SatelliteSourceError,
    fetch_frame,
    list_frames,
    viewer_metadata,
)
from backend.app.adapters.registry import connector_catalog


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    # Cloud instances use a database prepared by the migration command. Do not
    # run schema DDL and catalog writes on every serverless cold start.
    if not settings.serverless:
        initialize_database(settings.database_target)
        connection = connect(settings.database_target)
        try:
            ensure_candidate_products(connection)
        finally:
            connection.close()
    task = None
    if settings.collection_enabled:
        task = asyncio.create_task(scheduler_loop(settings.database_target, settings.collection_interval_seconds))
    app.state.collection_task = task
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="StormTrack MVP API",
    version="0.1.0",
    description="MVP local-first; coleta NOAA opt-in, com gates por produto e método meteorológico ainda não aprovado.",
    lifespan=lifespan,
)
bearer = HTTPBearer(auto_error=False)


def database_connection():
    settings = get_settings()
    connection = connect(settings.database_target)
    try:
        yield connection
    finally:
        connection.close()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=256)


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    status: Literal["ACTIVE", "DISABLED"] | None = None


class SourceProductRequest(BaseModel):
    provider_code: str = Field(min_length=1, max_length=50)
    source_name: str = Field(min_length=1, max_length=150)
    product_code: str = Field(min_length=1, max_length=100)
    terms_reference: str | None = Field(default=None, max_length=500)


class SourceProductUpdate(BaseModel):
    access_status: Literal["PENDING", "VERIFIED", "BLOCKED"] | None = None
    collection_status: Literal["PENDING", "VERIFIED", "BLOCKED"] | None = None
    storage_status: Literal["PENDING", "VERIFIED", "BLOCKED"] | None = None
    redistribution_status: Literal["PENDING", "VERIFIED", "BLOCKED"] | None = None
    terms_reference: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


def current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    connection=Depends(database_connection),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    account = resolve_session(connection, credentials.credentials)
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return account


def administrator(account: dict = Depends(current_account)) -> dict:
    if account["role"] != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return account


@app.get("/api/health")
def health(connection=Depends(database_connection)):
    result = database_health(connection)
    settings = get_settings()
    return {"status": "ok" if result == "ok" else "degraded", "database": result,
            "database_backend": settings.database_backend,
            "collection": "enabled" if settings.collection_enabled else "disabled_by_default"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, connection=Depends(database_connection)):
    settings = get_settings()
    try:
        account, token, expires_at = authenticate_and_issue_session(
            connection, payload.username, payload.password, settings.session_ttl_minutes
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer", "expires_at": expires_at, "account": account}


@app.get("/api/auth/me")
def who_am_i(account: dict = Depends(current_account)):
    return account


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    _: dict = Depends(current_account),
    connection=Depends(database_connection),
):
    revoke_session(connection, credentials.credentials)
    return None


@app.get("/api/admin/accounts")
def accounts_list(_: dict = Depends(administrator), connection=Depends(database_connection)):
    return list_accounts(connection)


@app.post("/api/admin/accounts", status_code=status.HTTP_201_CREATED)
def accounts_create(payload: AccountCreateRequest, actor: dict = Depends(administrator),
                    connection=Depends(database_connection)):
    try:
        created = provision_account(connection, payload.username, payload.password, "USER", actor_id=actor["id"])
        return next(account for account in list_accounts(connection) if account["id"] == created["id"])
    except (AccountConflictError, AccountLimitError) as exc:
        detail = "Limite de quatro usuários atingido." if isinstance(exc, AccountLimitError) else "Já existe uma conta com esse nome."
        raise HTTPException(status_code=409, detail=detail) from exc
    except AccountProtectionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/admin/accounts/{account_id}")
def accounts_update(account_id: str, payload: AccountUpdateRequest,
                    actor: dict = Depends(administrator), connection=Depends(database_connection)):
    try:
        return update_account(connection, account_id, payload.model_dump(exclude_unset=True), actor["id"])
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountProtectionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/admin/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def accounts_delete(account_id: str, actor: dict = Depends(administrator),
                    connection=Depends(database_connection)):
    try:
        delete_account(connection, account_id, actor["id"])
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountProtectionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/api/source-products")
def source_products(_: dict = Depends(current_account), connection=Depends(database_connection)):
    return list_source_products(connection)


@app.get("/api/observations")
def observations(limit: int = 100, _: dict = Depends(current_account), connection=Depends(database_connection)):
    try:
        return list_observations(connection, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/observations/geojson")
def observations_map(_: dict = Depends(current_account), connection=Depends(database_connection)):
    return observations_geojson(connection)


@app.get("/api/ingestion/runs")
def ingestion_runs(limit: int = 50, _: dict = Depends(current_account), connection=Depends(database_connection)):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    return [dict(row) for row in connection.execute(
        "SELECT r.id, r.product_id, p.product_code, r.started_at, r.finished_at, r.status, "
        "r.objects_seen, r.observations_written, r.error_code "
        "FROM collection_runs r JOIN source_products p ON p.id=r.product_id "
        "ORDER BY r.started_at DESC LIMIT ?", (limit,)
    ).fetchall()]


@app.get("/api/analysis/status")
def analysis_readiness(_: dict = Depends(current_account)):
    return analysis_status()


@app.get("/api/connectors")
def connectors(_: dict = Depends(current_account)):
    """Return connector readiness without triggering network requests."""
    return connector_catalog()


@app.get("/api/satellite/goes19/abi")
def goes19_abi_viewer(_: dict = Depends(current_account)):
    """Return metadata for NOAA images shown directly inside the application."""
    return viewer_metadata()


@app.get("/api/satellite/goes19/abi/frames")
def goes19_abi_frames(limit: int = 12, _: dict = Depends(current_account)):
    try:
        return list_frames(limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SatelliteSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/satellite/goes19/abi/image/{filename}")
def goes19_abi_image(filename: str, _: dict = Depends(current_account)):
    try:
        image_bytes = fetch_frame(filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SatelliteSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(image_bytes, media_type="image/jpeg", headers={
        "Cache-Control": "private, max-age=3600, immutable",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    })


@app.get("/api/alerts")
def alert_feed(_: dict = Depends(current_account)):
    return {"status": "NOT_ISSUED", "items": [],
            "reason": "Método de alerta ainda não aprovado; nenhum alerta está sendo calculado."}


@app.post("/api/admin/source-products", status_code=status.HTTP_201_CREATED)
def add_source_product(
    payload: SourceProductRequest,
    _: dict = Depends(administrator),
    connection=Depends(database_connection),
):
    try:
        return create_source_product(
            connection, payload.provider_code, payload.source_name,
            payload.product_code, payload.terms_reference, actor_id=_["id"],
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Source product already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/admin/source-products/{product_id}")
def update_source_product_route(
    product_id: str,
    payload: SourceProductUpdate,
    account: dict = Depends(administrator),
    connection=Depends(database_connection),
):
    changes = payload.model_dump(exclude_unset=True)
    try:
        product = update_source_product(connection, product_id, changes, account["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="Source product not found")
    return product


@app.get("/api/admin/operation-logs")
def operation_logs(
    limit: int = 100,
    _: dict = Depends(administrator),
    connection=Depends(database_connection),
):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    rows = connection.execute(
        "SELECT id, actor_id, event_code, severity, details, occurred_at "
        "FROM operation_logs ORDER BY occurred_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


_frontend_dir = Path(__file__).resolve().parents[3] / "frontend"
app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
