"""Compatibility layer for legacy attachment download links.

Older frontend links may pass the access token as ``?auth=...``. The legacy attachment
endpoint checks that query parameter and then incorrectly awaits the synchronous storage
initializer. More importantly, query-token authentication should enter the same normal JWT
path as Authorization-header authentication so tenant context is established consistently.

This middleware is installed after tenant isolation so it runs outermost. It converts only
attachment-download ``auth`` query tokens into a Bearer header and removes the query
parameter before the request reaches the legacy endpoint. Authentication and token-version
validation are still performed by the normal auth/isolation/security middleware chain.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode


def install(server):
    app = server.app

    @app.middleware("http")
    async def attachment_query_token_compat(request, call_next):
        path = request.url.path
        if request.method.upper() != "GET" or not re.fullmatch(r"/api/attachments/[^/]+/download", path):
            return await call_next(request)

        pairs = parse_qsl(request.scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        token = None
        kept = []
        for key, value in pairs:
            if key == "auth" and token is None:
                token = value
            else:
                kept.append((key, value))

        if token:
            # Preserve a normal Authorization header when already supplied. If absent, route
            # the query token through the exact same JWT validation path as Bearer auth.
            headers = list(request.scope.get("headers") or [])
            has_authorization = any(k.lower() == b"authorization" for k, _ in headers)
            if not has_authorization:
                headers.append((b"authorization", f"Bearer {token}".encode("latin-1")))
                request.scope["headers"] = headers

            # Prevent the legacy endpoint from entering its old ?auth branch. Other query
            # parameters are preserved exactly.
            request.scope["query_string"] = urlencode(kept, doseq=True).encode("latin-1")

        return await call_next(request)
