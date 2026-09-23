"""Foundational multi-tenant layer for SaaS migration.

Phase 1 goals:
- create global plans and a default tenant/company for the existing installation
- backfill tenant_id on existing application data without deleting or rewriting business data
- attach tenant_id/company_id to existing and newly-created users
- enforce max active-user quota for the current tenant
- expose tenant/plan usage endpoints for future Super Admin / registration UI

Important: this layer lays the foundation only. Full query isolation for every transaction
collection is implemented incrementally in the next phase before additional tenants are enabled.
"""
import json
import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response


DEFAULT_TENANT_ID = os.environ.get("DEFAULT_TENANT_ID", "tenant-pt-real")
DEFAULT_COMPANY_ID = os.environ.get("DEFAULT_COMPANY_ID", "company-pt-real")
DEFAULT_TENANT_SLUG = os.environ.get("DEFAULT_TENANT_SLUG", "pt-real")

GLOBAL_COLLECTIONS = {
    "tenants",
    "plans",
    "tenant_migrations",
    "login_attempts",
}

PLAN_SEEDS = [
    {
        "id": "plan-starter",
        "code": "starter",
        "name": "Starter",
        "is_public": True,
        "is_active": True,
        "limits": {"max_users": 5, "max_companies": 1, "max_warehouses": 2, "max_divisions": 5},
    },
    {
        "id": "plan-business",
        "code": "business",
        "name": "Business",
        "is_public": True,
        "is_active": True,
        "limits": {"max_users": 15, "max_companies": 1, "max_warehouses": 10, "max_divisions": 20},
    },
    {
        "id": "plan-professional",
        "code": "professional",
        "name": "Professional",
        "is_public": True,
        "is_active": True,
        "limits": {"max_users": 30, "max_companies": 3, "max_warehouses": 30, "max_divisions": 50},
    },
    {
        "id": "plan-enterprise",
        "code": "enterprise",
        "name": "Enterprise",
        "is_public": True,
        "is_active": True,
        "limits": {"max_users": None, "max_companies": None, "max_warehouses": None, "max_divisions": None},
    },
    {
        "id": "plan-legacy",
        "code": "legacy",
        "name": "Legacy Existing Tenant",
        "is_public": False,
        "is_active": True,
        "limits": {"max_users": 100, "max_companies": 5, "max_warehouses": 100, "max_divisions": 100},
    },
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def tenant_id_of(user: dict | None) -> str:
    return (user or {}).get("tenant_id") or DEFAULT_TENANT_ID


def company_id_of(user: dict | None) -> str:
    return (user or {}).get("company_id") or DEFAULT_COMPANY_ID


def tenant_filter(user: dict | None, extra: dict | None = None) -> dict:
    query = {"tenant_id": tenant_id_of(user)}
    if extra:
        query.update(extra)
    return query


async def _seed_plans(server):
    for plan in PLAN_SEEDS:
        await server.db.plans.update_one(
            {"id": plan["id"]},
            {"$setOnInsert": {**plan, "created_at": now_iso()}, "$set": {"updated_at": now_iso()}},
            upsert=True,
        )


async def _ensure_default_tenant(server):
    company_setting = await server.db.settings.find_one({"id": "company"}, {"_id": 0}) or {}
    company_name = (
        os.environ.get("DEFAULT_TENANT_NAME", "").strip()
        or str(company_setting.get("name") or "PT REAL").strip()
    )
    active_existing = await server.db.users.count_documents({"is_active": {"$ne": False}})
    configured_max = int(os.environ.get("DEFAULT_TENANT_MAX_USERS", "25") or 25)
    safe_max_users = max(configured_max, active_existing)

    await server.db.tenants.update_one(
        {"id": DEFAULT_TENANT_ID},
        {
            "$setOnInsert": {
                "id": DEFAULT_TENANT_ID,
                "slug": DEFAULT_TENANT_SLUG,
                "name": company_name,
                "status": "active",
                "plan_id": "plan-legacy",
                "created_at": now_iso(),
                "subscription": {
                    "status": "active",
                    "started_at": now_iso(),
                    "ends_at": None,
                },
            },
            "$set": {
                "updated_at": now_iso(),
                "limits.max_users": safe_max_users,
                "foundation_version": 1,
                "isolation_ready": False,
            },
        },
        upsert=True,
    )

    await server.db.companies.update_one(
        {"id": DEFAULT_COMPANY_ID},
        {
            "$setOnInsert": {
                "id": DEFAULT_COMPANY_ID,
                "tenant_id": DEFAULT_TENANT_ID,
                "name": company_name,
                "is_primary": True,
                "is_active": True,
                "created_at": now_iso(),
            },
            "$set": {
                "updated_at": now_iso(),
                "address": company_setting.get("address"),
            },
        },
        upsert=True,
    )


async def _backfill_existing_data(server):
    """Tag all existing application collections as the original PT REAL tenant.

    This is intentionally additive only: records are not deleted, renamed, or moved.
    """
    names = await server.db.list_collection_names()
    touched = []
    for name in names:
        if name in GLOBAL_COLLECTIONS or name.startswith("system."):
            continue
        col = server.db[name]
        result = await col.update_many(
            {"tenant_id": {"$exists": False}},
            {"$set": {"tenant_id": DEFAULT_TENANT_ID}},
        )
        if result.modified_count:
            touched.append({"collection": name, "records": result.modified_count})
        try:
            await col.create_index("tenant_id")
        except Exception:
            pass

    await server.db.users.update_many(
        {"company_id": {"$exists": False}},
        {"$set": {"company_id": DEFAULT_COMPANY_ID}},
    )

    await server.db.tenant_migrations.update_one(
        {"id": "foundation-v1"},
        {
            "$set": {
                "id": "foundation-v1",
                "tenant_id": DEFAULT_TENANT_ID,
                "completed_at": now_iso(),
                "collections_touched": touched,
            }
        },
        upsert=True,
    )


async def _create_indexes(server):
    await server.db.tenants.create_index("slug", unique=True)
    await server.db.plans.create_index("code", unique=True)
    await server.db.companies.create_index([("tenant_id", 1), ("is_active", 1)])
    await server.db.users.create_index([("tenant_id", 1), ("is_active", 1)])


async def bootstrap(server):
    await _seed_plans(server)
    await _ensure_default_tenant(server)
    await _backfill_existing_data(server)
    await _create_indexes(server)


async def get_tenant(server, tenant_id: str):
    return await server.db.tenants.find_one({"id": tenant_id}, {"_id": 0})


async def get_plan(server, tenant: dict):
    if not tenant:
        return None
    return await server.db.plans.find_one({"id": tenant.get("plan_id")}, {"_id": 0})


def _effective_limit(tenant: dict, plan: dict | None, key: str):
    tenant_limits = (tenant or {}).get("limits") or {}
    if key in tenant_limits:
        return tenant_limits.get(key)
    return ((plan or {}).get("limits") or {}).get(key)


async def active_user_count(server, tenant_id: str):
    return await server.db.users.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}})


