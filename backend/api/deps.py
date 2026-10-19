"""FastAPI dependencies: database sessions and local-development authentication."""

from __future__ import annotations

import hmac
from collections.abc import Iterator

from fastapi import Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import session_factory


def get_db() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_auth(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None, include_in_schema=False),
) -> str:
    """AUTH_MODE=local: every request acts as the local developer (bind to localhost only).
    AUTH_MODE=token: requires `Authorization: Bearer <FORGE_API_TOKEN>` (or ?token= for SSE)."""
    settings = get_settings()
    if settings.auth_mode == "local":
        return "local-dev"
    expected = settings.forge_api_token.get_secret_value() if settings.forge_api_token else ""
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif token:
        supplied = token
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API token")
    return "token-user"
