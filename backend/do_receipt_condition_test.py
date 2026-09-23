"""Disposable integration test for DO receipt conditions/discrepancies."""
import os
import sys
import time
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://do-cond-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "do-cond-admin@example.test")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "DoCondAdmin!123")


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


def login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    check(r.status_code == 200, "Login admin berhasil")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Gagal membuat master {name}: {r.status_code} {r.text}")
    return r.json()


def create_po(s, div, sup, wh, item, qty):
    r = s.post(f"{API}/po", json={
        "date": "2026-09-20", "division_id": div, "supplier_id": sup,
        "default_warehouse_id": wh, "currency": "IDR",
        "lines": [{"item_id": item, "qty": qty, "unit": "pcs", "warehouse_id": wh, "price": 1000}],
    }, timeout=15)
    check(r.status_code == 200, "PO kondisi dapat dibuat")
    doc = r.json()
    sr = s.post(f"{API}/po/{doc['id']}/submit", timeout=15)
    check(sr.status_code == 200 and sr.json().get("status") == "Approved", "PO kondisi menjadi Approved")
    return sr.json()


def do_payload(sup, wh, po, line, item, qty, condition, exception_qty=0):
    return {
        "date": "2026-09-20", "supplier_id": sup, "supplier_dn": "SJ-COND",
        "default_warehouse_id": wh, "receiver": "Condition Tester",
        "lines": [{
            "po_id": po, "po_line_id": line, "item_id": item, "qty": qty,
            "unit": "pcs", "warehouse_id": wh, "condition": condition,
            "exception_qty": exception_qty,
            "sources": [{"po_id": po, "line_id": line, "qty": qty, "base_qty": qty}],
        }],
    }


def stock(s, item, wh):
    rows = s.get(f"{API}/item-warehouse?warehouse_id={wh}&item_id={item}", timeout=15).json()
    return float(rows[0].get("current_stock", 0)) if rows else 0.0


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]
    div = master(s, "divisions", {"code": f"D{run}", "name": f"Divisi {run}"})
    wh = master(s, "warehouses", {"code": f"W{run}", "name": f"Gudang {run}", "division_id": div["id"]})
    sup = master(s, "suppliers", {"code": f"S{run}", "name": f"Supplier {run}"})
    item = master(s, "items", {"code": f"I{run}", "name": f"Item {run}", "unit": "pcs", "division_id": div["id"]})

    # Rusak: PO counts physical receipt, but damaged portion is not usable stock.
    po1 = create_po(s, div["id"], sup["id"], wh["id"], item["id"], 10)
    p1l = po1["lines"][0]["id"]
    bad = s.post(f"{API}/do", json=do_payload(sup["id"], wh["id"], po1["id"], p1l, item["id"], 10, "Rusak", 11), timeout=15)
    check(bad.status_code == 400, "Qty rusak melebihi qty terima ditolak")

    dr = s.post(f"{API}/do", json=do_payload(sup["id"], wh["id"], po1["id"], p1l, item["id"], 10, "Rusak", 2), timeout=15)
    check(dr.status_code == 200, "DO rusak dapat diposting")
    drj = dr.json(); did = drj["id"]
    check(abs(stock(s, item["id"], wh["id"]) - 8) < 1e-6, "DO 10 dengan rusak 2 menghasilkan stok usable 8")
    detail = s.get(f"{API}/do/{did}", timeout=15).json()
    line = detail["lines"][0]
    check(line.get("condition") == "Rusak" and abs(float(line.get("exception_qty", 0)) - 2) < 1e-6, "Detail menyimpan kondisi Rusak dan qty 2")
    check(abs(float(line.get("usable_qty", 0)) - 8) < 1e-6, "Detail menampilkan qty usable 8")
    check(detail.get("has_receipt_exception") is True, "Header DO menandai adanya exception")
    check(s.get(f"{API}/po/{po1['id']}", timeout=15).json().get("status") == "Fully Received", "PO tetap Fully Received secara fisik")

    # Edit must reverse both normal receipt and damaged hold, then post new state.
    edit = s.put(f"{API}/transactions/do/{did}", json=do_payload(sup["id"], wh["id"], po1["id"], p1l, item["id"], 8, "Rusak", 3), timeout=15)
    check(edit.status_code == 200, "DO rusak dapat direvisi")
    check(abs(stock(s, item["id"], wh["id"]) - 5) < 1e-6, "Edit menjadi terima 8 rusak 3 menghasilkan usable 5")
    check(s.get(f"{API}/po/{po1['id']}", timeout=15).json().get("status") == "Partially Received", "Edit qty receipt mengembalikan PO ke Partial")

    dele = s.delete(f"{API}/transactions/do/{did}", timeout=15)
    check(dele.status_code == 200, "DO rusak dapat dihapus dengan reversal")
    check(abs(stock(s, item["id"], wh["id"])) < 1e-6, "Hapus DO rusak mengembalikan stok ke 0")

    # Kurang: shortage is informational; only actual qty enters stock and PO stays outstanding.
    po2 = create_po(s, div["id"], sup["id"], wh["id"], item["id"], 10)
    p2l = po2["lines"][0]["id"]
    dk = s.post(f"{API}/do", json=do_payload(sup["id"], wh["id"], po2["id"], p2l, item["id"], 6, "Kurang", 4), timeout=15)
    check(dk.status_code == 200, "DO kurang dapat diposting")
    kd = s.get(f"{API}/do/{dk.json()['id']}", timeout=15).json()
    check(abs(float(kd["lines"][0].get("exception_qty", 0)) - 4) < 1e-6, "Qty kurang 4 tersimpan")
    check(s.get(f"{API}/po/{po2['id']}", timeout=15).json().get("status") == "Partially Received", "PO kurang tetap outstanding")

    # Lebih: excess is recorded but not accepted into PO/usable stock.
    po3 = create_po(s, div["id"], sup["id"], wh["id"], item["id"], 5)
    p3l = po3["lines"][0]["id"]
    before = stock(s, item["id"], wh["id"])
    dl = s.post(f"{API}/do", json=do_payload(sup["id"], wh["id"], po3["id"], p3l, item["id"], 5, "Lebih", 2), timeout=15)
    check(dl.status_code == 200, "DO lebih dapat mencatat excess")
    check(abs(stock(s, item["id"], wh["id"]) - (before + 5)) < 1e-6, "Qty lebih 2 tidak ikut masuk usable stock")
    ld = s.get(f"{API}/do/{dl.json()['id']}", timeout=15).json()
    check(abs(float(ld["lines"][0].get("exception_qty", 0)) - 2) < 1e-6, "Qty lebih 2 tersimpan sebagai exception")
    check(s.get(f"{API}/po/{po3['id']}", timeout=15).json().get("status") == "Fully Received", "PO lebih selesai hanya sebesar qty PO")

    print("\nRESULT: PASS - kondisi Baik/Rusak/Kurang/Lebih konsisten dengan stok dan PO.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
