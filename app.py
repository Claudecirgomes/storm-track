"""Vercel's ASGI entrypoint; serves the existing API and unchanged frontend."""

from backend.app.api.main import app

__all__ = ["app"]
