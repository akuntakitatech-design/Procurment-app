"""Disposable full E2E test for procurement + warehouse lifecycle.

Business flow:
MRO -> RO -> PO -> DO -> Inventory -> MI -> Traceability/Report.
Warehouse flow:
Opening adjustment -> Transfer -> Loan -> Return -> Damaged adjustment -> Stock Opname.
"""
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

API = os.environ.get("TEST_API_URL", "http://full-e2e-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(90):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend full E2E tidak siap")


def login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    check(r.status_code == 200, "Login admin full E2E berhasil")
    token = r.json().get("token")
    check(bool(token), "Token admin tersedia")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=payload, timeout=20)
    if r.status_code != 200:
        raise AssertionError(f"Gagal membuat master {name}: HTTP {r.status_code} {r.text}")
    print(f"PASS: Master {name} berhasil dibuat")
    return r.json()


def position(s, item_id, warehouse_id):
    r = s.get(f"{API}/inventory/position", timeout=20)
    check(r.status_code == 200, "Inventory position dapat dibaca")
    for row in r.json():
        if str(row.get("item_id")) == str(item_id) and str(row.get("warehouse_id")) == str(warehouse_id):
            return float(row.get("on_hand", row.get("current_stock", row.get("stock", 0))) or 0)
    return 0.0