async def ensure_user_capacity(server, tenant_id: str):
    tenant = await get_tenant(server, tenant_id)
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant tidak ditemukan")
    if tenant.get("status") != "active":
        raise HTTPException(status_code=403, detail="Tenant sedang tidak aktif")
    plan = await get_plan(server, tenant)
    maximum = _effective_limit(tenant, plan, "max_users")
    current = await active_user_count(server, tenant_id)
    if maximum is not None and current >= int(maximum):
        raise HTTPException(
            status_code=409,
            detail=f"Batas pengguna tenant sudah tercapai ({current}/{maximum}). Nonaktifkan user atau upgrade paket.",
        )
    return {"current": current, "maximum": maximum}


async def _consume_response(response):
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    headers = dict(response.headers)
    headers.pop("content-length", None)
    rebuilt = Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=None,
        background=response.background,
    )
    return body, rebuilt


def install(server):
    app = server.app

    @app.on_event("startup")
    async def tenant_foundation_startup():
        await bootstrap(server)
        server.logger.info("Multi-tenant foundation v1 ready for default tenant %s", DEFAULT_TENANT_ID)

    @app.middleware("http")
    async def tenant_user_limit_guard(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        guarded_create = method == "POST" and path in {"/api/users", "/api/auth/register"}
        tenant_id = None
        company_id = None

        if guarded_create:
            if path == "/api/users":
                try:
                    user = await server.current_user(request)
                    tenant_id = tenant_id_of(user)
                    company_id = company_id_of(user)
                except HTTPException as exc:
                    return Response(
                        content=json.dumps({"detail": exc.detail}),
                        status_code=exc.status_code,
                        media_type="application/json",
                    )
            else:
                tenant_id = DEFAULT_TENANT_ID
                company_id = DEFAULT_COMPANY_ID
            try:
                await ensure_user_capacity(server, tenant_id)
            except HTTPException as exc:
                return Response(
                    content=json.dumps({"detail": exc.detail}),
                    status_code=exc.status_code,
                    media_type="application/json",
                )

        response = await call_next(request)

        # Existing user-create endpoints were built before tenant support. The tenant-aware
        # DB proxy already tags normal runtime inserts. This fallback fills only missing
        # ownership fields so it never overwrites the caller's company with PT REAL defaults.
        if guarded_create and 200 <= response.status_code < 300 and tenant_id:
            body, rebuilt = await _consume_response(response)
            try:
                payload = json.loads(body.decode("utf-8"))
                uid = payload.get("id") if isinstance(payload, dict) else None
                if uid:
                    created = await server.db.users.find_one({"id": uid}, {"_id": 0}) or {}
                    updates = {}
                    if not created.get("tenant_id"):
                        updates["tenant_id"] = tenant_id
                    if not created.get("company_id"):
                        updates["company_id"] = company_id or DEFAULT_COMPANY_ID
                    if updates:
                        await server.db.users.update_one({"id": uid}, {"$set": updates})
            except Exception as exc:
                server.logger.warning("tenant user tagging failed: %s", exc)
            return rebuilt

        return response

    @app.get("/api/tenant/current", tags=["tenant"])
    async def current_tenant(user=Depends(server.current_user)):
        tenant_id = tenant_id_of(user)
        tenant = await get_tenant(server, tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant tidak ditemukan")
        plan = await get_plan(server, tenant)
        current_users = await active_user_count(server, tenant_id)
        max_users = _effective_limit(tenant, plan, "max_users")
        company = await server.db.companies.find_one(
            {"id": company_id_of(user), "tenant_id": tenant_id}, {"_id": 0}
        )
        return {
            **tenant,
            "plan": plan,
            "company": company,
            "usage": {
                "active_users": current_users,
                "max_users": max_users,
                "remaining_users": None if max_users is None else max(0, int(max_users) - current_users),
            },
        }

    @app.get("/api/tenant/usage", tags=["tenant"])
    async def tenant_usage(user=Depends(server.current_user)):
        tenant_id = tenant_id_of(user)
        tenant = await get_tenant(server, tenant_id)
        if not tenant:
            raise HTTPException(404, "Tenant tidak ditemukan")
        plan = await get_plan(server, tenant)
        active_users = await active_user_count(server, tenant_id)
        return {
            "tenant_id": tenant_id,
            "users": {"active": active_users, "limit": _effective_limit(tenant, plan, "max_users")},
            "companies": {
                "active": await server.db.companies.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
                "limit": _effective_limit(tenant, plan, "max_companies"),
            },
            "warehouses": {
                "active": await server.db.warehouses.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
                "limit": _effective_limit(tenant, plan, "max_warehouses"),
            },
            "divisions": {
                "active": await server.db.divisions.count_documents({"tenant_id": tenant_id, "is_active": {"$ne": False}}),
                "limit": _effective_limit(tenant, plan, "max_divisions"),
            },
        }

    @app.get("/api/plans", tags=["tenant"])
    async def list_plans(user=Depends(server.current_user)):
        server.require(user, "view")
        return await server.db.plans.find(
            {"is_public": True, "is_active": True}, {"_id": 0}
        ).sort("limits.max_users", 1).to_list(100)
