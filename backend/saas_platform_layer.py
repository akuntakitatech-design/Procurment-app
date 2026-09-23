"""SaaS registration and platform administration layer.

This layer is intentionally feature-flagged. Public tenant registration remains OFF by
default until explicitly enabled in staging/production environment configuration.
"""
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument

import auth as A
import tenant_foundation_layer as T
import tenant_isolation_layer as I


PLATFORM_TENANT_ID = "platform-root"
PLATFORM_COMPANY_ID = "platform-root"
TENANT_CODE_PREFIX = os.environ.get("TENANT_CODE_PREFIX", "PRC").strip().upper() or "PRC"
TENANT_CODE_COUNTER_ID = "tenant-code-counter"

# Platform audit is intentionally global and is never exposed through normal tenant routes.
T.GLOBAL_COLLECTIONS.add("platform_audit_logs")
I.GLOBAL_COLLECTIONS.add("platform_audit_logs")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _enabled(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _global_db(server):
    """Return the raw/global database behind the tenant proxy when isolation is active.

    During startup ``server.db`` is still the raw Motor database. After tenant isolation
    activates it becomes ``TenantDatabaseProxy``; its internal ``_raw`` handle is the
    deliberate escape hatch used only by platform-level SaaS operations that must span
    tenants (registration, plan catalog and Platform Super Admin).
    """
    db = server.db
    raw = getattr(db, "_raw", None)
    return raw if raw is not None else db


def _slugify(value: str) -> str:
    raw = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return slug[:60]


def _public_plan(plan: dict) -> dict:
    return {
        "code": plan.get("code"),
        "name": plan.get("name"),
        "limits": plan.get("limits") or {},
    }


def _require_platform_admin(user: dict):
    if not user or not user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Akses khusus Super Admin platform")


def _format_tenant_code(seq: int) -> str:
    return f"{TENANT_CODE_PREFIX}-{int(seq):06d}"


def _tenant_code_seq(code: str | None) -> int | None:
    match = re.fullmatch(rf"{re.escape(TENANT_CODE_PREFIX)}-(\d{{6,}})", str(code or "").strip().upper())
    return int(match.group(1)) if match else None


async def _next_tenant_code(db) -> str:
    counter = await db.tenant_migrations.find_one_and_update(
        {"id": TENANT_CODE_COUNTER_ID},
        {
            "$inc": {"seq": 1},
            "$set": {"type": "tenant-code-counter", "updated_at": now_iso()},
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return _format_tenant_code((counter or {}).get("seq", 1))


async def _ensure_tenant_codes(server):
    """Backfill permanent human-readable tenant codes without changing tenant UUIDs."""
    db = _global_db(server)
    tenants = await db.tenants.find({}, {"_id": 0}).to_list(100000)
    tenants.sort(key=lambda x: (0 if x.get("id") == T.DEFAULT_TENANT_ID else 1, x.get("created_at") or "", x.get("id") or ""))

    max_seq = 0
    seen_codes = set()
    missing = []
    for tenant in tenants:
        code = str(tenant.get("tenant_code") or "").strip().upper()
        seq = _tenant_code_seq(code)
        if code and code not in seen_codes:
            seen_codes.add(code)
            if seq is not None:
                max_seq = max(max_seq, seq)
            continue
        if code:
            # Duplicate code must not survive a unique index; preserve the first record.
            await db.tenants.update_one({"id": tenant["id"]}, {"$unset": {"tenant_code": ""}})
        missing.append(tenant)

    await db.tenant_migrations.update_one(
        {"id": TENANT_CODE_COUNTER_ID},
        {
            "$max": {"seq": max_seq},
            "$set": {"type": "tenant-code-counter", "updated_at": now_iso()},
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )

    for tenant in missing:
        code = await _next_tenant_code(db)
        await db.tenants.update_one(
            {"id": tenant["id"], "tenant_code": {"$exists": False}},
            {"$set": {"tenant_code": code, "updated_at": now_iso()}},
        )

    await db.tenants.create_index("tenant_code", unique=True, sparse=True)
    await db.platform_audit_logs.create_index([("tenant_id", 1), ("at", -1)])


async def _platform_audit(server, user: dict, action: str, tenant_id: str | None = None, after=None):
    db = _global_db(server)
    await db.platform_audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "action": action,
        "tenant_id": tenant_id,
        "user_id": (user or {}).get("id"),
        "user_email": (user or {}).get("email"),
        "after": after,
        "at": now_iso(),
    })


async def _seed_platform_admin(server):
    email = os.environ.get("PLATFORM_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("PLATFORM_ADMIN_PASSWORD", "")
    if not email or not password:
        server.logger.info("Platform Super Admin bootstrap skipped; env credentials not configured")
        return

    db = _global_db(server)
    existing = await db.users.find_one({"email": email})
    if existing:
        if existing.get("is_platform_admin"):
            server.logger.info("Platform Super Admin already exists; preserving current password")
        else:
            server.logger.warning(
                "PLATFORM_ADMIN_EMAIL already belongs to a tenant user; refusing automatic promotion: %s",
                email,
            )
        return

    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": PLATFORM_TENANT_ID,
        "company_id": PLATFORM_COMPANY_ID,
        "email": email,
        "password_hash": A.hash_password(password),
        "name": os.environ.get("PLATFORM_ADMIN_NAME", "Akuntakita Super Admin").strip() or "Akuntakita Super Admin",
        "role": "platform_super_admin",
        "is_platform_admin": True,
        "permissions": [],
        "divisions": [],
        "warehouses": [],
        "scope": "platform",
        "is_active": True,
        "token_version": 0,
        "signature_url": None,
        "created_at": now_iso(),
    })
    server.logger.info("Seeded Platform Super Admin")


class TenantRegistrationIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    pic_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    whatsapp: str = Field(min_length=7, max_length=40)
    workspace_slug: str | None = Field(default=None, max_length=60)
    plan_code: str = "starter"
    password: str = Field(min_length=8, max_length=128)
    address: str | None = Field(default=None, max_length=500)
    terms_accepted: bool = False


class TenantAdminPatch(BaseModel):
    status: str | None = None
    plan_code: str | None = None
    subscription_status: str | None = None
    subscription_ends_at: str | None = None
    max_users: int | None = Field(default=None, ge=1, le=100000)
    max_companies: int | None = Field(default=None, ge=1, le=100000)
    max_warehouses: int | None = Field(default=None, ge=1, le=100000)
    max_divisions: int | None = Field(default=None, ge=1, le=100000)
    notes: str | None = Field(default=None, max_length=1000)


def _tenant_defaults(tenant_id: str, company_name: str, address: str | None):
    return [
        {
            "id": "numbering",
            "tenant_id": tenant_id,
            "formats": {
                "MRO": "MRO/{year}/{month}/{seq}",
                "RO": "RO/{year}/{month}/{seq}",
                "PO": "PO/{year}/{month}/{seq}",
                "DO": "DO/{year}/{month}/{seq}",
                "MI": "MI/{year}/{month}/{seq}",
                "TRF": "TRF/{year}/{month}/{seq}",
                "LOAN": "LOAN/{year}/{month}/{seq}",
                "RET": "RET/{year}/{month}/{seq}",
                "ADJ": "ADJ/{year}/{month}/{seq}",
                "OPN": "OPN/{year}/{month}/{seq}",
            },
        },
        {"id": "approval_rules", "tenant_id": tenant_id, "rules": []},
        {"id": "approval_levels", "tenant_id": tenant_id, "levels": []},
        {
            "id": "approval_modules",
            "tenant_id": tenant_id,
            "modules": {
                "mro": {"enabled": False, "levels": []},
                "ro": {"enabled": False, "levels": []},
                "po": {"enabled": False, "levels": []},
            },
        },
        {
            "id": "company",
            "tenant_id": tenant_id,
            "name": company_name,
            "address": address,
            "app_subtitle": "Procurement & Inventory",
            "damaged_method": "method1",
        },
    ]


async def _usage(db, tenant_id: str) -> dict:
    return {
        "users": await db.users.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
        "companies": await db.companies.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
        "warehouses": await db.warehouses.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
        "divisions": await db.divisions.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
    }


def install(server):
    app = server.app

    @app.on_event("startup")
    async def platform_admin_startup():
        await _ensure_tenant_codes(server)
        await _seed_platform_admin(server)

    @app.middleware("http")
    async def block_legacy_self_registration(request, call_next):
        if (
            request.method.upper() == "POST"
            and request.url.path == "/api/auth/register"
            and _enabled("DISABLE_LEGACY_USER_SELF_REGISTER", "true")
        ):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=410,
                content={"detail": "Registrasi user lama dinonaktifkan. Gunakan registrasi workspace/perusahaan."},
            )
        return await call_next(request)

    @app.get("/api/saas/public-config", tags=["saas"])
    async def public_saas_config():
        db = _global_db(server)
        plans = await db.plans.find({"is_public": True, "is_active": True}, {"_id": 0}).sort("limits.max_users", 1).to_list(100)
        return {
            "registration_enabled": _enabled("ENABLE_PUBLIC_TENANT_REGISTRATION", "false"),
            "trial_days": int(os.environ.get("TENANT_TRIAL_DAYS", "14") or 14),
            "plans": [_public_plan(p) for p in plans],
        }

    @app.post("/api/saas/register", tags=["saas"])
    async def register_tenant(body: TenantRegistrationIn):
        if not _enabled("ENABLE_PUBLIC_TENANT_REGISTRATION", "false"):
            raise HTTPException(status_code=403, detail="Registrasi tenant belum dibuka")
        if not body.terms_accepted:
            raise HTTPException(status_code=400, detail="Persetujuan syarat penggunaan wajib dicentang")

        db = _global_db(server)
        email = str(body.email).strip().lower()
        if await db.users.find_one({"email": email}):
            raise HTTPException(status_code=409, detail="Email sudah terdaftar")

        plan = await db.plans.find_one({
            "code": body.plan_code.strip().lower(),
            "is_public": True,
            "is_active": True,
        }, {"_id": 0})
        if not plan:
            raise HTTPException(status_code=400, detail="Paket tidak tersedia")

        slug = _slugify(body.workspace_slug or body.company_name)
        if len(slug) < 3:
            raise HTTPException(status_code=400, detail="Nama workspace terlalu pendek")
        if await db.tenants.find_one({"slug": slug}):
            raise HTTPException(status_code=409, detail="Nama workspace sudah digunakan")

        tenant_id = f"tenant-{uuid.uuid4()}"
        company_id = f"company-{uuid.uuid4()}"
        owner_id = str(uuid.uuid4())
        tenant_code = await _next_tenant_code(db)
        trial_days = max(0, int(os.environ.get("TENANT_TRIAL_DAYS", "14") or 14))
        started = datetime.now(timezone.utc)
        trial_end = started + timedelta(days=trial_days)
        created = now_iso()

        tenant_doc = {
            "id": tenant_id,
            "tenant_code": tenant_code,
            "slug": slug,
            "name": body.company_name.strip(),
            "status": "active",
            "plan_id": plan["id"],
            "contact": {
                "pic_name": body.pic_name.strip(),
                "email": email,
                "whatsapp": body.whatsapp.strip(),
            },
            "subscription": {
                "status": "trial" if trial_days else "active",
                "started_at": started.isoformat(),
                "trial_ends_at": trial_end.isoformat() if trial_days else None,
                "ends_at": None,
            },
            "limits": {},
            "foundation_version": 1,
            "isolation_ready": False,
            "isolation_pending_reason": "staging-validation-required",
            "created_at": created,
            "updated_at": created,
        }
        company_doc = {
            "id": company_id,
            "tenant_id": tenant_id,
            "name": body.company_name.strip(),
            "address": body.address,
            "is_primary": True,
            "is_active": True,
            "created_at": created,
            "updated_at": created,
        }
        owner_doc = {
            "id": owner_id,
            "tenant_id": tenant_id,
            "company_id": company_id,
            "email": email,
            "password_hash": A.hash_password(body.password),
            "name": body.pic_name.strip(),
            "role": "admin",
            "divisions": [],
            "warehouses": [],
            "permissions": [],
            "scope": "global",
            "is_active": True,
            "token_version": 0,
            "signature_url": None,
            "email_verified": False,
            "created_at": created,
        }

        inserted = {"tenant": False, "company": False, "user": False, "settings": False}
        try:
            await db.tenants.insert_one(tenant_doc)
            inserted["tenant"] = True
            await db.companies.insert_one(company_doc)
            inserted["company"] = True
            await db.users.insert_one(owner_doc)
            inserted["user"] = True
            await db.settings.insert_many(_tenant_defaults(tenant_id, body.company_name.strip(), body.address))
            inserted["settings"] = True
            await db.tenant_migrations.insert_one({
                "id": f"registration-{tenant_id}",
                "tenant_id": tenant_id,
                "type": "saas-registration",
                "completed_at": created,
            })
            await _platform_audit(
                server,
                owner_doc,
                "tenant.registered",
                tenant_id,
                {"tenant_code": tenant_code, "workspace": slug, "plan_code": plan.get("code")},
            )
        except Exception:
            if inserted["settings"]:
                await db.settings.delete_many({"tenant_id": tenant_id})
            if inserted["user"]:
                await db.users.delete_many({"id": owner_id, "tenant_id": tenant_id})
            if inserted["company"]:
                await db.companies.delete_many({"id": company_id, "tenant_id": tenant_id})
            if inserted["tenant"]:
                await db.tenants.delete_many({"id": tenant_id})
            raise

        return {
            "ok": True,
            "tenant_id": tenant_id,
            "tenant_code": tenant_code,
            "company_id": company_id,
            "workspace": slug,
            "company_name": body.company_name.strip(),
            "owner_email": email,
            "plan": _public_plan(plan),
            "subscription": tenant_doc["subscription"],
            "message": f"Workspace berhasil dibuat. Kode tenant: {tenant_code}. Silakan masuk menggunakan akun Owner.",
        }

    @app.get("/api/platform/summary", tags=["platform"])
    async def platform_summary(user=Depends(server.current_user)):
        _require_platform_admin(user)
        db = _global_db(server)
        return {
            "tenants": await db.tenants.count_documents({}),
            "active_tenants": await db.tenants.count_documents({"status": "active"}),
            "trial_tenants": await db.tenants.count_documents({"subscription.status": "trial"}),
            "active_users": await db.users.count_documents({"is_platform_admin": {"$ne": True}, "is_active": {"$ne": False}}),
        }

    @app.get("/api/platform/tenants", tags=["platform"])
    async def platform_tenants(user=Depends(server.current_user)):
        _require_platform_admin(user)
        db = _global_db(server)
        tenants = await db.tenants.find({}, {"_id": 0}).sort("created_at", -1).to_list(5000)
        plan_map = {p["id"]: p async for p in db.plans.find({}, {"_id": 0})}
        out = []
        for tenant in tenants:
            usage = await _usage(db, tenant["id"])
            plan = plan_map.get(tenant.get("plan_id")) or {}
            out.append({**tenant, "plan": _public_plan(plan), "usage": usage})
        return out

    @app.get("/api/platform/tenants/{tenant_id}", tags=["platform"])
    async def platform_tenant_detail(tenant_id: str, user=Depends(server.current_user)):
        _require_platform_admin(user)
        db = _global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        plan = await db.plans.find_one({"id": tenant.get("plan_id")}, {"_id": 0}) or {}
        companies = await db.companies.find({"tenant_id": tenant_id}, {"_id": 0}).to_list(1000)
        users = await db.users.find(
            {"tenant_id": tenant_id},
            {"_id": 0, "password_hash": 0},
        ).sort("created_at", 1).to_list(5000)
        audit_logs = await db.platform_audit_logs.find(
            {"tenant_id": tenant_id}, {"_id": 0}
        ).sort("at", -1).to_list(100)
        return {
            **tenant,
            "plan": _public_plan(plan),
            "usage": await _usage(db, tenant_id),
            "companies": companies,
            "users": users,
            "audit_logs": audit_logs,
        }

    @app.patch("/api/platform/tenants/{tenant_id}", tags=["platform"])
    async def platform_update_tenant(tenant_id: str, body: TenantAdminPatch, user=Depends(server.current_user)):
        _require_platform_admin(user)
        db = _global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

        update = {"updated_at": now_iso()}
        if body.status is not None:
            if body.status not in {"active", "suspended"}:
                raise HTTPException(status_code=400, detail="Status tenant tidak valid")
            update["status"] = body.status
        if body.plan_code is not None:
            plan = await db.plans.find_one({"code": body.plan_code, "is_active": True}, {"_id": 0})
            if not plan:
                raise HTTPException(status_code=400, detail="Paket tidak ditemukan")
            update["plan_id"] = plan["id"]
        if body.subscription_status is not None:
            if body.subscription_status not in {"trial", "active", "grace", "expired", "suspended"}:
                raise HTTPException(status_code=400, detail="Status subscription tidak valid")
            update["subscription.status"] = body.subscription_status
        if body.subscription_ends_at is not None:
            update["subscription.ends_at"] = body.subscription_ends_at or None
        if body.notes is not None:
            update["admin_notes"] = body.notes
        for field in ("max_users", "max_companies", "max_warehouses", "max_divisions"):
            value = getattr(body, field)
            if value is not None:
                update[f"limits.{field}"] = value

        await db.tenants.update_one({"id": tenant_id}, {"$set": update})
        await _platform_audit(server, user, "tenant.update", tenant_id, update)
        return await platform_tenant_detail(tenant_id, user)
