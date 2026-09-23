"""Disposable integration test for MRO -> RO -> PO flow integrity."""
import os
import sys
import time
import uuid

import requests


API = os.environ.get("TEST_API_URL", "http://flow-test-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "flow-admin@example.test")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "FlowAdmin!123")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


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
    raise RuntimeError("Backend test tidak siap dalam 75 detik")


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    check(r.status_code == 200, f"Login {email} berhasil")
    token = r.json().get("token")
    check(bool(token), f"Token {email} tersedia")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def create_master(session, name, payload):
    r = session.post(f"{API}/master/{name}", json=payload, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Gagal membuat master {name}: HTTP {r.status_code} {r.text}")
    return r.json()


def source_row(rows, key, value):
    for row in rows:
        if row.get(key) == value:
            return row
    return None


def main():
    wait_api()
    run = uuid.uuid4().hex[:8]
    admin = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    div_a = create_master(admin, "divisions", {"code": f"A{run}", "name": f"Divisi A {run}"})
    div_b = create_master(admin, "divisions", {"code": f"B{run}", "name": f"Divisi B {run}"})
    wh = create_master(admin, "warehouses", {"code": f"WH{run}", "name": f"Gudang {run}", "division_id": div_a["id"]})
    supplier = create_master(admin, "suppliers", {"code": f"SUP{run}", "name": f"Supplier {run}"})
    item = create_master(admin, "items", {"code": f"IT{run}", "name": f"Item {run}", "unit": "pcs", "division_id": div_a["id"]})
    check(all(x.get("id") for x in (div_a, div_b, wh, supplier, item)), "Master pengujian tersedia")

    mro = admin.post(
        f"{API}/mro",
        json={
            "date": "2026-09-18",
            "division_id": div_a["id"],
            "default_warehouse_id": wh["id"],
            "requester": "Flow Tester",
            "lines": [{"item_id": item["id"], "qty": 10, "unit": "pcs", "warehouse_id": wh["id"]}],
        },
        timeout=15,
    )
    check(mro.status_code == 200, "MRO dapat dibuat")
    mroj = mro.json(); mro_id = mroj["id"]; mro_line = mroj["lines"][0]["id"]
    submitted = admin.post(f"{API}/mro/{mro_id}/submit", timeout=15)
    check(submitted.status_code == 200, "MRO dapat disubmit")

    ro = admin.post(
        f"{API}/ro",
        json={
            "date": "2026-09-18",
            "division_id": div_a["id"],
            "default_warehouse_id": wh["id"],
            "requester": "Flow Tester",
            "lines": [{
                "item_id": item["id"], "qty": 6, "unit": "pcs", "warehouse_id": wh["id"],
                "sources": [{"mro_id": mro_id, "line_id": mro_line, "qty": 6, "base_qty": 6}],
            }],
        },
        timeout=15,
    )
    check(ro.status_code == 200, "RO partial 6 dari MRO 10 dapat dibuat")
    roj = ro.json(); ro_id = roj["id"]; ro_line = roj["lines"][0]["id"]
    ro_submit = admin.post(f"{API}/ro/{ro_id}/submit", timeout=15)
    check(ro_submit.status_code == 200, "RO dapat disubmit")

    mro_pull = admin.get(f"{API}/pull/mro-for-ro", timeout=15)
    check(mro_pull.status_code == 200, "Outstanding MRO dapat dibaca")
    mro_row = source_row(mro_pull.json(), "mro_id", mro_id)
    check(mro_row is not None and abs(float(mro_row.get("outstanding", 0)) - 4) < 1e-6, "MRO 10 setelah RO 6 menyisakan outstanding 4")

    blocked_mro_cancel = admin.post(f"{API}/mro/{mro_id}/cancel", json={"reason": "uji"}, timeout=15)
    check(blocked_mro_cancel.status_code == 409, "MRO tidak dapat dibatalkan saat masih memiliki RO aktif")

    po = admin.post(
        f"{API}/po",
        json={
            "date": "2026-09-18",
            "division_id": div_a["id"],
            "supplier_id": supplier["id"],
            "default_warehouse_id": wh["id"],
            "currency": "IDR",
            "lines": [{
                "item_id": item["id"], "qty": 4, "unit": "pcs", "warehouse_id": wh["id"],
                "price": 1000, "discount": 0, "tax": 0,
                "sources": [{"ro_id": ro_id, "line_id": ro_line, "qty": 4, "base_qty": 4}],
            }],
        },
        timeout=15,
    )
    check(po.status_code == 200, "PO partial 4 dari RO 6 dapat dibuat")
    poj = po.json(); po_id = poj["id"]
    po_submit = admin.post(f"{API}/po/{po_id}/submit", timeout=15)
    check(po_submit.status_code == 200 and po_submit.json().get("status") == "Approved", "PO tanpa workflow approval menjadi Approved setelah submit")

    ro_pull = admin.get(f"{API}/pull/ro-for-po", timeout=15)
    check(ro_pull.status_code == 200, "Outstanding RO dapat dibaca")
    ro_row = source_row(ro_pull.json(), "ro_id", ro_id)
    check(ro_row is not None and abs(float(ro_row.get("outstanding", 0)) - 2) < 1e-6, "RO 6 setelah PO 4 menyisakan outstanding 2")

    blocked_ro_cancel = admin.post(f"{API}/ro/{ro_id}/cancel", json={"reason": "uji"}, timeout=15)
    check(blocked_ro_cancel.status_code == 409, "RO tidak dapat dibatalkan saat masih memiliki PO aktif")

    po_cancel = admin.post(f"{API}/po/{po_id}/cancel", json={"reason": "uji release"}, timeout=15)
    check(po_cancel.status_code == 200, "PO tanpa DO dapat dibatalkan")
    ro_pull_after = admin.get(f"{API}/pull/ro-for-po", timeout=15)
    ro_row_after = source_row(ro_pull_after.json(), "ro_id", ro_id)
    check(ro_row_after is not None and abs(float(ro_row_after.get("outstanding", 0)) - 6) < 1e-6, "Pembatalan PO mengembalikan outstanding RO menjadi 6")

    blocked_resubmit_cancelled_po = admin.post(f"{API}/po/{po_id}/submit", timeout=15)
    check(blocked_resubmit_cancelled_po.status_code == 409, "PO yang sudah dibatalkan tidak dapat disubmit ulang")

    ro_cancel = admin.post(f"{API}/ro/{ro_id}/cancel", json={"reason": "uji release"}, timeout=15)
    check(ro_cancel.status_code == 200, "RO dapat dibatalkan setelah PO turunannya dibatalkan")
    mro_pull_after = admin.get(f"{API}/pull/mro-for-ro", timeout=15)
    mro_row_after = source_row(mro_pull_after.json(), "mro_id", mro_id)
    check(mro_row_after is not None and abs(float(mro_row_after.get("outstanding", 0)) - 10) < 1e-6, "Pembatalan RO mengembalikan outstanding MRO menjadi 10")

    # Build a second active chain and receive only part of the PO.
    ro2 = admin.post(
        f"{API}/ro",
        json={
            "date": "2026-09-18", "division_id": div_a["id"], "default_warehouse_id": wh["id"],
            "lines": [{
                "item_id": item["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh["id"],
                "sources": [{"mro_id": mro_id, "line_id": mro_line, "qty": 5, "base_qty": 5}],
            }],
        }, timeout=15,
    )
    check(ro2.status_code == 200, "RO kedua dapat dibuat dari outstanding yang kembali")
    ro2j = ro2.json(); ro2_id = ro2j["id"]; ro2_line = ro2j["lines"][0]["id"]
    check(admin.post(f"{API}/ro/{ro2_id}/submit", timeout=15).status_code == 200, "RO kedua dapat disubmit")

    po2 = admin.post(
        f"{API}/po",
        json={
            "date": "2026-09-18", "division_id": div_a["id"], "supplier_id": supplier["id"],
            "default_warehouse_id": wh["id"], "currency": "IDR",
            "lines": [{
                "item_id": item["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh["id"], "price": 1000,
                "sources": [{"ro_id": ro2_id, "line_id": ro2_line, "qty": 5, "base_qty": 5}],
            }],
        }, timeout=15,
    )
    check(po2.status_code == 200, "PO kedua dapat dibuat")
    po2j = po2.json(); po2_id = po2j["id"]; po2_line = po2j["lines"][0]["id"]
    po2_submit = admin.post(f"{API}/po/{po2_id}/submit", timeout=15)
    check(po2_submit.status_code == 200 and po2_submit.json().get("status") == "Approved", "PO kedua Approved")

    do = admin.post(
        f"{API}/do",
        json={
            "date": "2026-09-18", "supplier_id": supplier["id"], "default_warehouse_id": wh["id"],
            "lines": [{
                "po_id": po2_id, "po_line_id": po2_line, "item_id": item["id"], "qty": 2,
                "unit": "pcs", "warehouse_id": wh["id"],
            }],
        }, timeout=15,
    )
    check(do.status_code == 200, "DO partial 2 dari PO 5 dapat diposting")
    po2_detail = admin.get(f"{API}/po/{po2_id}", timeout=15)
    check(po2_detail.status_code == 200 and po2_detail.json().get("status") == "Partially Received", "PO berubah menjadi Partially Received")

    po_pull = admin.get(f"{API}/pull/po-for-do?supplier_id={supplier['id']}", timeout=15)
    po_row = source_row(po_pull.json(), "po_id", po2_id)
    check(po_row is not None and abs(float(po_row.get("outstanding", 0)) - 3) < 1e-6, "PO 5 setelah DO 2 menyisakan outstanding penerimaan 3")

    blocked_po_cancel = admin.post(f"{API}/po/{po2_id}/cancel", json={"reason": "harus ditolak"}, timeout=15)
    check(blocked_po_cancel.status_code == 409, "PO tidak dapat dibatalkan saat masih memiliki DO aktif")
    blocked_po_resubmit = admin.post(f"{API}/po/{po2_id}/submit", timeout=15)
    check(blocked_po_resubmit.status_code == 409, "PO Partially Received tidak dapat disubmit ulang")

    # Direct action endpoints must also respect division scope, not only list/detail/edit routes.
    other_email = f"other-{run}@example.test"
    user_create = admin.post(
        f"{API}/users",
        json={
            "email": other_email, "password": "OtherUser!123", "name": "User Divisi B", "role": "warehouse",
            "scope": "limited", "divisions": [div_b["id"]], "warehouses": [],
            "permissions": ["view", "create", "edit", "delete", "submit", "cancel"],
        }, timeout=15,
    )
    check(user_create.status_code == 200, "User divisi lain dapat dibuat untuk pengujian")
    other = login(other_email, "OtherUser!123")
    cross_submit = other.post(f"{API}/mro/{mro_id}/submit", timeout=15)
    cross_cancel = other.post(f"{API}/mro/{mro_id}/cancel", json={"reason": "cross division"}, timeout=15)
    check(cross_submit.status_code == 403 and cross_cancel.status_code == 403, "Submit/cancel langsung tetap diblokir untuk divisi lain")

    print("\nRESULT: PASS - partial/outstanding, cancel release, downstream blocker, status PO, dan action guard konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
