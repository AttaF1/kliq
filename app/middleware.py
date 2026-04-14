"""ASGI middleware for ``POST /match`` JSON bodies (avoids BaseHTTPMiddleware body bugs)."""

from __future__ import annotations

import json
import logging
from typing import Callable

from app.json_sanitize import escape_control_chars_inside_json_strings

logger = logging.getLogger(__name__)


def _header_value(scope: dict, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k.lower() == name.lower():
            return v.decode("latin-1")
    return ""


async def _read_request_body(receive: Callable) -> bytes:
    chunks: list[bytes] = []
    more = True
    while more:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    return b"".join(chunks)


class MatchJsonBodySanitizeMiddleware:
    """
    If ``POST /match`` sends ``application/json`` with illegal newlines/tabs
    inside string values, it rewrite the body to valid
    JSON before FastAPI parses it.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        method = scope.get("method") or ""
        if method != "POST" or path != "/match":
            await self.app(scope, receive, send)
            return

        ct = _header_value(scope, b"content-type")
        if "application/json" not in ct.lower():
            await self.app(scope, receive, send)
            return

        body = await _read_request_body(receive)
        if not body:
            async def empty_receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, empty_receive, send)
            return

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            async def replay_raw():
                return {"type": "http.request", "body": body, "more_body": False}

            await self.app(scope, replay_raw, send)
            return

        fixed = escape_control_chars_inside_json_strings(text)
        if fixed != text:
            try:
                json.loads(fixed)
            except json.JSONDecodeError:
                pass
            else:
                logger.debug("Normalized control characters in POST /match JSON body")
                body = fixed.encode("utf-8")

        async def replay():
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
