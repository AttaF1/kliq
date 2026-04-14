"""
API key authentication for protected routes.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configured_keys() -> frozenset[str]:
    raw = os.environ.get("KLIQ_API_KEYS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def _token_matches_any(keys: frozenset[str], token: str | None) -> bool:
    if not token:
        return False
    for k in keys:
        if len(k) != len(token):
            continue
        if secrets.compare_digest(k, token):
            return True
    return False


def verify_api_key_dependency(
    x_api_key: str | None = Security(_api_key_header),
    authorization: str | None = Header(None, include_in_schema=False),
) -> None:
    keys = _configured_keys()
    if not keys:
        return

    token = x_api_key
    if token is None and authorization:
        prefix = "bearer "
        if authorization.lower().startswith(prefix):
            token = authorization[len(prefix) :].strip() or None

    if not _token_matches_any(keys, token):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def auth_enabled() -> bool:
    """True when at least one API key is configured."""
    return bool(_configured_keys())
