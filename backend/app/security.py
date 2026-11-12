"""Same-origin protection for the local API (pure ASGI middleware).

* Only 127.0.0.1/localhost Host headers are accepted (blocks DNS rebinding).
* A present Origin must be the app's own origin; cross-site fetches are rejected.
* Mutations require the ephemeral per-process session token (never logged, never put in URLs).
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from .config import Config

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
TOKEN_HEADER = b"x-eae-token"


class SecurityMiddleware:
    def __init__(self, app, cfg: Config, token: str) -> None:
        self.app, self.cfg, self.token = app, cfg, token

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        host = headers.get(b"host", b"").decode()
        origin = headers.get(b"origin", b"").decode()
        site = headers.get(b"sec-fetch-site", b"").decode()
        method = scope["method"]
        path = scope["path"]

        def deny(status: int, code: str, message: str):
            body = json.dumps({"error": {"code": code, "message": message}}).encode()
            return self._respond(send, status, body)

        if host not in self.cfg.allowed_hosts:
            await deny(400, "HOST_NOT_ALLOWED", "This request was not addressed to the local application.")
            return
        if origin and origin not in self.cfg.allowed_origins:
            await deny(403, "ORIGIN_NOT_ALLOWED", "Requests from other websites are not accepted.")
            return
        if site == "cross-site" or (site == "same-site" and not origin):
            await deny(403, "CROSS_SITE_BLOCKED", "Cross-site requests are not accepted.")
            return
        if method in MUTATING and path.startswith("/api/"):
            supplied = headers.get(TOKEN_HEADER, b"").decode()
            if not supplied or not secrets.compare_digest(supplied, self.token):
                await deny(403, "TOKEN_INVALID", "Missing or outdated session token. Reload the page.")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _respond(send, status: int, body: bytes) -> None:
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
