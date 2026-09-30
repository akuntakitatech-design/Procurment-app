"""CP0 — Platform Admin Completion.

Adds the missing Platform Admin foundation on top of ``saas_platform_layer``:
- Create tenant (by Platform Admin) + first Tenant Admin (Pending Activation)
- Token-based activation flow (email-less friendly: activation URL returned for testing)
- Resend activation
- Suspend / Reactivate with reason + history
- Renewal / perpanjangan with period history
- Edit tenant profile / primary email / user limit / storage limit (audited)
- Storage usage metadata
- Platform dashboard KPIs + "Perlu Perhatian" attention feed

This layer never hard-deletes tenants and keeps every mutation tenant-aware and audited.
It reuses helpers from ``saas_platform_layer`` and is installed before tenant isolation so
platform routes operate on the global database via ``P._global_db``.
"""
from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument

import auth as A
import saas_platform_layer as P
import tenant_foundation_layer as T
import tenant_isolation_layer as I

# Activation tokens are platform-global and never exposed through tenant routes.
T.GLOBAL_COLLECTIONS.add("tenant_activations")
I.GLOBAL_COLLECTIONS.add("tenant_activations")

ACTIVATION_TTL_DAYS = int(os.environ.get("TENANT_ACTIVATION_TTL_DAYS", "7") or 7)
DEFAULT_STORAGE_LIMIT_GB = float(os.environ.get("DEFAULT_TENANT_STORAGE_GB", "20") or 20)
EXPIRING_SOON_DAYS = 30


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now().isoformat()


def _frontend_base() -> str:
    base = (os.environ.get("FRONTEND_URL", "") or "").split(",")[0].strip().rstrip("/")
    return base or "http://localhost:3000"


def _activation_url(token: str) -> str:
    return f"{_frontend_base()}/activation/{token}"


