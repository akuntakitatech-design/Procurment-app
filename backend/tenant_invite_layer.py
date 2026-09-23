"""Tenant-scoped user invitation flow for SaaS workspaces.

Invitation codes are public capabilities, but creation/list/cancel are restricted to the
authenticated tenant Admin. Public lookup/accept deliberately use the raw database only inside
this trusted layer so the invite can resolve its tenant before a normal tenant session exists.
"""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument

import auth as A
import saas_platform_layer as P


INVITE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ALLOWED_ROLES = {"admin", "director", "manager", "purchasing", "warehouse"}
ALLOWED_SCOPES = {"global", "limited"}


def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return now_dt().isoformat()


def _db(server):
    db = server.db
    raw = getattr(db, "_raw", None)
    return raw if raw is not None else db


def _require_tenant_admin(user: dict):
    if not user or user.get("is_platform_admin") or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Hanya Admin tenant yang dapat mengelola undangan user")


def _make_code() -> str:
    raw = "".join(secrets.choice(INVITE_CHARS) for _ in range(12))
    return f"INV-{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def _mask_email(email: str) -> str:
    local, _, domain = str(email or "").partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        masked = local[:1] + "*"
    else:
        masked = local[:2] + "*" * max(2, len(local) - 2)
    return f"{masked}@{domain}"


def _is_expired(invite: dict) -> bool:
    value = invite.get("expires_at")
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) <= now_dt()
    except ValueError:
        return True


def _invite_status(invite: dict) -> str:
    status = invite.get("status") or "pending"
    if status == "pending" and _is_expired(invite):
        return "expired"
    return status


def _clean_invite(invite: dict) -> dict:
    if not invite:
        return invite
    out = {k: v for k, v in invite.items() if k != "_id"}
    out["status"] = _invite_status(invite)
    return out


async def _tenant_and_capacity(db, tenant_id: str):
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
    if tenant.get("status") != "active":
        raise HTTPException(status_code=403, detail="Tenant sedang tidak aktif")
    subscription_status = (tenant.get("subscription") or {}).get("status")
    if subscription_status in {"expired", "suspended"}:
        raise HTTPException(status_code=403, detail="Langganan tenant sedang tidak aktif")

    plan = await db.plans.find_one({"id": tenant.get("plan_id")}, {"_id": 0}) or {}
    tenant_limits = tenant.get("limits") or {}
    maximum = tenant_limits.get("max_users") if "max_users" in tenant_limits else (plan.get("limits") or {}).get("max_users")
    current = await db.users.count_documents({
        "tenant_id": tenant_id,
        "is_platform_admin": {"$ne": True},
        "is_active": {"$ne": False},
    })
    if maximum is not None and current >= int(maximum):
        raise HTTPException(
            status_code=409,
            detail=f"Batas pengguna tenant sudah tercapai ({current}/{maximum}). Nonaktifkan user atau upgrade paket.",
        )
    return tenant, current, maximum


async def _validate_scope_refs(db, tenant_id: str, divisions: list[str], warehouses: list[str]):
    divs = list(dict.fromkeys(divisions or []))
    whs = list(dict.fromkeys(warehouses or []))
    if divs:
        count = await db.divisions.count_documents({"tenant_id": tenant_id, "id": {"$in": divs}})
        if count != len(divs):
            raise HTTPException(status_code=400, detail="Ada divisi undangan yang tidak valid untuk tenant ini")
    if whs:
        count = await db.warehouses.count_documents({"tenant_id": tenant_id, "id": {"$in": whs}})
        if count != len(whs):
            raise HTTPException(status_code=400, detail="Ada gudang undangan yang tidak valid untuk tenant ini")
    return divs, whs


class InviteCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    role: str = "warehouse"
    scope: str = "limited"
    divisions: list[str] = Field(default_factory=list)
    warehouses: list[str] = Field(default_factory=list)
    expires_hours: int = Field(default=72, ge=1, le=168)


class InviteAcceptIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


