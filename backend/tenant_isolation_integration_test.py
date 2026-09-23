"""Integration test for the multi-tenant database isolation layer.

This script is intentionally designed to run only against a disposable test database.
It creates two synthetic tenants, writes overlapping business/settings/user data through
TenantDatabaseProxy, and proves that Tenant A cannot read/update/delete Tenant B data
(and vice versa). It also verifies user quota enforcement.
"""
import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import HTTPException

import tenant_foundation_layer as T
import tenant_isolation_layer as I


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "procurement_tenant_test")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


class Scope:
    def __init__(self, tenant_id, company_id):
        self.tenant_id = tenant_id
        self.company_id = company_id
        self._tt = None
        self._ct = None

    def __enter__(self):
        self._tt = I._current_tenant.set(self.tenant_id)
        self._ct = I._current_company.set(self.company_id)
        return self

    def __exit__(self, exc_type, exc, tb):
        I._current_company.reset(self._ct)
        I._current_tenant.reset(self._tt)


async def main():
    run_id = uuid.uuid4().hex[:10]
    tenant_a = f"test-tenant-a-{run_id}"
    tenant_b = f"test-tenant-b-{run_id}"
    company_a = f"test-company-a-{run_id}"
    company_b = f"test-company-b-{run_id}"
    plan_id = f"test-plan-{run_id}"
    marker = f"tenant-isolation-test-{run_id}"

    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    raw_db = client[DB_NAME]
    await client.admin.command("ping")
    print(f"Connected to disposable MongoDB database: {DB_NAME}")

    proxy = I.TenantDatabaseProxy(raw_db)
    raw_server = SimpleNamespace(db=raw_db)

    try:
        await raw_db.plans.insert_one({
            "id": plan_id,
            "code": f"test-{run_id}",
            "name": "Tenant Isolation Test",
            "is_active": True,
            "limits": {"max_users": 2, "max_companies": 1, "max_warehouses": 2, "max_divisions": 2},
            "test_marker": marker,
        })
        for tenant_id, slug in ((tenant_a, f"a-{run_id}"), (tenant_b, f"b-{run_id}")):
            await raw_db.tenants.insert_one({
                "id": tenant_id,
                "slug": slug,
                "name": tenant_id,
                "status": "active",
                "plan_id": plan_id,
                "test_marker": marker,
            })

        # 1) Insert identical business identifiers in different tenant scopes.
        with Scope(tenant_a, company_a):
            await proxy.tenant_probe.insert_one({"id": "shared-doc", "value": "A", "test_marker": marker})
            await proxy.settings.insert_one({"id": "shared-setting", "value": "A", "test_marker": marker})
            await proxy.users.insert_one({
                "id": f"a-user-1-{run_id}", "email": f"a1-{run_id}@example.test",
                "is_active": True, "test_marker": marker,
            })

        with Scope(tenant_b, company_b):
            await proxy.tenant_probe.insert_one({"id": "shared-doc", "value": "B", "test_marker": marker})
            await proxy.settings.insert_one({"id": "shared-setting", "value": "B", "test_marker": marker})
            await proxy.users.insert_one({
                "id": f"b-user-1-{run_id}", "email": f"b1-{run_id}@example.test",
                "is_active": True, "test_marker": marker,
            })

        raw_probe = await raw_db.tenant_probe.find({"test_marker": marker}, {"_id": 0}).to_list(20)
        check(len(raw_probe) == 2, "Raw test database contains both tenant records")
        check({d.get("tenant_id") for d in raw_probe} == {tenant_a, tenant_b}, "Inserted records are automatically tagged with tenant_id")

        # 2) Read isolation and same-id coexistence.
        with Scope(tenant_a, company_a):
            rows = await proxy.tenant_probe.find({"id": "shared-doc"}, {"_id": 0}).to_list(20)
            check(len(rows) == 1 and rows[0]["value"] == "A", "Tenant A reads only Tenant A business data")
            setting = await proxy.settings.find_one({"id": "shared-setting"}, {"_id": 0})
            check(setting and setting["value"] == "A", "Tenant A reads only Tenant A settings")
            users = await proxy.users.find({"test_marker": marker}, {"_id": 0}).to_list(20)
            check(len(users) == 1 and users[0]["tenant_id"] == tenant_a, "Tenant A reads only Tenant A users")

        with Scope(tenant_b, company_b):
            rows = await proxy.tenant_probe.find({"id": "shared-doc"}, {"_id": 0}).to_list(20)
            check(len(rows) == 1 and rows[0]["value"] == "B", "Tenant B reads only Tenant B business data")
            setting = await proxy.settings.find_one({"id": "shared-setting"}, {"_id": 0})
            check(setting and setting["value"] == "B", "Tenant B reads only Tenant B settings")
            users = await proxy.users.find({"test_marker": marker}, {"_id": 0}).to_list(20)
            check(len(users) == 1 and users[0]["tenant_id"] == tenant_b, "Tenant B reads only Tenant B users")

        # 3) Cross-tenant update/delete attempts must be harmless.
        tenant_b_raw = await raw_db.tenant_probe.find_one({"tenant_id": tenant_b, "test_marker": marker})
        tenant_b_mongo_id = tenant_b_raw["_id"]
        with Scope(tenant_a, company_a):
            update = await proxy.tenant_probe.update_one({"_id": tenant_b_mongo_id}, {"$set": {"value": "HACKED"}})
            check(update.modified_count == 0, "Tenant A cannot update Tenant B record even using Mongo _id")
            deleted = await proxy.tenant_probe.delete_one({"_id": tenant_b_mongo_id})
            check(deleted.deleted_count == 0, "Tenant A cannot delete Tenant B record even using Mongo _id")

        tenant_b_after = await raw_db.tenant_probe.find_one({"_id": tenant_b_mongo_id})
        check(tenant_b_after and tenant_b_after["value"] == "B", "Tenant B record remains unchanged after cross-tenant attack")

        # 4) Aggregate, count, distinct and upsert are scoped.
        with Scope(tenant_a, company_a):
            count = await proxy.tenant_probe.count_documents({"test_marker": marker})
            check(count == 1, "Tenant-aware count_documents returns only Tenant A")
            agg = await proxy.tenant_probe.aggregate([
                {"$match": {"test_marker": marker}},
                {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}}},
            ]).to_list(20)
            check(len(agg) == 1 and agg[0]["_id"] == tenant_a and agg[0]["n"] == 1, "Aggregation is automatically tenant-scoped")
            values = await proxy.tenant_probe.distinct("value", {"test_marker": marker})
            check(values == ["A"], "Distinct is automatically tenant-scoped")
            await proxy.tenant_probe.update_one(
                {"id": "upsert-a", "test_marker": marker},
                {"$set": {"value": "A-UP"}},
                upsert=True,
            )

        upserted = await raw_db.tenant_probe.find_one({"id": "upsert-a", "test_marker": marker})
        check(upserted and upserted.get("tenant_id") == tenant_a, "Upsert automatically receives Tenant A tenant_id")

        # 5) User quota enforcement is isolated per tenant.
        with Scope(tenant_a, company_a):
            await proxy.users.insert_one({
                "id": f"a-user-2-{run_id}", "email": f"a2-{run_id}@example.test",
                "is_active": True, "test_marker": marker,
            })

        try:
            await T.ensure_user_capacity(raw_server, tenant_a)
            raise AssertionError("Tenant A quota should have been full")
        except HTTPException as exc:
            check(exc.status_code == 409, "Tenant A is blocked when active-user quota is full")

        capacity_b = await T.ensure_user_capacity(raw_server, tenant_b)
        check(capacity_b["current"] == 1 and capacity_b["maximum"] == 2, "Tenant B retains its own independent user quota")

        # 6) Global SaaS collections stay global by design.
        with Scope(tenant_a, company_a):
            plan_a = await proxy.plans.find_one({"id": plan_id}, {"_id": 0})
        with Scope(tenant_b, company_b):
            plan_b = await proxy.plans.find_one({"id": plan_id}, {"_id": 0})
        check(plan_a and plan_b, "Global plan catalog is visible across tenants")

        print("\nRESULT: PASS - Tenant A and Tenant B are isolated at the database proxy layer.")
        return 0
    finally:
        # Cleanup using the raw disposable database so cleanup is not tenant-scoped.
        for name in ("tenant_probe", "settings", "users", "companies"):
            await raw_db[name].delete_many({"test_marker": marker})
        await raw_db.tenants.delete_many({"test_marker": marker})
        await raw_db.plans.delete_many({"test_marker": marker})
        client.close()


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    sys.exit(code)
