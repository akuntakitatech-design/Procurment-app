"""API-level multi-tenant isolation integration test.

Runs only against the disposable Docker test stack. It starts the real production bootstrap,
creates two synthetic tenant admins directly in the disposable MongoDB, then exercises the
actual HTTP API for master data and MRO -> RO -> PO. The same business codes are deliberately
used in both tenants to prove that queries and uniqueness checks are tenant-scoped.
"""
import os
import sys
import time
import uuid

import requests
from pymongo import MongoClient

import auth as A


API = os.environ.get("TEST_API_URL", "http://tenant-test-api:8000/api").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://tenant-test-mongodb:27017")
DB_NAME = os.environ.get("DB_NAME", "procurement_tenant_api_test")
PASSWORD = "TenantTest!123"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(60):
        try:
            r = requests.get(f"{base}/docs", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend test tidak siap dalam 60 detik")


def login(email):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}, timeout=15)
    check(r.status_code == 200, f"Login berhasil untuk {email}")
    token = r.json().get("token")
    check(bool(token), f"Token login tersedia untuk {email}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def post_ok(session, path, payload, label):
    r = session.post(f"{API}{path}", json=payload, timeout=20)
    if r.status_code >= 300:
        raise AssertionError(f"{label}: HTTP {r.status_code} {r.text}")
    print(f"PASS: {label}")
    return r.json()


def get_ok(session, path, label):
    r = session.get(f"{API}{path}", timeout=20)
    if r.status_code >= 300:
        raise AssertionError(f"{label}: HTTP {r.status_code} {r.text}")
    print(f"PASS: {label}")
    return r.json()


def create_master(session, name, code, display_name, extra=None):
    body = {"code": code, "name": display_name, "is_active": True}
    if extra:
        body.update(extra)
    return post_ok(session, f"/master/{name}", body, f"Create {name} {code}")


def main():
    wait_api()
    run_id = uuid.uuid4().hex[:10]
    tenant_a = os.environ.get("DEFAULT_TENANT_ID", "tenant-pt-real")
    company_a = os.environ.get("DEFAULT_COMPANY_ID", "company-pt-real")
    tenant_b = f"api-tenant-b-{run_id}"
    company_b = f"api-company-b-{run_id}"
    plan_id = f"api-plan-{run_id}"
    email_a = f"tenant-a-{run_id}@example.test"
    email_b = f"tenant-b-{run_id}@example.test"
    marker_a = f"API-A-{run_id}"
    marker_b = f"API-B-{run_id}"

    mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    db = mongo[DB_NAME]
    mongo.admin.command("ping")

    admin_permissions = [
        "view", "create", "edit", "delete", "submit", "approve", "reject", "cancel", "close",
        "print", "export", "upload_attachment", "view_all_division", "view_all_warehouse",
        "view_purchase_price", "edit_purchase_price", "override_qty", "direct_mi",
        "stock_adjustment", "post_stock_opname",
    ]

    try:
        # Global SaaS seed for Tenant B. Tenant A is created by the real production bootstrap.
        db.plans.insert_one({
            "id": plan_id,
            "code": f"api-test-{run_id}",
            "name": "API Isolation Test",
            "is_active": True,
            "limits": {"max_users": 10, "max_companies": 2, "max_warehouses": 10, "max_divisions": 10},
        })
        db.tenants.insert_one({
            "id": tenant_b,
            "slug": f"api-b-{run_id}",
            "name": "Tenant B API Test",
            "status": "active",
            "plan_id": plan_id,
            "limits": {"max_users": 10},
        })
        db.companies.insert_one({
            "id": company_b,
            "tenant_id": tenant_b,
            "name": "Tenant B API Test",
            "is_primary": True,
            "is_active": True,
        })

        for tenant_id, company_id, email, name in (
            (tenant_a, company_a, email_a, "Admin Tenant A"),
            (tenant_b, company_b, email_b, "Admin Tenant B"),
        ):
            db.users.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "company_id": company_id,
                "email": email,
                "password_hash": A.hash_password(PASSWORD),
                "name": name,
                "role": "admin",
                "divisions": [],
                "warehouses": [],
                "permissions": admin_permissions,
                "scope": "global",
                "is_active": True,
                "token_version": 0,
                "signature_url": None,
            })

        a = login(email_a)
        b = login(email_b)

        iso_a = get_ok(a, "/tenant/isolation-status", "Isolation status dapat dibaca Tenant A")
        iso_b = get_ok(b, "/tenant/isolation-status", "Isolation status dapat dibaca Tenant B")
        check(iso_a.get("installed") is True and iso_b.get("installed") is True,
              "Tenant isolation layer aktif pada real HTTP backend")

        # Deliberately reuse the same master codes in both tenants.
        div_a = create_master(a, "divisions", "TST", f"Divisi {marker_a}")
        wh_a = create_master(a, "warehouses", "WH-TST", f"Gudang {marker_a}")
        sup_a = create_master(a, "suppliers", "SUP-TST", f"Supplier {marker_a}")
        item_a = create_master(a, "items", "ITEM-TST", f"Item {marker_a}", {
            "unit": "pcs", "division_id": div_a["id"]
        })

        div_b = create_master(b, "divisions", "TST", f"Divisi {marker_b}")
        wh_b = create_master(b, "warehouses", "WH-TST", f"Gudang {marker_b}")
        sup_b = create_master(b, "suppliers", "SUP-TST", f"Supplier {marker_b}")
        item_b = create_master(b, "items", "ITEM-TST", f"Item {marker_b}", {
            "unit": "pcs", "division_id": div_b["id"]
        })
        check(item_a["id"] != item_b["id"], "Kode item yang sama dapat hidup di dua tenant berbeda")

        # MRO A and B.
        mro_a = post_ok(a, "/mro", {
            "division_id": div_a["id"], "default_warehouse_id": wh_a["id"],
            "notes": marker_a, "submitted": True,
            "lines": [{"item_id": item_a["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_a["id"]}],
        }, "Tenant A membuat MRO")
        mro_b = post_ok(b, "/mro", {
            "division_id": div_b["id"], "default_warehouse_id": wh_b["id"],
            "notes": marker_b, "submitted": True,
            "lines": [{"item_id": item_b["id"], "qty": 7, "unit": "pcs", "warehouse_id": wh_b["id"]}],
        }, "Tenant B membuat MRO")

        list_a = get_ok(a, "/mro", "Tenant A membaca daftar MRO")
        list_b = get_ok(b, "/mro", "Tenant B membaca daftar MRO")
        check(any(x["id"] == mro_a["id"] for x in list_a) and not any(x["id"] == mro_b["id"] for x in list_a),
              "Daftar MRO Tenant A tidak bocor Tenant B")
        check(any(x["id"] == mro_b["id"] for x in list_b) and not any(x["id"] == mro_a["id"] for x in list_b),
              "Daftar MRO Tenant B tidak bocor Tenant A")
        cross = a.get(f"{API}/mro/{mro_b['id']}", timeout=15)
        check(cross.status_code == 404, "Tenant A tidak dapat membuka detail MRO Tenant B")

        # RO sourced from each tenant's own MRO.
        ma_line = mro_a["lines"][0]
        mb_line = mro_b["lines"][0]
        ro_a = post_ok(a, "/ro", {
            "division_id": div_a["id"], "default_warehouse_id": wh_a["id"], "notes": marker_a,
            "submitted": True,
            "lines": [{
                "item_id": item_a["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_a["id"],
                "sources": [{"line_id": ma_line["id"], "mro_id": mro_a["id"], "qty": 5}],
            }],
        }, "Tenant A membuat RO dari MRO sendiri")
        ro_b = post_ok(b, "/ro", {
            "division_id": div_b["id"], "default_warehouse_id": wh_b["id"], "notes": marker_b,
            "submitted": True,
            "lines": [{
                "item_id": item_b["id"], "qty": 7, "unit": "pcs", "warehouse_id": wh_b["id"],
                "sources": [{"line_id": mb_line["id"], "mro_id": mro_b["id"], "qty": 7}],
            }],
        }, "Tenant B membuat RO dari MRO sendiri")
        cross = b.get(f"{API}/ro/{ro_a['id']}", timeout=15)
        check(cross.status_code == 404, "Tenant B tidak dapat membuka detail RO Tenant A")

        pull_a = get_ok(a, "/pull/ro-for-po", "Tenant A membuka sumber RO untuk PO")
        pull_b = get_ok(b, "/pull/ro-for-po", "Tenant B membuka sumber RO untuk PO")
        check(any(x["ro_id"] == ro_a["id"] for x in pull_a) and not any(x["ro_id"] == ro_b["id"] for x in pull_a),
              "Pull RO->PO Tenant A terisolasi")
        check(any(x["ro_id"] == ro_b["id"] for x in pull_b) and not any(x["ro_id"] == ro_a["id"] for x in pull_b),
              "Pull RO->PO Tenant B terisolasi")

        # PO sourced from each tenant's own RO.
        ra_line = ro_a["lines"][0]
        rb_line = ro_b["lines"][0]
        po_a = post_ok(a, "/po", {
            "supplier_id": sup_a["id"], "division_id": div_a["id"], "default_warehouse_id": wh_a["id"],
            "internal_notes": marker_a,
            "lines": [{
                "item_id": item_a["id"], "qty": 5, "unit": "pcs", "price": 1000,
                "warehouse_id": wh_a["id"],
                "sources": [{"line_id": ra_line["id"], "ro_id": ro_a["id"], "qty": 5}],
            }],
        }, "Tenant A membuat PO")
        po_b = post_ok(b, "/po", {
            "supplier_id": sup_b["id"], "division_id": div_b["id"], "default_warehouse_id": wh_b["id"],
            "internal_notes": marker_b,
            "lines": [{
                "item_id": item_b["id"], "qty": 7, "unit": "pcs", "price": 2000,
                "warehouse_id": wh_b["id"],
                "sources": [{"line_id": rb_line["id"], "ro_id": ro_b["id"], "qty": 7}],
            }],
        }, "Tenant B membuat PO")

        pos_a = get_ok(a, "/po", "Tenant A membaca daftar PO")
        pos_b = get_ok(b, "/po", "Tenant B membaca daftar PO")
        check(any(x["id"] == po_a["id"] for x in pos_a) and not any(x["id"] == po_b["id"] for x in pos_a),
              "Daftar PO Tenant A tidak bocor Tenant B")
        check(any(x["id"] == po_b["id"] for x in pos_b) and not any(x["id"] == po_a["id"] for x in pos_b),
              "Daftar PO Tenant B tidak bocor Tenant A")
        cross = a.get(f"{API}/po/{po_b['id']}", timeout=15)
        check(cross.status_code == 404, "Tenant A tidak dapat membuka detail PO Tenant B")

        # User directory is also scoped by tenant.
        users_a = get_ok(a, "/users", "Tenant A membaca user directory")
        users_b = get_ok(b, "/users", "Tenant B membaca user directory")
        check(any(x["email"] == email_a for x in users_a) and not any(x["email"] == email_b for x in users_a),
              "User Tenant A tidak melihat user Tenant B")
        check(any(x["email"] == email_b for x in users_b) and not any(x["email"] == email_a for x in users_b),
              "User Tenant B tidak melihat user Tenant A")

        print("\nRESULT: PASS - HTTP API MRO/RO/PO dan master data terisolasi antara Tenant A dan Tenant B.")
        return 0
    finally:
        mongo.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
