"""Disposable integration test for DO / penerimaan barang integrity."""
import os
import sys
import time
import uuid

import requests


API = os.environ.get("TEST_API_URL", "http://do-test-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "do-admin@example.test")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "DoAdmin!123")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
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


def master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Gagal membuat master {name}: {r.status_code} {r.text}")
    return r.json()


def create_po(s, *, division_id, supplier_id, warehouse_id, item_id, qty, price=1000, submit=True):
    r = s.post(
        f"{API}/po",
        json={
            "date": "2026-09-18",
            "division_id": division_id,
            "supplier_id": supplier_id,
            "default_warehouse_id": warehouse_id,
            "currency": "IDR",
            "lines": [{
                "item_id": item_id,
                "qty": qty,
                "unit": "pcs",
                "warehouse_id": warehouse_id,
                "price": price,
                "discount": 0,
                "tax": 0,
            }],
        },
        timeout=15,
    )
    check(r.status_code == 200, "PO pengujian dapat dibuat")
    doc = r.json()
    if submit:
        sr = s.post(f"{API}/po/{doc['id']}/submit", timeout=15)
        check(sr.status_code == 200 and sr.json().get("status") == "Approved", "PO pengujian menjadi Approved")
        doc = sr.json()
    return doc


def stock(s, item_id, warehouse_id):
    r = s.get(f"{API}/item-warehouse?warehouse_id={warehouse_id}&item_id={item_id}", timeout=15)
    check(r.status_code == 200, "Saldo stok dapat dibaca")
    rows = r.json()
    return float(rows[0].get("current_stock", 0)) if rows else 0.0


def do_payload(*, supplier_id, warehouse_id, po_id, po_line_id, item_id, qty):
    return {
        "date": "2026-09-18",
        "supplier_id": supplier_id,
        "supplier_dn": "SJ-TEST-001",
        "default_warehouse_id": warehouse_id,
        "receiver": "DO Tester",
        "lines": [{
            "po_id": po_id,
            "po_line_id": po_line_id,
            "item_id": item_id,
            "qty": qty,
            "unit": "pcs",
            "warehouse_id": warehouse_id,
            "condition": "Baik",
            "sources": [{"po_id": po_id, "line_id": po_line_id, "qty": qty, "base_qty": qty}],
        }],
    }


def main():
    wait_api()
    run = uuid.uuid4().hex[:8]
    admin = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    div_a = master(admin, "divisions", {"code": f"DA{run}", "name": f"Divisi A {run}"})
    div_b = master(admin, "divisions", {"code": f"DB{run}", "name": f"Divisi B {run}"})
    wh_a = master(admin, "warehouses", {"code": f"WA{run}", "name": f"Gudang A {run}", "division_id": div_a["id"]})
    wh_a2 = master(admin, "warehouses", {"code": f"W2{run}", "name": f"Gudang A2 {run}", "division_id": div_a["id"]})
    supplier_a = master(admin, "suppliers", {"code": f"SA{run}", "name": f"Supplier A {run}"})
    supplier_b = master(admin, "suppliers", {"code": f"SB{run}", "name": f"Supplier B {run}"})
    item = master(admin, "items", {"code": f"IT{run}", "name": f"Item DO {run}", "unit": "pcs", "division_id": div_a["id"]})
    check(all(x.get("id") for x in (div_a, div_b, wh_a, wh_a2, supplier_a, supplier_b, item)), "Master DO tersedia")

    po = create_po(
        admin,
        division_id=div_a["id"], supplier_id=supplier_a["id"], warehouse_id=wh_a["id"],
        item_id=item["id"], qty=10,
    )
    po_id = po["id"]
    po_line_id = po["lines"][0]["id"]

    # Supplier mismatch must be rejected before any DO/stock write.
    before_count = len(admin.get(f"{API}/do", timeout=15).json())
    bad_supplier = admin.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_b["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=1,
        ), timeout=15,
    )
    check(bad_supplier.status_code == 400, "Supplier DO yang berbeda dari PO ditolak")
    after_count = len(admin.get(f"{API}/do", timeout=15).json())
    check(after_count == before_count and abs(stock(admin, item["id"], wh_a["id"])) < 1e-6, "Validasi gagal tidak meninggalkan header DO atau stok parsial")

    # Draft PO is not eligible for receiving.
    draft_po = create_po(
        admin,
        division_id=div_a["id"], supplier_id=supplier_a["id"], warehouse_id=wh_a["id"],
        item_id=item["id"], qty=2, submit=False,
    )
    draft_receive = admin.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=draft_po["id"],
            po_line_id=draft_po["lines"][0]["id"], item_id=item["id"], qty=1,
        ), timeout=15,
    )
    check(draft_receive.status_code == 409, "PO Draft tidak dapat diterima")

    # First partial receipt.
    do1 = admin.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=4,
        ), timeout=15,
    )
    check(do1.status_code == 200, "DO partial 4 dari PO 10 dapat diposting")
    do1j = do1.json(); do1_id = do1j["id"]
    check(do1j.get("division_id") == div_a["id"], "DO mewarisi divisi dari PO")
    check(abs(stock(admin, item["id"], wh_a["id"]) - 4) < 1e-6, "DO partial menambah stok 4")

    detail1 = admin.get(f"{API}/do/{do1_id}", timeout=15)
    check(detail1.status_code == 200, "Detail DO dapat dibaca")
    dline = detail1.json()["lines"][0]
    check(abs(float(dline.get("qty_po", 0)) - 10) < 1e-6, "Detail DO menampilkan Qty PO 10")
    check(abs(float(dline.get("received_before", 0))) < 1e-6, "Detail DO pertama menampilkan penerimaan sebelumnya 0")
    check(abs(float(dline.get("outstanding", 0)) - 6) < 1e-6, "Detail DO menampilkan sisa PO 6")
    po_after1 = admin.get(f"{API}/po/{po_id}", timeout=15).json()
    check(po_after1.get("status") == "Partially Received", "PO berubah menjadi Partially Received")

    # Reject over receipt before stock is touched.
    bad_over = admin.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=7,
        ), timeout=15,
    )
    check(bad_over.status_code == 400, "Penerimaan melebihi outstanding PO ditolak")
    check(abs(stock(admin, item["id"], wh_a["id"]) - 4) < 1e-6, "Over-receipt gagal tidak mengubah stok")

    # Warehouse access and division access are server-side, not only source-picker UI.
    wh_email = f"wh-{run}@example.test"
    cr = admin.post(
        f"{API}/users",
        json={
            "email": wh_email, "password": "Warehouse!123", "name": "Warehouse Restricted",
            "role": "warehouse", "scope": "limited", "divisions": [div_a["id"]],
            "warehouses": [wh_a2["id"]], "permissions": ["view", "create", "edit", "delete"],
        }, timeout=15,
    )
    check(cr.status_code == 200, "User gudang terbatas dapat dibuat")
    wh_user = login(wh_email, "Warehouse!123")
    bad_wh = wh_user.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=1,
        ), timeout=15,
    )
    check(bad_wh.status_code == 403, "User tidak dapat menerima ke gudang di luar kewenangannya")

    other_email = f"other-{run}@example.test"
    cr2 = admin.post(
        f"{API}/users",
        json={
            "email": other_email, "password": "OtherDiv!123", "name": "Other Division",
            "role": "warehouse", "scope": "limited", "divisions": [div_b["id"]],
            "warehouses": [], "permissions": ["view", "create", "edit", "delete"],
        }, timeout=15,
    )
    check(cr2.status_code == 200, "User divisi lain dapat dibuat")
    other = login(other_email, "OtherDiv!123")
    check(all(x.get("id") != do1_id for x in other.get(f"{API}/do", timeout=15).json()), "Daftar DO tidak membocorkan divisi lain")
    check(other.get(f"{API}/do/{do1_id}", timeout=15).status_code == 403, "Detail DO divisi lain diblokir")
    cross_create = other.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=1,
        ), timeout=15,
    )
    check(cross_create.status_code == 403, "Penerimaan PO divisi lain diblokir di backend")

    # Complete the PO with second receipt.
    do2 = admin.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=6,
        ), timeout=15,
    )
    check(do2.status_code == 200, "DO kedua 6 dapat menyelesaikan PO")
    do2_id = do2.json()["id"]
    check(admin.get(f"{API}/po/{po_id}", timeout=15).json().get("status") == "Fully Received", "PO menjadi Fully Received")
    check(abs(stock(admin, item["id"], wh_a["id"]) - 10) < 1e-6, "Stok menjadi 10 setelah penerimaan penuh")

    blocked_full = admin.post(
        f"{API}/do",
        json=do_payload(
            supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
            po_line_id=po_line_id, item_id=item["id"], qty=1,
        ), timeout=15,
    )
    check(blocked_full.status_code == 409, "PO Fully Received tidak dapat dibuatkan DO baru")

    # Edit existing DO is allowed even while the source PO is Fully Received; reversal + repost
    # must return PO and stock to the mathematically correct state.
    edit_body = do_payload(
        supplier_id=supplier_a["id"], warehouse_id=wh_a["id"], po_id=po_id,
        po_line_id=po_line_id, item_id=item["id"], qty=3,
    )
    edit = admin.put(f"{API}/transactions/do/{do1_id}", json=edit_body, timeout=15)
    check(edit.status_code == 200, "DO existing dapat direvisi dari 4 menjadi 3")
    check(abs(stock(admin, item["id"], wh_a["id"]) - 9) < 1e-6, "Edit DO melakukan reversal dan repost stok menjadi 9")
    check(admin.get(f"{API}/po/{po_id}", timeout=15).json().get("status") == "Partially Received", "Edit DO mengembalikan PO menjadi Partially Received")

    # Delete must reverse stock and release PO outstanding.
    dele2 = admin.delete(f"{API}/transactions/do/{do2_id}", timeout=15)
    check(dele2.status_code == 200, "DO kedua dapat dihapus dengan reversal")
    check(abs(stock(admin, item["id"], wh_a["id"]) - 3) < 1e-6, "Hapus DO kedua mengembalikan stok menjadi 3")
    check(admin.get(f"{API}/po/{po_id}", timeout=15).json().get("status") == "Partially Received", "PO tetap Partial selama DO pertama masih ada")

    dele1 = admin.delete(f"{API}/transactions/do/{do1_id}", timeout=15)
    check(dele1.status_code == 200, "DO pertama dapat dihapus dengan reversal")
    check(abs(stock(admin, item["id"], wh_a["id"])) < 1e-6, "Seluruh DO dihapus mengembalikan stok menjadi 0")
    check(admin.get(f"{API}/po/{po_id}", timeout=15).json().get("status") == "Approved", "Seluruh DO dihapus mengembalikan PO menjadi Approved")

    print("\nRESULT: PASS - DO source, supplier, division, warehouse, outstanding, edit/delete reversal konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
