"""API-level isolation test for DO, MI, item-warehouse and stock ledger.

Runs only against the disposable Docker test stack. It starts the real production bootstrap,
creates Tenant A and Tenant B users, then exercises purchase receipt and material issue flows
through the actual HTTP API. Raw MongoDB is used only for verification that ledger documents
are tagged with the correct tenant.
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
DB_NAME = os.environ.get("DB_NAME", "procurement_tenant_stock_test")
PASSWORD = "TenantStockTest!123"


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


def stock_row(session, item_id, warehouse_id, label):
    rows = get_ok(
        session,
        f"/item-warehouse?item_id={item_id}&warehouse_id={warehouse_id}",
        label,
    )
    return rows


def main():
    wait_api()
    run_id = uuid.uuid4().hex[:10]
    tenant_a = os.environ.get("DEFAULT_TENANT_ID", "tenant-pt-real")
    company_a = os.environ.get("DEFAULT_COMPANY_ID", "company-pt-real")
    tenant_b = f"stock-tenant-b-{run_id}"
    company_b = f"stock-company-b-{run_id}"
    plan_id = f"stock-plan-{run_id}"
    email_a = f"stock-a-{run_id}@example.test"
    email_b = f"stock-b-{run_id}@example.test"
    marker_a = f"STOCK-A-{run_id}"
    marker_b = f"STOCK-B-{run_id}"

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
        db.plans.insert_one({
            "id": plan_id,
            "code": f"stock-test-{run_id}",
            "name": "Stock Isolation Test",
            "is_active": True,
            "limits": {"max_users": 10, "max_companies": 2, "max_warehouses": 10, "max_divisions": 10},
        })
        db.tenants.insert_one({
            "id": tenant_b,
            "slug": f"stock-b-{run_id}",
            "name": "Tenant B Stock Test",
            "status": "active",
            "plan_id": plan_id,
            "limits": {"max_users": 10},
        })
        db.companies.insert_one({
            "id": company_b,
            "tenant_id": tenant_b,
            "name": "Tenant B Stock Test",
            "is_primary": True,
            "is_active": True,
        })

        for tenant_id, company_id, email, name in (
            (tenant_a, company_a, email_a, "Admin Stock Tenant A"),
            (tenant_b, company_b, email_b, "Admin Stock Tenant B"),
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

        iso_a = get_ok(a, "/tenant/isolation-status", "Self-check tenant isolation dapat dibaca")
        check(iso_a.get("installed") is True, "Tenant isolation layer aktif")
        check(iso_a.get("raw_reference_count") == 0, "Self-check tidak menemukan raw database reference")

        # Same business codes in each tenant must remain independent.
        div_a = create_master(a, "divisions", "STK", f"Divisi {marker_a}")
        wh_a = create_master(a, "warehouses", "WH-STK", f"Gudang {marker_a}")
        sup_a = create_master(a, "suppliers", "SUP-STK", f"Supplier {marker_a}")
        item_a = create_master(a, "items", "ITEM-STK", f"Item {marker_a}", {
            "unit": "pcs", "division_id": div_a["id"]
        })

        div_b = create_master(b, "divisions", "STK", f"Divisi {marker_b}")
        wh_b = create_master(b, "warehouses", "WH-STK", f"Gudang {marker_b}")
        sup_b = create_master(b, "suppliers", "SUP-STK", f"Supplier {marker_b}")
        item_b = create_master(b, "items", "ITEM-STK", f"Item {marker_b}", {
            "unit": "pcs", "division_id": div_b["id"]
        })

        # Create and submit one PO per tenant. With empty approval rules in production test
        # defaults, submit moves each PO directly to Approved.
        po_a = post_ok(a, "/po", {
            "supplier_id": sup_a["id"], "division_id": div_a["id"], "default_warehouse_id": wh_a["id"],
            "internal_notes": marker_a,
            "lines": [{"item_id": item_a["id"], "qty": 10, "unit": "pcs", "price": 1000,
                       "warehouse_id": wh_a["id"]}],
        }, "Tenant A membuat PO stok")
        po_b = post_ok(b, "/po", {
            "supplier_id": sup_b["id"], "division_id": div_b["id"], "default_warehouse_id": wh_b["id"],
            "internal_notes": marker_b,
            "lines": [{"item_id": item_b["id"], "qty": 20, "unit": "pcs", "price": 2000,
                       "warehouse_id": wh_b["id"]}],
        }, "Tenant B membuat PO stok")
        po_a = post_ok(a, f"/po/{po_a['id']}/submit", {}, "Tenant A submit PO menjadi Approved")
        po_b = post_ok(b, f"/po/{po_b['id']}/submit", {}, "Tenant B submit PO menjadi Approved")
        check(po_a.get("status") == "Approved" and po_b.get("status") == "Approved",
              "PO kedua tenant siap diterima")

        pull_a = get_ok(a, "/pull/po-for-do", "Tenant A membuka sumber PO untuk DO")
        pull_b = get_ok(b, "/pull/po-for-do", "Tenant B membuka sumber PO untuk DO")
        check(any(x["po_id"] == po_a["id"] for x in pull_a) and not any(x["po_id"] == po_b["id"] for x in pull_a),
              "Pull PO->DO Tenant A tidak bocor Tenant B")
        check(any(x["po_id"] == po_b["id"] for x in pull_b) and not any(x["po_id"] == po_a["id"] for x in pull_b),
              "Pull PO->DO Tenant B tidak bocor Tenant A")

        # Receive different quantities so cross-tenant leakage is obvious.
        poa_line = po_a["lines"][0]
        pob_line = po_b["lines"][0]
        do_a = post_ok(a, "/do", {
            "supplier_id": sup_a["id"], "default_warehouse_id": wh_a["id"], "notes": marker_a,
            "lines": [{
                "po_id": po_a["id"], "po_line_id": poa_line["id"], "item_id": item_a["id"],
                "qty": 10, "unit": "pcs", "warehouse_id": wh_a["id"],
            }],
        }, "Tenant A posting DO 10 pcs")
        do_b = post_ok(b, "/do", {
            "supplier_id": sup_b["id"], "default_warehouse_id": wh_b["id"], "notes": marker_b,
            "lines": [{
                "po_id": po_b["id"], "po_line_id": pob_line["id"], "item_id": item_b["id"],
                "qty": 20, "unit": "pcs", "warehouse_id": wh_b["id"],
            }],
        }, "Tenant B posting DO 20 pcs")

        dos_a = get_ok(a, "/do", "Tenant A membaca daftar DO")
        dos_b = get_ok(b, "/do", "Tenant B membaca daftar DO")
        check(any(x["id"] == do_a["id"] for x in dos_a) and not any(x["id"] == do_b["id"] for x in dos_a),
              "Daftar DO Tenant A terisolasi")
        check(any(x["id"] == do_b["id"] for x in dos_b) and not any(x["id"] == do_a["id"] for x in dos_b),
              "Daftar DO Tenant B terisolasi")
        cross_do = a.get(f"{API}/do/{do_b['id']}", timeout=15)
        check(cross_do.status_code == 404, "Tenant A tidak dapat membuka DO Tenant B")

        stock_a = stock_row(a, item_a["id"], wh_a["id"], "Tenant A membaca stok setelah DO")
        stock_b = stock_row(b, item_b["id"], wh_b["id"], "Tenant B membaca stok setelah DO")
        check(len(stock_a) == 1 and stock_a[0].get("current_stock") == 10, "Stok Tenant A setelah DO = 10")
        check(len(stock_b) == 1 and stock_b[0].get("current_stock") == 20, "Stok Tenant B setelah DO = 20")
        check(stock_row(a, item_b["id"], wh_b["id"], "Tenant A mencoba query stok Tenant B") == [],
              "Tenant A tidak dapat membaca item-warehouse Tenant B walau mengetahui ID")

        # Direct MI reduces stock independently in each tenant.
        mi_a = post_ok(a, "/mi", {
            "source_type": "Direct", "division_id": div_a["id"], "default_warehouse_id": wh_a["id"],
            "notes": marker_a,
            "lines": [{"item_id": item_a["id"], "qty": 3, "unit": "pcs", "warehouse_id": wh_a["id"]}],
        }, "Tenant A posting MI 3 pcs")
        mi_b = post_ok(b, "/mi", {
            "source_type": "Direct", "division_id": div_b["id"], "default_warehouse_id": wh_b["id"],
            "notes": marker_b,
            "lines": [{"item_id": item_b["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_b["id"]}],
        }, "Tenant B posting MI 5 pcs")

        mis_a = get_ok(a, "/mi", "Tenant A membaca daftar MI")
        mis_b = get_ok(b, "/mi", "Tenant B membaca daftar MI")
        check(any(x["id"] == mi_a["id"] for x in mis_a) and not any(x["id"] == mi_b["id"] for x in mis_a),
              "Daftar MI Tenant A terisolasi")
        check(any(x["id"] == mi_b["id"] for x in mis_b) and not any(x["id"] == mi_a["id"] for x in mis_b),
              "Daftar MI Tenant B terisolasi")
        cross_mi = b.get(f"{API}/mi/{mi_a['id']}", timeout=15)
        check(cross_mi.status_code == 404, "Tenant B tidak dapat membuka MI Tenant A")

        stock_a2 = stock_row(a, item_a["id"], wh_a["id"], "Tenant A membaca stok setelah MI")
        stock_b2 = stock_row(b, item_b["id"], wh_b["id"], "Tenant B membaca stok setelah MI")
        check(len(stock_a2) == 1 and stock_a2[0].get("current_stock") == 7, "Stok Tenant A setelah MI = 7")
        check(len(stock_b2) == 1 and stock_b2[0].get("current_stock") == 15, "Stok Tenant B setelah MI = 15")

        # Raw verification: stock ledger entries generated by real HTTP flows must carry
        # the correct tenant_id and never share business item ids across tenants.
        led_a = list(db.stock_ledger.find({"tenant_id": tenant_a, "item_id": item_a["id"]}))
        led_b = list(db.stock_ledger.find({"tenant_id": tenant_b, "item_id": item_b["id"]}))
        check(any(x.get("doc_type") == "DO" and x.get("qty_in") == 10 for x in led_a),
              "Ledger Tenant A menyimpan DO 10 dengan tenant_id yang benar")
        check(any(x.get("doc_type") == "MI" and x.get("qty_out") == 3 for x in led_a),
              "Ledger Tenant A menyimpan MI 3 dengan tenant_id yang benar")
        check(any(x.get("doc_type") == "DO" and x.get("qty_in") == 20 for x in led_b),
              "Ledger Tenant B menyimpan DO 20 dengan tenant_id yang benar")
        check(any(x.get("doc_type") == "MI" and x.get("qty_out") == 5 for x in led_b),
              "Ledger Tenant B menyimpan MI 5 dengan tenant_id yang benar")
        check(db.stock_ledger.count_documents({"tenant_id": tenant_a, "item_id": item_b["id"]}) == 0,
              "Ledger Tenant A tidak berisi item Tenant B")
        check(db.stock_ledger.count_documents({"tenant_id": tenant_b, "item_id": item_a["id"]}) == 0,
              "Ledger Tenant B tidak berisi item Tenant A")

        print("\nRESULT: PASS - DO, MI, item-warehouse, stock ledger dan self-check terisolasi antar tenant.")
        return 0
    finally:
        mongo.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
