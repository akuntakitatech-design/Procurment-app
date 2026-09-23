"""Disposable security regression test for tenant hardening.

Covers ownership mutation, aggregate/raw DB bypasses, malicious cross-tenant transaction
references, and attachment authentication/storage isolation against the real HTTP backend.
"""
import os
import sys
import time
import uuid

import requests
from pymongo import MongoClient

import auth as A
import tenant_isolation_layer as I
import tenant_security_hardening_layer as H


API = os.environ.get("TEST_API_URL", "http://tenant-test-api:8000/api").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://tenant-test-mongodb:27017")
DB_NAME = os.environ.get("DB_NAME", "procurement_tenant_security_test")
PASSWORD = "TenantSecurity!123"
TEST_EMAIL_DOMAIN = os.environ.get("TEST_EMAIL_DOMAIN", "akuntakita.com")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def expect_raises(fn, message):
    try:
        fn()
    except RuntimeError:
        print(f"PASS: {message}")
        return
    raise AssertionError(message)


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            r = requests.get(f"{base}/docs", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend security test tidak siap dalam 75 detik")


def login(email):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Login {email} gagal: HTTP {r.status_code} {r.text}")
    token = r.json().get("token")
    check(bool(token), f"Token login tersedia untuk {email}")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session, token


def post_ok(session, path, payload, label):
    r = session.post(f"{API}{path}", json=payload, timeout=20)
    if r.status_code >= 300:
        raise AssertionError(f"{label}: HTTP {r.status_code} {r.text}")
    print(f"PASS: {label}")
    return r.json()


def create_master(session, name, code, display_name, extra=None):
    body = {"code": code, "name": display_name, "is_active": True}
    if extra:
        body.update(extra)
    return post_ok(session, f"/master/{name}", body, f"Create {name} {code}")


def test_proxy_hardening():
    H._install_proxy_hardening()
    tenant_token = I._current_tenant.set("tenant-security-a")
    company_token = I._current_company.set("company-security-a")
    try:
        doc = I._tag_document("items", {"id": "x", "tenant_id": "tenant-security-b"})
        check(doc.get("tenant_id") == "tenant-security-a", "Insert payload tidak dapat menyuntik tenant_id tenant lain")

        upd = I._tag_update(
            "items",
            {"$set": {"tenant_id": "tenant-security-b", "name": "X"}, "$unset": {"tenant_id": ""}},
        )
        check(upd.get("$set", {}).get("tenant_id") == "tenant-security-a", "Update $set tenant_id dipaksa ke tenant aktif")
        check("tenant_id" not in upd.get("$unset", {}), "Update $unset tidak dapat menghapus tenant_id")

        expect_raises(
            lambda: I._tag_update("items", {"$rename": {"tenant_id": "owner"}}),
            "$rename tenant_id diblokir",
        )
        expect_raises(
            lambda: I._tag_update("items", [{"$set": {"tenant_id": "tenant-security-b"}}]),
            "Update pipeline tenant-scoped diblokir",
        )

        class FakeRawCollection:
            name = "items"
            def aggregate(self, pipeline, *args, **kwargs):
                self.pipeline = pipeline
                return pipeline

        col = I.TenantCollectionProxy(FakeRawCollection())
        expect_raises(
            lambda: col.aggregate([{"$lookup": {"from": "users", "pipeline": [], "as": "x"}}]),
            "$lookup lintas collection diblokir",
        )
        expect_raises(
            lambda: col.aggregate([{"$unionWith": "items"}]),
            "$unionWith diblokir",
        )
        expect_raises(lambda: getattr(col, "database"), "Akses collection.database raw diblokir")

        safe_pipeline = col.aggregate([{"$match": {"is_active": True}}])
        check(
            safe_pipeline[0] == {"$match": {"tenant_id": "tenant-security-a"}},
            "Aggregation aman selalu diawali tenant match",
        )

        class FakeRawDb:
            name = "fake"
            client = object()
            def __getitem__(self, name):
                raw = FakeRawCollection()
                raw.name = name
                return raw

        proxy_db = I.TenantDatabaseProxy(FakeRawDb())
        expect_raises(lambda: getattr(proxy_db, "client"), "Akses raw database client diblokir")
        expect_raises(lambda: getattr(proxy_db, "command"), "Akses raw database command diblokir")
    finally:
        I._current_company.reset(company_token)
        I._current_tenant.reset(tenant_token)


def main():
    test_proxy_hardening()
    wait_api()

    run_id = uuid.uuid4().hex[:10]
    tenant_a = os.environ.get("DEFAULT_TENANT_ID", "tenant-pt-real")
    company_a = os.environ.get("DEFAULT_COMPANY_ID", "company-pt-real")
    tenant_b = f"security-tenant-b-{run_id}"
    company_b = f"security-company-b-{run_id}"
    plan_id = f"security-plan-{run_id}"
    email_a = f"security-a-{run_id}@{TEST_EMAIL_DOMAIN}"
    email_b = f"security-b-{run_id}@{TEST_EMAIL_DOMAIN}"
    marker_a = f"SEC-A-{run_id}"
    marker_b = f"SEC-B-{run_id}"

    mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    db = mongo[DB_NAME]
    mongo.admin.command("ping")

    permissions = [
        "view", "create", "edit", "delete", "submit", "approve", "reject", "cancel", "close",
        "print", "export", "upload_attachment", "view_all_division", "view_all_warehouse",
        "view_purchase_price", "edit_purchase_price", "override_qty", "direct_mi",
        "stock_adjustment", "post_stock_opname",
    ]

    try:
        db.plans.insert_one({
            "id": plan_id, "code": f"security-{run_id}", "name": "Security Test",
            "is_active": True, "limits": {"max_users": 10, "max_companies": 2, "max_warehouses": 10, "max_divisions": 10},
        })
        db.tenants.insert_one({
            "id": tenant_b, "slug": f"security-b-{run_id}", "name": "Tenant B Security",
            "status": "active", "plan_id": plan_id, "limits": {"max_users": 10},
        })
        db.companies.insert_one({
            "id": company_b, "tenant_id": tenant_b, "name": "Tenant B Security",
            "is_primary": True, "is_active": True,
        })

        for tenant_id, company_id, email, name in (
            (tenant_a, company_a, email_a, "Security Admin A"),
            (tenant_b, company_b, email_b, "Security Admin B"),
        ):
            db.users.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tenant_id, "company_id": company_id,
                "email": email, "password_hash": A.hash_password(PASSWORD), "name": name,
                "role": "admin", "divisions": [], "warehouses": [], "permissions": permissions,
                "scope": "global", "is_active": True, "token_version": 0, "signature_url": None,
            })

        a, token_a = login(email_a)
        b, token_b = login(email_b)

        div_a = create_master(a, "divisions", "SEC", f"Divisi {marker_a}")
        wh_a = create_master(a, "warehouses", "WH-SEC", f"Gudang {marker_a}")
        sup_a = create_master(a, "suppliers", "SUP-SEC", f"Supplier {marker_a}")
        item_a = create_master(a, "items", "ITEM-SEC", f"Item {marker_a}", {"unit": "pcs", "division_id": div_a["id"]})

        div_b = create_master(b, "divisions", "SEC", f"Divisi {marker_b}")
        wh_b = create_master(b, "warehouses", "WH-SEC", f"Gudang {marker_b}")
        sup_b = create_master(b, "suppliers", "SUP-SEC", f"Supplier {marker_b}")
        item_b = create_master(b, "items", "ITEM-SEC", f"Item {marker_b}", {"unit": "pcs", "division_id": div_b["id"]})

        mro_a = post_ok(a, "/mro", {
            "division_id": div_a["id"], "default_warehouse_id": wh_a["id"], "notes": marker_a,
            "submitted": True,
            "lines": [{"item_id": item_a["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_a["id"]}],
        }, "Tenant A membuat MRO security test")
        mro_b = post_ok(b, "/mro", {
            "division_id": div_b["id"], "default_warehouse_id": wh_b["id"], "notes": marker_b,
            "submitted": True,
            "lines": [{"item_id": item_b["id"], "qty": 7, "unit": "pcs", "warehouse_id": wh_b["id"]}],
        }, "Tenant B membuat MRO security test")
        ma_line = mro_a["lines"][0]
        mb_line = mro_b["lines"][0]

        before_ro = db.ro.count_documents({"tenant_id": tenant_a})
        bad_ro = a.post(f"{API}/ro", json={
            "division_id": div_a["id"], "default_warehouse_id": wh_a["id"], "notes": "cross-source",
            "submitted": True,
            "lines": [{
                "item_id": item_a["id"], "qty": 1, "unit": "pcs", "warehouse_id": wh_a["id"],
                "sources": [{"line_id": mb_line["id"], "mro_id": mro_b["id"], "qty": 1}],
            }],
        }, timeout=20)
        check(bad_ro.status_code in (400, 404), "RO menolak source line milik Tenant B")
        check(db.ro.count_documents({"tenant_id": tenant_a}) == before_ro, "RO cross-tenant ditolak sebelum header tersimpan")

        ro_a = post_ok(a, "/ro", {
            "division_id": div_a["id"], "default_warehouse_id": wh_a["id"], "notes": marker_a, "submitted": True,
            "lines": [{
                "item_id": item_a["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_a["id"],
                "sources": [{"line_id": ma_line["id"], "mro_id": mro_a["id"], "qty": 5}],
            }],
        }, "RO valid Tenant A tetap dapat dibuat setelah security gate")
        ro_b = post_ok(b, "/ro", {
            "division_id": div_b["id"], "default_warehouse_id": wh_b["id"], "notes": marker_b, "submitted": True,
            "lines": [{
                "item_id": item_b["id"], "qty": 7, "unit": "pcs", "warehouse_id": wh_b["id"],
                "sources": [{"line_id": mb_line["id"], "mro_id": mro_b["id"], "qty": 7}],
            }],
        }, "RO valid Tenant B tetap dapat dibuat setelah security gate")
        ra_line = ro_a["lines"][0]
        rb_line = ro_b["lines"][0]

        before_po = db.po.count_documents({"tenant_id": tenant_a})
        bad_po = a.post(f"{API}/po", json={
            "supplier_id": sup_a["id"], "division_id": div_a["id"], "default_warehouse_id": wh_a["id"],
            "lines": [{
                "item_id": item_a["id"], "qty": 1, "unit": "pcs", "price": 1000, "warehouse_id": wh_a["id"],
                "sources": [{"line_id": rb_line["id"], "ro_id": ro_b["id"], "qty": 1}],
            }],
        }, timeout=20)
        check(bad_po.status_code in (400, 404), "PO menolak source RO milik Tenant B")
        check(db.po.count_documents({"tenant_id": tenant_a}) == before_po, "PO cross-tenant ditolak sebelum header tersimpan")

        po_b = post_ok(b, "/po", {
            "supplier_id": sup_b["id"], "division_id": div_b["id"], "default_warehouse_id": wh_b["id"],
            "lines": [{
                "item_id": item_b["id"], "qty": 7, "unit": "pcs", "price": 2000, "warehouse_id": wh_b["id"],
                "sources": [{"line_id": rb_line["id"], "ro_id": ro_b["id"], "qty": 7}],
            }],
        }, "PO valid Tenant B tetap dapat dibuat setelah security gate")
        pb_line = po_b["lines"][0]

        before_do = db.do.count_documents({"tenant_id": tenant_a})
        bad_do = a.post(f"{API}/do", json={
            "supplier_id": sup_a["id"], "default_warehouse_id": wh_a["id"],
            "lines": [{
                "po_id": po_b["id"], "po_line_id": pb_line["id"], "item_id": item_b["id"],
                "qty": 1, "unit": "pcs", "warehouse_id": wh_a["id"],
            }],
        }, timeout=20)
        check(bad_do.status_code in (400, 404), "DO menolak PO line milik Tenant B")
        check(db.do.count_documents({"tenant_id": tenant_a}) == before_do, "DO cross-tenant ditolak sebelum header/stok berubah")

        before_mi = db.mi.count_documents({"tenant_id": tenant_a})
        bad_mi = a.post(f"{API}/mi", json={
            "source_type": "MRO", "division_id": div_a["id"], "default_warehouse_id": wh_a["id"],
            "lines": [{
                "mro_id": mro_b["id"], "mro_line_id": mb_line["id"], "item_id": item_b["id"],
                "qty": 1, "unit": "pcs", "warehouse_id": wh_a["id"],
            }],
        }, timeout=20)
        check(bad_mi.status_code in (400, 404), "MI menolak MRO line milik Tenant B")
        check(db.mi.count_documents({"tenant_id": tenant_a}) == before_mi, "MI cross-tenant ditolak sebelum header/stok berubah")

        upload = b.post(
            f"{API}/attachments",
            files={"file": ("tenant-b-secret.txt", b"tenant-b-secret", "text/plain")},
            data={"entity": "mro", "entity_id": mro_b["id"], "category": "Security", "note": marker_b},
            timeout=20,
        )
        if upload.status_code >= 300:
            raise AssertionError(f"Upload attachment Tenant B gagal: HTTP {upload.status_code} {upload.text}")
        attachment = upload.json()
        aid = attachment["id"]
        check(True, "Tenant B dapat upload attachment")

        raw_attachment = db.attachments.find_one({"id": aid})
        expected_prefix = f"procureflow/tenants/{tenant_b}/"
        check(raw_attachment and raw_attachment.get("storage_path", "").startswith(expected_prefix),
              "Storage path attachment diprefix tenant_id")

        own_download = b.get(f"{API}/attachments/{aid}/download", timeout=20)
        check(own_download.status_code == 200 and own_download.content == b"tenant-b-secret",
              "Tenant B dapat download attachment sendiri")

        cross_download = a.get(f"{API}/attachments/{aid}/download", timeout=20)
        check(cross_download.status_code == 404, "Tenant A tidak dapat download attachment Tenant B")

        anonymous = requests.get(f"{API}/attachments/{aid}/download", timeout=20)
        check(anonymous.status_code == 401, "Download attachment anonim diblokir")

        query_auth = requests.get(f"{API}/attachments/{aid}/download", params={"auth": token_b}, timeout=20)
        check(query_auth.status_code == 200 and query_auth.content == b"tenant-b-secret",
              "Query-token attachment tetap didukung dengan tenant context yang benar")

        cross_list = a.get(f"{API}/attachments", params={"entity": "mro", "entity_id": mro_b["id"]}, timeout=20)
        check(cross_list.status_code == 200 and all(x.get("id") != aid for x in cross_list.json()),
              "Daftar attachment tidak bocor lintas tenant")

        iso = a.get(f"{API}/tenant/isolation-status", timeout=20)
        check(iso.status_code == 200 and iso.json().get("raw_reference_count") == 0,
              "Security hardening tidak menambah raw database reference")

        print("\nRESULT: PASS - ownership mutation, source references, aggregation/raw bypass, dan attachment isolation aman.")
        return 0
    finally:
        mongo.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