def _normalize_iso(value):
    """Accept 'YYYY-MM-DD' or ISO datetime; return a UTC ISO string or None."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raw = f"{raw}T23:59:59.999999"
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal tidak valid")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _as_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _mask_email(email: str) -> str:
    local, _, domain = str(email or "").partition("@")
    if not domain:
        return "***"
    masked = (local[:1] + "*") if len(local) <= 2 else (local[:2] + "*" * max(2, len(local) - 2))
    return f"{masked}@{domain}"


async def _plan_for(db, tenant: dict) -> dict:
    if tenant.get("plan_id"):
        return await db.plans.find_one({"id": tenant.get("plan_id")}, {"_id": 0}) or {}
    if tenant.get("plan_code"):
        return await db.plans.find_one({"code": tenant.get("plan_code")}, {"_id": 0}) or {}
    return {}


def _effective_limit(tenant: dict, plan: dict, key: str):
    limits = tenant.get("limits") or {}
    if key in limits and limits.get(key) is not None:
        return limits.get(key)
    return (plan.get("limits") or {}).get(key)


async def _active_user_count(db, tenant_id: str) -> int:
    return await db.users.count_documents({
        "tenant_id": tenant_id,
        "is_platform_admin": {"$ne": True},
        "is_active": {"$ne": False},
    })


async def _storage_usage(db, tenant_id: str, limit_gb=None) -> dict:
    rows = await db.attachments.find(
        {"tenant_id": tenant_id, "is_deleted": {"$ne": True}}, {"_id": 0, "size": 1}
    ).to_list(1000000)
    used_bytes = sum(int(r.get("size") or 0) for r in rows)
    used_gb = round(used_bytes / (1024 ** 3), 4)
    limit = limit_gb
    pct = None
    if limit not in (None, 0):
        pct = round((used_bytes / (float(limit) * (1024 ** 3))) * 100, 2)
    return {
        "used_bytes": used_bytes,
        "used_gb": used_gb,
        "limit_gb": limit,
        "percent": pct,
        "files": len(rows),
    }


def _subscription_view(tenant: dict) -> dict:
    sub = tenant.get("subscription") or {}
    status = str(sub.get("status") or "").lower()
    tenant_status = str(tenant.get("status") or "").lower()
    deadline = sub.get("ends_at") or sub.get("trial_ends_at")
    dl = _as_dt(deadline)
    days_remaining = None
    if dl is not None:
        days_remaining = (dl - _now()).days
    severity = "normal"
    display = status or "-"
    if tenant_status == "suspended" or status == "suspended":
        severity, display = "danger", "suspended"
    elif tenant_status == "pending_activation" or status == "pending_activation":
        severity, display = "warning", "pending_activation"
    elif status == "expired" or (days_remaining is not None and days_remaining < 0):
        severity, display = "danger", "expired"
    elif days_remaining is not None and days_remaining <= EXPIRING_SOON_DAYS:
        severity, display = "warning", "expiring_soon"
    elif status:
        display = status
    return {
        "status": status or "-",
        "display_status": display,
        "deadline": deadline,
        "days_remaining": days_remaining,
        "severity": severity,
        "started_at": sub.get("started_at"),
        "activated_at": sub.get("activated_at"),
    }


def _tenant_defaults(tenant_id: str, company_name: str, address):
    try:
        return P._tenant_defaults(tenant_id, company_name, address)
    except Exception:
        return []


# --------------------------------------------------------------------------- models
class TenantCreateIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    workspace_slug: str | None = Field(default=None, max_length=60)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    logo: str | None = None  # optional base64 data URL
    pic_name: str = Field(min_length=2, max_length=120)
    pic_position: str | None = Field(default=None, max_length=120)
    whatsapp: str = Field(min_length=6, max_length=40)
    email: EmailStr
    plan_code: str | None = None
    start_date: str | None = None
    ends_at: str | None = None
    max_users: int | None = Field(default=None, ge=1, le=100000)
    storage_limit_gb: float | None = Field(default=None, ge=0, le=1000000)
    notes: str | None = Field(default=None, max_length=1000)


class TenantProfilePatch(BaseModel):
    company_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    logo: str | None = None
    pic_name: str | None = Field(default=None, min_length=2, max_length=120)
    pic_position: str | None = Field(default=None, max_length=120)
    whatsapp: str | None = Field(default=None, min_length=6, max_length=40)
    email: EmailStr | None = None
    max_users: int | None = Field(default=None, ge=1, le=100000)
    storage_limit_gb: float | None = Field(default=None, ge=0, le=1000000)
    notes: str | None = Field(default=None, max_length=1000)


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReactivateIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RenewIn(BaseModel):
    start_date: str | None = None
    ends_at: str = Field(min_length=4)
    plan_code: str | None = None
    max_users: int | None = Field(default=None, ge=1, le=100000)
    storage_limit_gb: float | None = Field(default=None, ge=0, le=1000000)
    notes: str | None = Field(default=None, max_length=1000)


class ActivateIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


def install(server):
    app = server.app

    @app.on_event("startup")
    async def cp0_startup():
        db = P._global_db(server)
        try:
            await db.tenant_activations.create_index("token", unique=True)
            await db.tenant_activations.create_index([("tenant_id", 1), ("status", 1)])
        except Exception as exc:  # pragma: no cover
            server.logger.warning(f"cp0 index: {exc}")

    # ---- helpers bound to server ----
    async def _email_taken(db, email: str, exclude_user_id: str | None = None) -> bool:
        u = await db.users.find_one({"email": email}, {"_id": 0, "id": 1})
        if u and u.get("id") != exclude_user_id:
            return True
        t = await db.tenants.find_one({"contact.email": email}, {"_id": 0, "id": 1})
        if t:
            # allow if it belongs to the same tenant of the excluded user (handled by caller)
            return True if exclude_user_id is None else False
        return False

    async def _new_activation_token(db, tenant_id: str, user_id: str, email: str) -> dict:
        # Invalidate previous pending tokens for this tenant admin.
        await db.tenant_activations.update_many(
            {"tenant_id": tenant_id, "user_id": user_id, "status": "pending"},
            {"$set": {"status": "superseded", "superseded_at": _now_iso()}},
        )
        token = secrets.token_urlsafe(32)
        doc = {
            "id": str(uuid.uuid4()),
            "token": token,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "email": email,
            "status": "pending",
            "created_at": _now_iso(),
            "expires_at": (_now() + timedelta(days=ACTIVATION_TTL_DAYS)).isoformat(),
            "used_at": None,
        }
        await db.tenant_activations.insert_one(doc)
        return doc

    async def _detail(tenant_id: str, user):
        """Enriched CP0 tenant detail (reuses P.platform_tenant_detail then adds CP0 fields)."""
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        plan = await _plan_for(db, tenant)
        users = await db.users.find(
            {"tenant_id": tenant_id}, {"_id": 0, "password_hash": 0}
        ).sort("created_at", 1).to_list(5000)
        companies = await db.companies.find({"tenant_id": tenant_id}, {"_id": 0}).to_list(1000)
        audit_logs = await db.platform_audit_logs.find(
            {"tenant_id": tenant_id}, {"_id": 0}
        ).sort("at", -1).to_list(200)
        limit_gb = _effective_limit(tenant, plan, "storage_limit_gb")
        max_users = _effective_limit(tenant, plan, "max_users")
        active_users = await _active_user_count(db, tenant_id)
        pending_activation = await db.tenant_activations.find_one(
            {"tenant_id": tenant_id, "status": "pending"}, {"_id": 0, "token": 1, "expires_at": 1, "email": 1}
        )
        return {
            **tenant,
            "plan": P._public_plan(plan),
            "usage": await P._usage(db, tenant_id),
            "companies": companies,
            "users": users,
            "audit_logs": audit_logs,
            "subscription_view": _subscription_view(tenant),
            "subscription_history": tenant.get("subscription_history") or [],
            "suspend_history": tenant.get("suspend_history") or [],
            "effective_limits": {"max_users": max_users, "storage_limit_gb": limit_gb},
            "user_usage": {"active": active_users, "limit": max_users},
            "storage": await _storage_usage(db, tenant_id, limit_gb),
            "pending_activation": bool(pending_activation),
            "activation": ({"activation_url": _activation_url(pending_activation["token"]),
                            "email": pending_activation.get("email"),
                            "expires_at": pending_activation.get("expires_at")}
                           if pending_activation else None),
        }

    # ---- CREATE TENANT ----
    @app.post("/api/platform/tenants", tags=["platform"])
    async def create_tenant(body: TenantCreateIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        email = str(body.email).strip().lower()

        if await _email_taken(db, email):
            raise HTTPException(status_code=409, detail="Email utama sudah digunakan tenant/user lain")

        slug = P._slugify(body.workspace_slug or body.company_name)
        if len(slug) < 3:
            raise HTTPException(status_code=400, detail="Workspace/slug terlalu pendek (min 3 karakter)")
        if await db.tenants.find_one({"slug": slug}):
            raise HTTPException(status_code=409, detail="Workspace/slug sudah digunakan")

        plan = {}
        if body.plan_code:
            plan = await db.plans.find_one({"code": body.plan_code.strip().lower()}, {"_id": 0}) or {}

        tenant_id = f"tenant-{uuid.uuid4()}"
        company_id = f"company-{uuid.uuid4()}"
        owner_id = str(uuid.uuid4())
        tenant_code = await P._next_tenant_code(db)
        created = _now_iso()
        started_at = _normalize_iso(body.start_date) or created
        ends_at = _normalize_iso(body.ends_at)

        limits = {}
        if body.max_users is not None:
            limits["max_users"] = int(body.max_users)
        limits["storage_limit_gb"] = float(body.storage_limit_gb) if body.storage_limit_gb is not None else DEFAULT_STORAGE_LIMIT_GB

        tenant_doc = {
            "id": tenant_id,
            "tenant_code": tenant_code,
            "slug": slug,
            "name": body.company_name.strip(),
            "status": "pending_activation",
            "plan_id": plan.get("id"),
            "plan_code": (plan.get("code") if plan else (body.plan_code or None)),
            "logo": body.logo or None,
            "contact": {
                "pic_name": body.pic_name.strip(),
                "pic_position": (body.pic_position or "").strip() or None,
                "email": email,
                "whatsapp": body.whatsapp.strip(),
                "phone": (body.phone or "").strip() or None,
            },
            "address": (body.address or "").strip() or None,
            "subscription": {
                "status": "pending_activation",
                "started_at": started_at,
                "trial_ends_at": None,
                "ends_at": ends_at,
                "activated_at": None,
            },
            "limits": limits,
            "subscription_history": [],
            "suspend_history": [],
            "admin_notes": (body.notes or "").strip() or None,
            "foundation_version": 1,
            "isolation_ready": False,
            "created_by": user.get("id"),
            "created_at": created,
            "updated_at": created,
        }
        company_doc = {
            "id": company_id, "tenant_id": tenant_id, "name": body.company_name.strip(),
            "address": (body.address or "").strip() or None, "is_primary": True, "is_active": True,
            "created_at": created, "updated_at": created,
        }
        owner_doc = {
            "id": owner_id, "tenant_id": tenant_id, "company_id": company_id, "email": email,
            "password_hash": None, "name": body.pic_name.strip(), "role": "admin",
            "divisions": [], "warehouses": [], "permissions": list(getattr(server, "ROLE_DEFAULTS", {}).get("admin", [])),
            "scope": "global", "is_active": False, "status": "pending_activation",
            "token_version": 0, "signature_url": None, "email_verified": False,
            "created_at": created,
        }

        inserted = {"tenant": False, "company": False, "user": False, "settings": False}
        try:
            await db.tenants.insert_one(tenant_doc); inserted["tenant"] = True
            await db.companies.insert_one(company_doc); inserted["company"] = True
            await db.users.insert_one(owner_doc); inserted["user"] = True
            defaults = _tenant_defaults(tenant_id, body.company_name.strip(), body.address)
            if defaults:
                await db.settings.insert_many(defaults)
            inserted["settings"] = True
            activation = await _new_activation_token(db, tenant_id, owner_id, email)
            await P._platform_audit(server, user, "tenant.created", tenant_id, {
                "tenant_code": tenant_code, "workspace": slug, "company_name": body.company_name.strip(),
                "primary_email": email, "plan_code": tenant_doc.get("plan_code"),
                "max_users": limits.get("max_users"), "storage_limit_gb": limits.get("storage_limit_gb"),
            })
        except Exception:
            if inserted["settings"]:
                await db.settings.delete_many({"tenant_id": tenant_id})
            if inserted["user"]:
                await db.users.delete_many({"id": owner_id})
            if inserted["company"]:
                await db.companies.delete_many({"id": company_id})
            if inserted["tenant"]:
                await db.tenants.delete_many({"id": tenant_id})
            raise

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "tenant_code": tenant_code,
            "workspace": slug,
            "primary_email": email,
            "tenant_admin": {"name": body.pic_name.strip(), "email": email, "status": "pending_activation"},
            "activation_url": _activation_url(activation["token"]),
            "activation_expires_at": activation["expires_at"],
            "message": (f"Tenant {tenant_code} dibuat. Akun Tenant Admin pertama berstatus Pending Activation. "
                        f"Bagikan link aktivasi kepada {email}."),
        }

    # ---- EDIT PROFILE / EMAIL / LIMITS ----
    @app.patch("/api/platform/tenants/{tenant_id}/profile", tags=["platform"])
    async def update_tenant_profile(tenant_id: str, body: TenantProfilePatch, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

        contact = dict(tenant.get("contact") or {})
        update = {"updated_at": _now_iso()}
        audit_after = {}

        if body.company_name is not None:
            update["name"] = body.company_name.strip()
            audit_after["company_name"] = update["name"]
        if body.address is not None:
            update["address"] = body.address.strip() or None
        if body.logo is not None:
            update["logo"] = body.logo or None
        if body.pic_name is not None:
            contact["pic_name"] = body.pic_name.strip()
        if body.pic_position is not None:
            contact["pic_position"] = body.pic_position.strip() or None
        if body.whatsapp is not None:
            contact["whatsapp"] = body.whatsapp.strip()
        if body.phone is not None:
            contact["phone"] = body.phone.strip() or None

        # Primary email change: unique + sync to the primary admin user (keeps tenant code intact).
        if body.email is not None:
            new_email = str(body.email).strip().lower()
            if new_email != (contact.get("email") or "").lower():
                dup_user = await db.users.find_one({"email": new_email}, {"_id": 0, "id": 1, "tenant_id": 1})
                if dup_user and dup_user.get("tenant_id") != tenant_id:
                    raise HTTPException(status_code=409, detail="Email sudah digunakan user/tenant lain")
                dup_tenant = await db.tenants.find_one({"contact.email": new_email, "id": {"$ne": tenant_id}}, {"_id": 0, "id": 1})
                if dup_tenant:
                    raise HTTPException(status_code=409, detail="Email sudah digunakan tenant lain")
                old_email = contact.get("email")
                contact["email"] = new_email
                # Sync the tenant's primary admin (first created admin) email.
                primary_admin = await db.users.find_one(
                    {"tenant_id": tenant_id, "role": "admin"}, {"_id": 0}, sort=[("created_at", 1)]
                )
                if primary_admin and (primary_admin.get("email") or "").lower() == (old_email or "").lower():
                    await db.users.update_one({"id": primary_admin["id"]}, {"$set": {"email": new_email}})
                # Repoint any pending activation token to the new email.
                await db.tenant_activations.update_many(
                    {"tenant_id": tenant_id, "status": "pending"}, {"$set": {"email": new_email}}
                )
                audit_after["primary_email"] = {"from": old_email, "to": new_email}

        update["contact"] = contact

        if body.max_users is not None:
            update["limits.max_users"] = int(body.max_users)
            active = await _active_user_count(db, tenant_id)
            audit_after["max_users"] = int(body.max_users)
            audit_after["active_users"] = active
            if active > int(body.max_users):
                audit_after["over_limit_warning"] = True
        if body.storage_limit_gb is not None:
            update["limits.storage_limit_gb"] = float(body.storage_limit_gb)
            audit_after["storage_limit_gb"] = float(body.storage_limit_gb)
        if body.notes is not None:
            update["admin_notes"] = body.notes.strip() or None

        await db.tenants.update_one({"id": tenant_id}, {"$set": update})
        await P._platform_audit(server, user, "tenant.profile_updated", tenant_id, audit_after or {"updated": True})

        result = await _detail(tenant_id, user)
        if body.max_users is not None and result["user_usage"]["active"] > int(body.max_users):
            result["warning"] = (f"User aktif ({result['user_usage']['active']}) melebihi limit baru "
                                 f"({int(body.max_users)}). Penambahan user baru diblokir sampai di bawah limit.")
        return result

    # ---- SUSPEND ----
    @app.post("/api/platform/tenants/{tenant_id}/suspend", tags=["platform"])
    async def suspend_tenant(tenant_id: str, body: SuspendIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        if tenant.get("status") == "suspended":
            raise HTTPException(status_code=409, detail="Tenant sudah dalam status suspended")
        entry = {"action": "suspend", "reason": body.reason.strip(), "at": _now_iso(),
                 "by": user.get("email"), "prev_status": tenant.get("status")}
        await db.tenants.update_one({"id": tenant_id}, {
            "$set": {"status": "suspended", "subscription.status": "suspended", "updated_at": _now_iso()},
            "$push": {"suspend_history": entry},
        })
        await P._platform_audit(server, user, "tenant.suspended", tenant_id, {"reason": body.reason.strip()})
        return await _detail(tenant_id, user)

    # ---- REACTIVATE ----
    @app.post("/api/platform/tenants/{tenant_id}/reactivate", tags=["platform"])
    async def reactivate_tenant(tenant_id: str, body: ReactivateIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        if tenant.get("status") != "suspended":
            raise HTTPException(status_code=409, detail="Hanya tenant suspended yang dapat direaktivasi")
        sub = tenant.get("subscription") or {}
        end_dt = _as_dt(sub.get("ends_at"))
        new_sub_status = "active"
        if end_dt is not None and end_dt < _now():
            new_sub_status = "expired"
        entry = {"action": "reactivate", "reason": (body.reason or "").strip() or None, "at": _now_iso(),
                 "by": user.get("email")}
        await db.tenants.update_one({"id": tenant_id}, {
            "$set": {"status": "active", "subscription.status": new_sub_status, "updated_at": _now_iso()},
            "$push": {"suspend_history": entry},
        })
        await P._platform_audit(server, user, "tenant.reactivated", tenant_id,
                                {"reason": entry["reason"], "subscription_status": new_sub_status})
        return await _detail(tenant_id, user)

    # ---- RENEW ----
    @app.post("/api/platform/tenants/{tenant_id}/renew", tags=["platform"])
    async def renew_tenant(tenant_id: str, body: RenewIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

        sub = tenant.get("subscription") or {}
        limits = tenant.get("limits") or {}
        history = list(tenant.get("subscription_history") or [])
        # Snapshot the current period before overwriting.
        history.append({
            "period_no": len(history) + 1,
            "plan_id": tenant.get("plan_id"),
            "plan_code": tenant.get("plan_code"),
            "started_at": sub.get("started_at"),
            "ends_at": sub.get("ends_at"),
            "status": sub.get("status"),
            "max_users": limits.get("max_users"),
            "storage_limit_gb": limits.get("storage_limit_gb"),
            "archived_at": _now_iso(),
            "archived_by": user.get("email"),
        })

        new_start = _normalize_iso(body.start_date) or _now_iso()
        new_end = _normalize_iso(body.ends_at)
        if not new_end:
            raise HTTPException(status_code=400, detail="Tanggal akhir langganan wajib diisi")

        update = {
            "updated_at": _now_iso(),
            "subscription.status": "active",
            "subscription.started_at": new_start,
            "subscription.ends_at": new_end,
            "subscription.activated_at": sub.get("activated_at") or _now_iso(),
            "subscription_history": history,
        }
        # Reactivating status on renewal (unless tenant is suspended).
        if tenant.get("status") != "suspended":
            update["status"] = "active"
        if body.plan_code is not None:
            plan = await db.plans.find_one({"code": body.plan_code.strip().lower()}, {"_id": 0})
            update["plan_id"] = plan.get("id") if plan else None
            update["plan_code"] = (plan.get("code") if plan else body.plan_code)
        if body.max_users is not None:
            update["limits.max_users"] = int(body.max_users)
        if body.storage_limit_gb is not None:
            update["limits.storage_limit_gb"] = float(body.storage_limit_gb)
        if body.notes is not None:
            update["admin_notes"] = body.notes.strip() or None

        # Clear stale lifecycle reminder metadata for the new period.
        unset = {
            "subscription.grace_ends_at": "", "subscription.expired_at": "",
            "subscription.reminders_sent": "", "subscription.last_reminder_at": "",
            "subscription.last_reminder_type": "", "subscription.status_changed_at": "",
        }
        await db.tenants.update_one({"id": tenant_id}, {"$set": update, "$unset": unset})
        await P._platform_audit(server, user, "tenant.renewed", tenant_id, {
            "period_no": len(history) + 1, "started_at": new_start, "ends_at": new_end,
            "plan_code": update.get("plan_code", tenant.get("plan_code")),
            "max_users": update.get("limits.max_users", limits.get("max_users")),
            "storage_limit_gb": update.get("limits.storage_limit_gb", limits.get("storage_limit_gb")),
        })
        return await _detail(tenant_id, user)

    # ---- RESEND ACTIVATION ----
    @app.post("/api/platform/tenants/{tenant_id}/resend-activation", tags=["platform"])
    async def resend_activation(tenant_id: str, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        admin = await db.users.find_one(
            {"tenant_id": tenant_id, "role": "admin"}, {"_id": 0}, sort=[("created_at", 1)]
        )
        if not admin:
            raise HTTPException(status_code=404, detail="Akun Tenant Admin tidak ditemukan")
        if admin.get("is_active") and admin.get("status") != "pending_activation":
            raise HTTPException(status_code=409, detail="Tenant Admin sudah aktif; aktivasi tidak diperlukan")
        activation = await _new_activation_token(db, tenant_id, admin["id"], admin.get("email"))
        await P._platform_audit(server, user, "tenant.activation_resent", tenant_id, {"email": admin.get("email")})
        return {
            "ok": True,
            "activation_url": _activation_url(activation["token"]),
            "activation_expires_at": activation["expires_at"],
            "email": admin.get("email"),
            "message": f"Link aktivasi baru dibuat untuk {admin.get('email')}.",
        }

    # ---- PUBLIC: activation lookup ----
    @app.get("/api/platform/activation/{token}", tags=["platform"])
    async def activation_info(token: str):
        db = P._global_db(server)
        act = await db.tenant_activations.find_one({"token": token}, {"_id": 0})
        if not act:
            raise HTTPException(status_code=404, detail="Token aktivasi tidak ditemukan")
        if act.get("status") != "pending":
            raise HTTPException(status_code=410, detail="Token aktivasi sudah tidak berlaku")
        if _as_dt(act.get("expires_at")) and _as_dt(act.get("expires_at")) <= _now():
            raise HTTPException(status_code=410, detail="Token aktivasi sudah kedaluwarsa")
        tenant = await db.tenants.find_one({"id": act.get("tenant_id")}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        admin = await db.users.find_one({"id": act.get("user_id")}, {"_id": 0, "name": 1, "email": 1})
        return {
            "tenant_code": tenant.get("tenant_code"),
            "tenant_name": tenant.get("name"),
            "name": (admin or {}).get("name"),
            "email_hint": _mask_email(act.get("email")),
            "expires_at": act.get("expires_at"),
        }

    # ---- PUBLIC: activation accept (set password) ----
    @app.post("/api/platform/activation/{token}/accept", tags=["platform"])
    async def activation_accept(token: str, body: ActivateIn):
        db = P._global_db(server)
        # Atomic claim to prevent token reuse / race.
        claimed = await db.tenant_activations.find_one_and_update(
            {"token": token, "status": "pending", "expires_at": {"$gt": _now_iso()}},
            {"$set": {"status": "activating", "activation_started_at": _now_iso()}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            existing = await db.tenant_activations.find_one({"token": token}, {"_id": 0, "status": 1})
            if not existing:
                raise HTTPException(status_code=404, detail="Token aktivasi tidak ditemukan")
            raise HTTPException(status_code=410, detail="Token aktivasi sudah dipakai atau kedaluwarsa")

        tenant_id = claimed.get("tenant_id")
        user_id = claimed.get("user_id")
        try:
            admin = await db.users.find_one({"id": user_id, "tenant_id": tenant_id}, {"_id": 0})
            if not admin:
                raise HTTPException(status_code=404, detail="Akun Tenant Admin tidak ditemukan")
            await db.users.update_one({"id": user_id}, {"$set": {
                "password_hash": A.hash_password(body.password),
                "is_active": True,
                "status": "active",
                "email_verified": True,
                "activated_at": _now_iso(),
            }})
            # Activate tenant + subscription.
            tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
            sub = tenant.get("subscription") or {}
            end_dt = _as_dt(sub.get("ends_at"))
            sub_status = "active"
            if end_dt is not None and end_dt < _now():
                sub_status = "expired"
            await db.tenants.update_one({"id": tenant_id}, {"$set": {
                "status": "active" if tenant.get("status") == "pending_activation" else tenant.get("status"),
                "subscription.status": sub_status,
                "subscription.activated_at": _now_iso(),
                "updated_at": _now_iso(),
            }})
            await db.tenant_activations.update_one(
                {"token": token, "status": "activating"},
                {"$set": {"status": "used", "used_at": _now_iso()}, "$unset": {"activation_started_at": ""}},
            )
            await P._platform_audit(server, admin, "tenant.activated", tenant_id,
                                    {"email": admin.get("email"), "user_id": user_id})
            return {
                "ok": True,
                "message": "Akun Tenant Admin berhasil diaktifkan. Silakan masuk menggunakan email dan password baru.",
                "email": admin.get("email"),
                "tenant_code": tenant.get("tenant_code"),
            }
        except Exception:
            await db.tenant_activations.update_one(
                {"token": token, "status": "activating"},
                {"$set": {"status": "pending"}, "$unset": {"activation_started_at": ""}},
            )
            raise

    # ---- STORAGE USAGE ----
    @app.get("/api/platform/tenants/{tenant_id}/storage", tags=["platform"])
    async def tenant_storage(tenant_id: str, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        plan = await _plan_for(db, tenant)
        limit_gb = _effective_limit(tenant, plan, "storage_limit_gb")
        return await _storage_usage(db, tenant_id, limit_gb)

    # ---- CP0 DETAIL (enriched) ----
    @app.get("/api/platform/tenants/{tenant_id}/cp0", tags=["platform"])
    async def tenant_cp0_detail(tenant_id: str, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        return await _detail(tenant_id, user)

    # ---- DASHBOARD (KPIs + attention) ----
    @app.get("/api/platform/dashboard", tags=["platform"])
    async def platform_dashboard(user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenants = await db.tenants.find({}, {"_id": 0}).to_list(10000)
        plan_map = {p["id"]: p async for p in db.plans.find({}, {"_id": 0})}

        total = len(tenants)
        active = pending = suspended = expired = expiring = 0
        attention = []
        for t in tenants:
            tid = t["id"]
            status = str(t.get("status") or "").lower()
            view = _subscription_view(t)
            if status == "suspended":
                suspended += 1
                attention.append({"tenant_id": tid, "tenant_code": t.get("tenant_code"), "name": t.get("name"),
                                  "type": "suspended", "severity": "danger", "message": "Tenant ditangguhkan (suspended)."})
                continue
            if status == "pending_activation":
                pending += 1
                attention.append({"tenant_id": tid, "tenant_code": t.get("tenant_code"), "name": t.get("name"),
                                  "type": "pending_activation", "severity": "warning",
                                  "message": "Menunggu aktivasi Tenant Admin pertama."})
                continue
            if status == "active":
                active += 1
            dr = view.get("days_remaining")
            if view.get("display_status") == "expired" or (dr is not None and dr < 0):
                expired += 1
                attention.append({"tenant_id": tid, "tenant_code": t.get("tenant_code"), "name": t.get("name"),
                                  "type": "expired", "severity": "danger",
                                  "message": "Langganan sudah berakhir."})
            elif dr is not None and dr <= EXPIRING_SOON_DAYS:
                expiring += 1
                attention.append({"tenant_id": tid, "tenant_code": t.get("tenant_code"), "name": t.get("name"),
                                  "type": "expiring_soon", "severity": "warning",
                                  "message": f"Langganan berakhir dalam {dr} hari."})
            # user limit + storage attention
            plan = plan_map.get(t.get("plan_id")) or ({} if not t.get("plan_code") else {})
            max_users = _effective_limit(t, plan, "max_users")
            if max_users is not None:
                current = await _active_user_count(db, tid)
                if current >= int(max_users):
                    attention.append({"tenant_id": tid, "tenant_code": t.get("tenant_code"), "name": t.get("name"),
                                      "type": "user_limit_reached", "severity": "warning",
                                      "message": f"User limit tercapai ({current}/{max_users})."})
            limit_gb = _effective_limit(t, plan, "storage_limit_gb")
            if limit_gb:
                usage = await _storage_usage(db, tid, limit_gb)
                if usage.get("percent") is not None and usage["percent"] >= 80:
                    attention.append({"tenant_id": tid, "tenant_code": t.get("tenant_code"), "name": t.get("name"),
                                      "type": "storage_high", "severity": "warning",
                                      "message": f"Storage terpakai {usage['percent']}% ({usage['used_gb']}/{limit_gb} GB)."})

        active_users = await db.users.count_documents({"is_platform_admin": {"$ne": True}, "is_active": {"$ne": False}})
        severity_rank = {"danger": 0, "warning": 1, "normal": 2}
        attention.sort(key=lambda a: severity_rank.get(a.get("severity"), 3))
        return {
            "total_tenants": total,
            "active_tenants": active,
            "pending_activation": pending,
            "suspended": suspended,
            "expiring_30_days": expiring,
            "expired": expired,
            "active_users": active_users,
            "attention": attention,
            "attention_count": len(attention),
        }

    server.logger.info("CP0 Platform Admin completion layer installed")
