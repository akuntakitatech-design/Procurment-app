"""Disposable integrity test for Loan/Return with alternate UOM conversion."""
import os
import sys
import time
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://loan-return-uom-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


def near(a, b):
    return abs(float(a) - float(b)) < 1e-6


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend test tidak siap")


def login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    check(r.status_code == 200, "Login admin berhasil")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    check(r.status_code == 200, f"Master {name} berhasil dibuat")
    return r.json()


def stock(s, item_id, warehouse_id):
    r = s.get(f"{API}/item-warehouse", params={"warehouse_id": warehouse_id, "item_id": item_id}, timeout=15)
    check(r.status_code == 200, "Posisi stok dapat dibaca")
    rows = r.json()
    return float(rows[0].get("current_stock", 0)) if rows else 0.0


def loan_detail(s, loan_id):
    r = s.get(f"{API}/loans/{loan_id}", timeout=15)
    check(r.status_code == 200, "Detail loan dapat dibaca")
    return r.json()


def returns(s, loan_id):
    r = s.get(f"{API}/loans/{loan_id}/returns", timeout=15)
    check(r.status_code == 200, "Daftar return dapat dibaca")
    return r.json()


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8].upper()

    pcs = master(s, "uoms", {"code": f"PCS-{run}", "name": "Pieces", "symbol": "pcs"})
    box = master(s, "uoms", {"code": f"BOX-{run}", "name": "Box", "symbol": "box"})
    div = master(s, "divisions", {"code": f"DU{run}", "name": f"Divisi UOM {run}"})
    wh_a = master(s, "warehouses", {"code": f"UA{run}", "name": f"Gudang A {run}", "division_id": div["id"]})
    wh_b = master(s, "warehouses", {"code": f"UB{run}", "name": f"Gudang B {run}", "division_id": div["id"]})
    item = master(s, "items", {
        "code": f"UI{run}",
        "name": f"Bearing UOM {run}",
        "division_id": div["id"],
        "base_uom_id": pcs["id"],
        "uoms": [{"uom_id": box["id"], "factor": 12}],
    })

    opening = s.post(f"{API}/adjustments", json={
        "date": "2026-09-21",
        "warehouse_id": wh_a["id"],
        "division_id": div["id"],
        "adj_type": "Saldo Awal Test",
        "reason": "Loan return UOM integrity",
        "lines": [{"item_id": item["id"], "adjustment": 120, "reason": "opening"}],
    }, timeout=15)
    check(opening.status_code == 200, "Saldo awal 120 pcs berhasil dibuat")

    loan_r = s.post(f"{API}/loans", json={
        "date": "2026-09-21",
        "from_warehouse_id": wh_a["id"],
        "to_warehouse_id": wh_b["id"],
        "requester": "UOM Tester",
        "notes": "2 box = 24 pcs",
        "lines": [{
            "item_id": item["id"],
            "qty": 2,
            "uom_id": box["id"],
            "unit": "box",
        }],
    }, timeout=15)
    check(loan_r.status_code == 200, "Loan 2 box berhasil dibuat")
    loan = loan_r.json()
    loan_id = loan["id"]
    detail = loan_detail(s, loan_id)
    line = detail["lines"][0]
    line_id = line["id"]
    check(near(line.get("qty"), 24), "Loan menyimpan qty dasar 24 pcs")
    check(near(line.get("conversion_factor"), 12), "Loan menyimpan faktor konversi 12")
    check(near(line.get("display_qty"), 2), "Loan menyimpan display qty 2 box")
    check(near(stock(s, item["id"], wh_a["id"]), 96), "Stok pemberi menjadi 96 pcs")
    check(near(stock(s, item["id"], wh_b["id"]), 24), "Stok peminjam menjadi 24 pcs")

    ret_r = s.post(f"{API}/loans/{loan_id}/return", json={
        "date": "2026-09-21",
        "notes": "Return 1 box",
        "lines": [{"loan_line_id": line_id, "qty": 1}],
    }, timeout=15)
    check(ret_r.status_code == 200, "Return 1 box berhasil")
    detail = loan_detail(s, loan_id)
    check(near(detail.get("outstanding_total"), 12), "Outstanding setelah return 1 box = 12 pcs")
    check(near(stock(s, item["id"], wh_a["id"]), 108), "Stok pemberi setelah return = 108 pcs")
    check(near(stock(s, item["id"], wh_b["id"]), 12), "Stok peminjam setelah return = 12 pcs")

    docs = returns(s, loan_id)
    check(len(docs) == 1, "Dokumen return tercatat")
    rid = docs[0]["id"]
    check(near(docs[0]["lines"][0].get("qty"), 12), "Return line menyimpan qty dasar 12 pcs")

    edit = s.put(f"{API}/loan-returns/{rid}", json={
        "date": "2026-09-21",
        "notes": "Edit return menjadi setengah box",
        "lines": [{"loan_line_id": line_id, "qty": 0.5}],
    }, timeout=15)
    check(edit.status_code == 200, "Edit return 1 box menjadi 0,5 box berhasil")
    detail = loan_detail(s, loan_id)
    check(near(detail.get("outstanding_total"), 18), "Edit return menyisakan outstanding 18 pcs")
    check(near(stock(s, item["id"], wh_a["id"]), 102), "Edit return menghasilkan stok pemberi 102 pcs")
    check(near(stock(s, item["id"], wh_b["id"]), 18), "Edit return menghasilkan stok peminjam 18 pcs")
    docs = returns(s, loan_id)
    check(near(docs[0]["lines"][0].get("qty"), 6), "Edit return menyimpan 0,5 box sebagai 6 pcs")

    delete = s.delete(f"{API}/loan-returns/{rid}", timeout=15)
    check(delete.status_code == 200, "Delete return UOM berhasil direversal")
    detail = loan_detail(s, loan_id)
    check(near(detail.get("outstanding_total"), 24), "Delete return mengembalikan outstanding 24 pcs")
    check(near(stock(s, item["id"], wh_a["id"]), 96), "Delete return mengembalikan stok pemberi 96 pcs")
    check(near(stock(s, item["id"], wh_b["id"]), 24), "Delete return mengembalikan stok peminjam 24 pcs")

    full = s.post(f"{API}/loans/{loan_id}/return", json={
        "date": "2026-09-21",
        "notes": "Full return 2 box",
        "lines": [{"loan_line_id": line_id, "qty": 2}],
    }, timeout=15)
    check(full.status_code == 200, "Full return 2 box berhasil")
    detail = loan_detail(s, loan_id)
    check(detail.get("status") == "Completed" and near(detail.get("outstanding_total"), 0), "Loan Completed setelah full return")
    check(near(stock(s, item["id"], wh_a["id"]), 120), "Full return mengembalikan stok pemberi 120 pcs")
    check(near(stock(s, item["id"], wh_b["id"]), 0), "Full return mengosongkan stok peminjam")

    print("\nRESULT: PASS - Loan/Return UOM alternatif konsisten dalam qty dasar, edit, delete, dan stok.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