def install(server):
    app = server.app

    @app.on_event("startup")
    async def invite_indexes_startup():
        db = _db(server)
        await db.user_invitations.create_index("code", unique=True)
        await db.user_invitations.create_index([("tenant_id", 1), ("created_at", -1)])
        await db.user_invitations.create_index([("tenant_id", 1), ("email", 1), ("status", 1)])

    @app.get("/api/invitations", tags=["invitations"])
    async def list_invitations(user=Depends(server.current_user)):
        _require_tenant_admin(user)
        tenant_id = user.get("tenant_id")
        db = _db(server)
        rows = await db.user_invitations.find(
            {"tenant_id": tenant_id}, {"_id": 0}
        ).sort("created_at", -1).to_list(1000)
        return [_clean_invite(row) for row in rows]

    @app.post("/api/invitations", tags=["invitations"])
    async def create_invitation(body: InviteCreateIn, user=Depends(server.current_user)):
        _require_tenant_admin(user)
        tenant_id = user.get("tenant_id")
        company_id = user.get("company_id")
        db = _db(server)

        tenant, current, maximum = await _tenant_and_capacity(db, tenant_id)
        company = await db.companies.find_one({"id": company_id, "tenant_id": tenant_id, "is_active": {"$ne": False}}, {"_id": 0})
        if not company:
            raise HTTPException(status_code=400, detail="Perusahaan user Admin tidak valid")

        email = str(body.email).strip().lower()
        if await db.users.find_one({"email": email}):
            raise HTTPException(status_code=409, detail="Email sudah terdaftar sebagai user")
        active_invite = await db.user_invitations.find_one({
            "tenant_id": tenant_id,
            "email": email,
            "status": "pending",
            "expires_at": {"$gt": now_iso()},
        })
        if active_invite:
            raise HTTPException(status_code=409, detail="Undangan aktif untuk email ini sudah ada")

        role = str(body.role or "warehouse").strip().lower()
        scope = str(body.scope or "limited").strip().lower()
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=400, detail="Role undangan tidak valid")
        if scope not in ALLOWED_SCOPES:
            raise HTTPException(status_code=400, detail="Scope undangan tidak valid")
        if role in {"admin", "director", "purchasing"}:
            scope = "global"

        divisions, warehouses = await _validate_scope_refs(db, tenant_id, body.divisions, body.warehouses)
        if scope == "global":
            divisions = []
            warehouses = []

        created = now_dt()
        expires = created + timedelta(hours=body.expires_hours)
        for _ in range(10):
            code = _make_code()
            if not await db.user_invitations.find_one({"code": code}):
                break
        else:
            raise HTTPException(status_code=500, detail="Gagal membuat kode undangan unik")

        permissions = list((getattr(server, "ROLE_DEFAULTS", {}) or {}).get(role, []))
        # server.py exposes ROLE_DEFAULTS as a module global, so getattr works after import;
        # keep a safe fallback for test/bootstrap ordering.
        if not permissions:
            permissions = {
                "admin": list(getattr(server, "ALL_PERMISSIONS", []) or []),
                "director": list(getattr(server, "ALL_PERMISSIONS", []) or []),
                "manager": ["view", "create", "edit", "submit", "approve", "reject", "cancel", "close", "print", "export", "view_all_division", "view_all_warehouse", "view_purchase_price"],
                "purchasing": ["view", "create", "edit", "submit", "cancel", "print", "export", "upload_attachment", "view_all_division", "view_all_warehouse", "view_purchase_price", "edit_purchase_price"],
                "warehouse": ["view", "create", "edit", "submit", "print", "upload_attachment", "direct_mi"],
            }.get(role, [])

        doc = {
            "id": str(uuid.uuid4()),
            "code": code,
            "tenant_id": tenant_id,
            "tenant_code": tenant.get("tenant_code"),
            "company_id": company_id,
            "name": body.name.strip(),
            "email": email,
            "role": role,
            "scope": scope,
            "divisions": divisions,
            "warehouses": warehouses,
            "permissions": permissions,
            "status": "pending",
            "created_by": user.get("id"),
            "created_by_email": user.get("email"),
            "created_at": created.isoformat(),
            "expires_at": expires.isoformat(),
            "used_at": None,
            "used_by_user_id": None,
            "cancelled_at": None,
            "cancelled_by": None,
        }
        await db.user_invitations.insert_one(doc)
        await server.audit(user, "invite_create", "user_invitation", doc["id"], doc_no=code, after={"email": email, "role": role, "expires_at": doc["expires_at"]})
        await P._platform_audit(server, user, "invite.created", tenant_id, {"code": code, "email": email, "role": role, "expires_at": doc["expires_at"]})
        result = _clean_invite(doc)
        result["usage"] = {"active_users": current, "max_users": maximum}
        return result

    @app.post("/api/invitations/{invite_id}/cancel", tags=["invitations"])
    async def cancel_invitation(invite_id: str, user=Depends(server.current_user)):
        _require_tenant_admin(user)
        tenant_id = user.get("tenant_id")
        db = _db(server)
        invite = await db.user_invitations.find_one({"id": invite_id, "tenant_id": tenant_id}, {"_id": 0})
        if not invite:
            raise HTTPException(status_code=404, detail="Undangan tidak ditemukan")
        if _invite_status(invite) != "pending":
            raise HTTPException(status_code=409, detail="Hanya undangan aktif yang dapat dibatalkan")
        updated = await db.user_invitations.find_one_and_update(
            {"id": invite_id, "tenant_id": tenant_id, "status": "pending"},
            {"$set": {"status": "cancelled", "cancelled_at": now_iso(), "cancelled_by": user.get("id")}},
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            raise HTTPException(status_code=409, detail="Status undangan sudah berubah")
        await server.audit(user, "invite_cancel", "user_invitation", invite_id, doc_no=invite.get("code"))
        await P._platform_audit(server, user, "invite.cancelled", tenant_id, {"code": invite.get("code"), "email": invite.get("email")})
        return _clean_invite(updated)

    @app.get("/api/invitations/public/{code}", tags=["invitations"])
    async def public_invitation(code: str):
        db = _db(server)
        normalized = str(code or "").strip().upper()
        invite = await db.user_invitations.find_one({"code": normalized}, {"_id": 0})
        if not invite:
            raise HTTPException(status_code=404, detail="Kode undangan tidak ditemukan")
        status = _invite_status(invite)
        if status == "expired":
            raise HTTPException(status_code=410, detail="Undangan sudah kedaluwarsa")
        if status != "pending":
            raise HTTPException(status_code=410, detail="Undangan sudah tidak aktif")
        tenant = await db.tenants.find_one({"id": invite.get("tenant_id")}, {"_id": 0})
        if not tenant or tenant.get("status") != "active":
            raise HTTPException(status_code=403, detail="Tenant sedang tidak aktif")
        return {
            "code": invite.get("code"),
            "tenant_code": tenant.get("tenant_code"),
            "tenant_name": tenant.get("name"),
            "name": invite.get("name"),
            "email_hint": _mask_email(invite.get("email")),
            "role": invite.get("role"),
            "scope": invite.get("scope"),
            "expires_at": invite.get("expires_at"),
        }

    @app.post("/api/invitations/public/{code}/accept", tags=["invitations"])
    async def accept_invitation(code: str, body: InviteAcceptIn):
        db = _db(server)
        normalized = str(code or "").strip().upper()
        invite = await db.user_invitations.find_one({"code": normalized}, {"_id": 0})
        if not invite:
            raise HTTPException(status_code=404, detail="Kode undangan tidak ditemukan")
        status = _invite_status(invite)
        if status == "expired":
            raise HTTPException(status_code=410, detail="Undangan sudah kedaluwarsa")
        if status != "pending":
            raise HTTPException(status_code=410, detail="Undangan sudah tidak aktif")

        tenant_id = invite.get("tenant_id")
        await _tenant_and_capacity(db, tenant_id)
        if await db.users.find_one({"email": invite.get("email")}):
            raise HTTPException(status_code=409, detail="Email sudah terdaftar sebagai user")

        claimed = await db.user_invitations.find_one_and_update(
            {
                "id": invite.get("id"),
                "tenant_id": tenant_id,
                "status": "pending",
                "expires_at": {"$gt": now_iso()},
            },
            {"$set": {"status": "activating", "activation_started_at": now_iso()}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            raise HTTPException(status_code=409, detail="Undangan sedang diproses atau sudah tidak aktif")

        uid = str(uuid.uuid4())
        inserted = False
        try:
            await _tenant_and_capacity(db, tenant_id)
            if await db.users.find_one({"email": claimed.get("email")}):
                raise HTTPException(status_code=409, detail="Email sudah terdaftar sebagai user")
            company = await db.companies.find_one({
                "id": claimed.get("company_id"),
                "tenant_id": tenant_id,
                "is_active": {"$ne": False},
            }, {"_id": 0})
            if not company:
                raise HTTPException(status_code=409, detail="Perusahaan pada undangan sudah tidak aktif")

            user_doc = {
                "id": uid,
                "tenant_id": tenant_id,
                "company_id": claimed.get("company_id"),
                "email": claimed.get("email"),
                "password_hash": A.hash_password(body.password),
                "name": claimed.get("name"),
                "role": claimed.get("role") or "warehouse",
                "divisions": claimed.get("divisions") or [],
                "warehouses": claimed.get("warehouses") or [],
                "permissions": claimed.get("permissions") or [],
                "scope": claimed.get("scope") or "limited",
                "is_active": True,
                "token_version": 0,
                "signature_url": None,
                "email_verified": False,
                "invitation_id": claimed.get("id"),
                "created_at": now_iso(),
            }
            await db.users.insert_one(user_doc)
            inserted = True
            used_at = now_iso()
            await db.user_invitations.update_one(
                {"id": claimed.get("id"), "status": "activating"},
                {"$set": {"status": "used", "used_at": used_at, "used_by_user_id": uid}, "$unset": {"activation_started_at": ""}},
            )
            await db.audit_logs.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user": claimed.get("email"),
                "user_name": claimed.get("name"),
                "action": "invite_accept",
                "entity": "user_invitation",
                "entity_id": claimed.get("id"),
                "doc_no": claimed.get("code"),
                "after": {"user_id": uid, "role": claimed.get("role")},
                "at": used_at,
            })
            await P._platform_audit(server, user_doc, "invite.accepted", tenant_id, {"code": claimed.get("code"), "email": claimed.get("email"), "user_id": uid})
            return {
                "ok": True,
                "message": "Akun berhasil diaktifkan. Silakan masuk menggunakan email dan password baru.",
                "tenant_code": claimed.get("tenant_code"),
                "email": claimed.get("email"),
            }
        except Exception:
            if inserted:
                await db.users.delete_one({"id": uid, "tenant_id": tenant_id})
            await db.user_invitations.update_one(
                {"id": claimed.get("id"), "status": "activating"},
                {"$set": {"status": "pending"}, "$unset": {"activation_started_at": ""}},
            )
            raise
