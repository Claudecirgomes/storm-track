from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    session_ttl_minutes: int = 60
    collection_enabled: bool = False
    collection_interval_seconds: int = 60
    database_url: str | None = field(default=None, repr=False)
    serverless: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / "stormtrack.sqlite3"

    @property
    def database_target(self) -> Path | str:
        return self.database_url or self.database_path

    @property
    def database_backend(self) -> str:
        return "postgresql" if self.database_url else "sqlite"


def validate_database_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/") or parsed.fragment:
            raise ValueError()
        port = parsed.port
    except ValueError:
        raise ValueError("STORMTRACK_DATABASE_URL must be a valid PostgreSQL connection URL.") from None
    if parsed.hostname.endswith((".supabase.co", ".pooler.supabase.com")) and port == 6543:
        raise ValueError("Use a direct connection or Supabase session pooler on port 5432.")
    return value


def get_settings() -> Settings:
    serverless = os.getenv("VERCEL") == "1"
    raw_data_dir = os.getenv("STORMTRACK_DATA_DIR", "./data")
    database_url = os.getenv("STORMTRACK_DATABASE_URL", "").strip() or None
    if database_url is not None:
        database_url = validate_database_url(database_url)
    if serverless and database_url is None:
        raise ValueError("Set STORMTRACK_DATABASE_URL to PostgreSQL before deploying on Vercel; SQLite is local-only.")
    raw_ttl = os.getenv("STORMTRACK_SESSION_TTL_MINUTES", "60")
    try:
        ttl = int(raw_ttl)
    except ValueError as exc:
        raise ValueError("STORMTRACK_SESSION_TTL_MINUTES must be an integer") from exc
    if not 5 <= ttl <= 1440:
        raise ValueError("Session TTL must be between 5 and 1440 minutes")
    raw_interval = os.getenv("STORMTRACK_COLLECTION_INTERVAL_SECONDS", "60")
    try:
        interval = int(raw_interval)
    except ValueError as exc:
        raise ValueError("STORMTRACK_COLLECTION_INTERVAL_SECONDS must be an integer") from exc
    if not 20 <= interval <= 300:
        raise ValueError("Collection interval must be between 20 and 300 seconds")
    collection_enabled = os.getenv("STORMTRACK_COLLECTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    if serverless and collection_enabled:
        raise ValueError("Keep STORMTRACK_COLLECTION_ENABLED=false on Vercel; the continuous collector requires a separate worker.")
    return Settings(data_dir=Path(raw_data_dir).expanduser(), session_ttl_minutes=ttl,
                    collection_enabled=collection_enabled, collection_interval_seconds=interval,
                    database_url=database_url, serverless=serverless)
