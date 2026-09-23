"""Enforce tenant access after trial or paid subscription expiry.

Rules:
- full: normal application access
- limited: read-only access; safe reads plus print/export/download operations remain available
- locked: only authentication/session and subscription-status endpoints remain available
- suspended tenants are locked immediately

The gate runs on API requests and is intentionally enforced server-side so hiding frontend
buttons is never the security boundary.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse

import auth as A
import saas_platform_layer as SaaS
import subscription_lifecycle_layer as Lifecycle


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# These endpoints must remain available so a locked tenant can authenticate, learn why the
# workspace is locked, and sign out. Public SaaS endpoints have their own controls.
ALWAYS_ALLOWED_EXACT = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/refresh",
    "/api/auth/me",
    "/api/subscription/status",
}
ALWAYS_ALLOWED_PREFIXES = (
    "/api/saas/",
    "/api/verify/",
)

# Only exact path segments are treated as read-only actions. This intentionally does not match
# mutating resources such as /print-layouts.
LIMITED_READ_ACTION_SEGMENTS = {"export", "print", "download", "preview"}


def _has_auth(request) -> bool:
    if request.cookies.get("access_token"):
        return True
    return request.headers.get("Authorization", "").startswith("Bearer ")


def _limited_action_allowed(path: str) -> bool:
    segments = {segment for segment in path.lower().split("/") if segment}
    return bool(segments.intersection(LIMITED_READ_ACTION_SEGMENTS))


def _blocked(snapshot: dict, code: str, detail: str):
    return JSONResponse(
        status_code=403,
        content={
            "detail": detail,
            "code": code,
            "subscription": snapshot,
        },
    )


async def _public_invite_accept_allowed(server, path: str):
    """Resolve the invite tenant before account activation and enforce its access state."""
    prefix = "/api/invitations/public/"
    suffix = "/accept"
    if not (path.startswith(prefix) and path.endswith(suffix)):
        return None
    code = path[len(prefix):-len(suffix)].strip("/").upper()
    if not code:
        return None
    db = SaaS._global_db(server)
    invite = await db.user_invitations.find_one({"code": code}, {"_id": 0})
    if not invite:
        return None
    tenant = await db.tenants.find_one({"id": invite.get("tenant_id")}, {"_id": 0})
    if not tenant:
        return _blocked(
            {"access_mode": "locked", "phase": "locked", "tenant_id": invite.get("tenant_id")},
            "TENANT_LOCKED",
            "Workspace undangan tidak tersedia.",
        )
    snapshot = Lifecycle._evaluate(tenant, Lifecycle._now())
    if snapshot.get("access_mode") != "full":
        return _blocked(
            snapshot,
            "SUBSCRIPTION_LIMITED" if snapshot.get("access_mode") == "limited" else "SUBSCRIPTION_LOCKED",
            "Undangan user tidak dapat diaktifkan karena masa aktif workspace telah berakhir.",
        )
    return None


def install(server):
    app = server.app

    @app.middleware("http")
    async def subscription_access_gate(request, call_next):
        path = request.url.path
        method = request.method.upper()

        if not path.startswith("/api/"):
            return await call_next(request)

        # Public invite lookup remains available, but accepting an invite is a write operation
        # and is blocked once the target tenant enters limited/locked access.
        if path.startswith("/api/invitations/public/"):
            if method == "POST" and path.endswith("/accept"):
                blocked = await _public_invite_accept_allowed(server, path)
                if blocked is not None:
                    return blocked
            return await call_next(request)

        if path in ALWAYS_ALLOWED_EXACT or any(path.startswith(p) for p in ALWAYS_ALLOWED_PREFIXES):
            return await call_next(request)
        if not _has_auth(request):
            return await call_next(request)

        db = SaaS._global_db(server)
        try:
            user = await A.get_current_user(request, db)
        except Exception:
            # Let the normal authentication stack return the canonical auth error.
            return await call_next(request)

        if user.get("is_platform_admin"):
            return await call_next(request)

        tenant_id = user.get("tenant_id")
        if not tenant_id:
            return await call_next(request)

        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            return _blocked(
                {"access_mode": "locked", "phase": "locked", "tenant_id": tenant_id},
                "TENANT_LOCKED",
                "Workspace tidak ditemukan. Hubungi administrator platform.",
            )

        snapshot = Lifecycle._evaluate(tenant, Lifecycle._now())
        mode = snapshot.get("access_mode") or "full"

        if mode == "full":
            return await call_next(request)

        if mode == "limited":
            if method in SAFE_METHODS or _limited_action_allowed(path):
                return await call_next(request)
            return _blocked(
                snapshot,
                "SUBSCRIPTION_LIMITED",
                "Masa aktif telah berakhir. Workspace sedang dalam akses terbatas; perubahan data dan transaksi baru dinonaktifkan.",
            )

        return _blocked(
            snapshot,
            "SUBSCRIPTION_LOCKED",
            "Workspace terkunci karena masa akses setelah jatuh tempo telah berakhir atau workspace ditangguhkan.",
        )