def near(a, b):
    return abs(float(a) - float(b)) < 1e-6


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]
    today = datetime.now(timezone.utc).date().isoformat()

    div = master(s, "divisions", {"code": f"E2D{run}", "name": f"Divisi E2E {run}"})
    wh_main = master(s, "warehouses", {"code": f"E2M{run}", "name": f"Gudang Utama E2E {run}", "division_id": div["id"]})
    wh_site = master(s, "warehouses", {"code": f"E2S{run}", "name": f"Gudang Site E2E {run}", "division_id": div["id"]})
    supplier = master(s, "suppliers", {"code": f"E2SUP{run}", "name": f"Supplier E2E {run}"})
    unit = master(s, "units", {"code": f"E2U{run}", "name": f"Unit E2E {run}", "division_id": div["id"]})
    item_business = master(s, "items", {"code": f"E2B{run}", "name": f"Barang Business E2E {run}", "unit": "pcs", "division_id": div["id"]})
    item_stock = master(s, "items", {"code": f"E2W{run}", "name": f"Barang Warehouse E2E {run}", "unit": "pcs", "division_id": div["id"]})

    print("\n== BUSINESS E2E: MRO -> RO -> PO -> DO -> MI -> REPORT ==")
    mro_r = s.post(f"{API}/mro", json={
        "date": today, "need_date": today, "division_id": div["id"],
        "default_warehouse_id": wh_main["id"], "requester": "E2E Tester",
        "department": "Workshop", "notes": f"FULL-E2E-{run}",
        "lines": [{"item_id": item_business["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_main["id"], "unit_id": unit["id"]}],
    }, timeout=20)
    check(mro_r.status_code == 200, "MRO 5 pcs berhasil dibuat")
    mro = mro_r.json(); mro_line = mro["lines"][0]
    sub = s.post(f"{API}/mro/{mro['id']}/submit", timeout=20)
    check(sub.status_code == 200, "MRO berhasil disubmit")

    ro_r = s.post(f"{API}/ro", json={
        "date": today, "division_id": div["id"], "default_warehouse_id": wh_main["id"],
        "requester": "E2E Tester", "notes": f"FULL-E2E-{run}",
        "lines": [{
            "item_id": item_business["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_main["id"], "unit_id": unit["id"],
            "sources": [{"mro_id": mro["id"], "line_id": mro_line["id"], "qty": 5, "base_qty": 5}],
        }],
    }, timeout=20)
    check(ro_r.status_code == 200, "RO 5 pcs dari MRO berhasil dibuat")
    ro = ro_r.json(); ro_line = ro["lines"][0]
    check(s.post(f"{API}/ro/{ro['id']}/submit", timeout=20).status_code == 200, "RO berhasil disubmit")

    po_r = s.post(f"{API}/po", json={
        "date": today, "division_id": div["id"], "supplier_id": supplier["id"],
        "default_warehouse_id": wh_main["id"], "currency": "IDR", "notes": f"FULL-E2E-{run}",
        "lines": [{
            "item_id": item_business["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh_main["id"],
            "unit_id": unit["id"], "price": 100000, "discount": 0, "tax": 0,
            "sources": [{"ro_id": ro["id"], "line_id": ro_line["id"], "qty": 5, "base_qty": 5}],
        }],
    }, timeout=20)
    check(po_r.status_code == 200, "PO 5 pcs dari RO berhasil dibuat")
    po = po_r.json(); po_line = po["lines"][0]
    po_sub = s.post(f"{API}/po/{po['id']}/submit", timeout=20)
    check(po_sub.status_code == 200 and po_sub.json().get("status") == "Approved", "PO berhasil Approved")

    do_r = s.post(f"{API}/do", json={
        "date": today, "supplier_id": supplier["id"], "default_warehouse_id": wh_main["id"],
        "receiver": "E2E Tester", "notes": f"FULL-E2E-{run}",
        "lines": [{
            "po_id": po["id"], "po_line_id": po_line["id"], "item_id": item_business["id"],
            "qty": 5, "unit": "pcs", "warehouse_id": wh_main["id"], "unit_id": unit["id"], "condition": "Baik",
        }],
    }, timeout=20)
    check(do_r.status_code == 200, "DO 5 pcs berhasil diposting")
    po_after = s.get(f"{API}/po/{po['id']}", timeout=20)
    check(po_after.status_code == 200 and po_after.json().get("status") == "Fully Received", "PO menjadi Fully Received")
    check(near(position(s, item_business["id"], wh_main["id"]), 5), "Stok setelah DO menjadi 5 pcs")

    mi_r = s.post(f"{API}/mi", json={
        "date": today, "division_id": div["id"], "default_warehouse_id": wh_main["id"],
        "receiver": "E2E Tester", "department": "Workshop", "source_type": "MRO", "notes": f"FULL-E2E-{run}",
        "lines": [{
            "mro_id": mro["id"], "mro_line_id": mro_line["id"], "item_id": item_business["id"],
            "qty": 5, "unit": "pcs", "warehouse_id": wh_main["id"], "unit_id": unit["id"],
        }],
    }, timeout=20)
    check(mi_r.status_code == 200, "MI 5 pcs dari MRO berhasil diposting")
    mi = mi_r.json()
    check(near(position(s, item_business["id"], wh_main["id"]), 0), "Stok setelah MI kembali 0 pcs")

    trace = s.get(f"{API}/traceability/{mro['id']}", timeout=20)
    check(trace.status_code == 200, "Traceability MRO dapat dibuka")
    report = s.get(f"{API}/reports/mro-traceability", timeout=30)
    check(report.status_code == 200, "Report MRO traceability dapat dibaca")
    row = next((x for x in report.json() if x.get("mro_id") == mro["id"]), None)
    check(row is not None, "MRO muncul pada report traceability")
    check(float(row.get("qty_ro") or 0) >= 5, "Report mencatat Qty RO")
    check(float(row.get("qty_po") or 0) >= 5, "Report mencatat Qty PO")
    check(float(row.get("qty_received") or 0) >= 5, "Report mencatat Qty DO")
    check(float(row.get("qty_mi") or 0) >= 5, "Report mencatat Qty MI")
    search = s.get(f"{API}/search", params={"q": mro.get("no")}, timeout=20)
    check(search.status_code == 200 and any(x.get("id") == mro["id"] for x in search.json()), "MRO dapat ditemukan lewat global search")
    check(mi.get("id"), "Dokumen MI memiliki ID valid")

    print("\n== WAREHOUSE E2E: TRANSFER -> LOAN -> RETURN -> ADJUSTMENT -> OPNAME ==")
    seed = s.post(f"{API}/adjustments", json={
        "date": today, "warehouse_id": wh_main["id"], "division_id": div["id"],
        "adj_type": "Saldo E2E", "reason": "Seed disposable E2E",
        "lines": [{"item_id": item_stock["id"], "adjustment": 20, "reason": "Saldo awal E2E"}],
    }, timeout=20)
    check(seed.status_code == 200, "Saldo awal warehouse 20 pcs berhasil dibuat")
    check(near(position(s, item_stock["id"], wh_main["id"]), 20), "Stok awal gudang utama 20 pcs")

    tr = s.post(f"{API}/transfers", json={
        "date": today, "from_warehouse_id": wh_main["id"], "to_warehouse_id": wh_site["id"],
        "notes": f"FULL-E2E-{run}",
        "lines": [{"item_id": item_stock["id"], "qty": 5, "unit": "pcs"}],
    }, timeout=20)
    check(tr.status_code == 200, "Transfer 5 pcs utama -> site berhasil")
    check(near(position(s, item_stock["id"], wh_main["id"]), 15), "Stok utama setelah transfer 15")
    check(near(position(s, item_stock["id"], wh_site["id"]), 5), "Stok site setelah transfer 5")

    loan_r = s.post(f"{API}/loans", json={
        "date": today, "from_warehouse_id": wh_main["id"], "to_warehouse_id": wh_site["id"],
        "requester": "E2E Tester", "notes": f"FULL-E2E-{run}",
        "lines": [{"item_id": item_stock["id"], "qty": 4, "unit": "pcs"}],
    }, timeout=20)
    check(loan_r.status_code == 200, "Loan 4 pcs utama -> site berhasil")
    loan = loan_r.json(); loan_line = loan["lines"][0]
    check(near(position(s, item_stock["id"], wh_main["id"]), 11), "Stok utama setelah loan 11")
    check(near(position(s, item_stock["id"], wh_site["id"]), 9), "Stok site setelah loan 9")

    ret = s.post(f"{API}/loans/{loan['id']}/return", json={
        "date": today, "notes": "Full return E2E",
        "lines": [{"loan_line_id": loan_line["id"], "qty": 4}],
    }, timeout=20)
    check(ret.status_code == 200, "Return loan 4 pcs berhasil")
    check(ret.json().get("status") == "Completed", "Loan berstatus Completed setelah full return")
    check(near(position(s, item_stock["id"], wh_main["id"]), 15), "Stok utama setelah return 15")
    check(near(position(s, item_stock["id"], wh_site["id"]), 5), "Stok site setelah return 5")

    damaged = s.post(f"{API}/adjustments", json={
        "date": today, "warehouse_id": wh_site["id"], "division_id": div["id"],
        "adj_type": "Barang Rusak", "reason": "Rusak E2E",
        "lines": [{"item_id": item_stock["id"], "adjustment": -1, "reason": "Barang rusak E2E"}],
    }, timeout=20)
    check(damaged.status_code == 200, "Adjustment rusak -1 berhasil")
    check(near(position(s, item_stock["id"], wh_site["id"]), 4), "Stok site setelah barang rusak menjadi 4")

    opn_r = s.post(f"{API}/opname", json={
        "date": today, "warehouse_id": wh_site["id"], "division_id": div["id"],
        "mode": "live", "scope": "division", "notes": f"FULL-E2E-{run}",
    }, timeout=20)
    check(opn_r.status_code == 200, "Stock opname site berhasil dibuat")
    opn = opn_r.json()
    count_lines = []
    found = False
    for line in opn.get("lines") or []:
        counted = float(line.get("snapshot") or 0)
        if line.get("item_id") == item_stock["id"]:
            counted = 3
            found = True
        count_lines.append({"line_id": line["id"], "counted": counted})
    check(found, "Barang warehouse masuk snapshot opname")
    counted = s.put(f"{API}/opname/{opn['id']}/count", json={"status": "Review", "lines": count_lines}, timeout=20)
    check(counted.status_code == 200, "Hasil hitung opname berhasil disimpan")
    submitted = s.post(f"{API}/opname/{opn['id']}/submit", timeout=20)
    check(submitted.status_code == 200, "Stock opname berhasil disubmit")
    posted = s.post(f"{API}/opname/{opn['id']}/post", timeout=20)
    check(posted.status_code == 200 and posted.json().get("status") == "Posted", "Stock opname berhasil diposting")
    check(near(position(s, item_stock["id"], wh_site["id"]), 3), "Stok site setelah opname menjadi 3")
    check(near(position(s, item_stock["id"], wh_main["id"]), 15), "Stok utama tetap konsisten 15")

    ledger = s.get(f"{API}/inventory/ledger", timeout=20)
    check(ledger.status_code == 200, "Stock ledger akhir dapat dibaca")
    doc_types = {x.get("doc_type") for x in ledger.json() if x.get("item_id") == item_stock["id"]}
    required = {"Transfer Out", "Transfer In", "Loan Out", "Loan In", "Loan Return Out", "Loan Return In", "Stock Adjustment", "Stock Opname Adjustment"}
    check(required.issubset(doc_types), "Ledger mencatat seluruh lifecycle warehouse")

    print("\nRESULT: PASS - Full E2E procurement, inventory, report, transfer, loan/return, adjustment, dan opname konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
