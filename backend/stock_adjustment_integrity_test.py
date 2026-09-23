"""Disposable integration test for stock adjustment / damaged stock integrity."""
import os
import sys
import time
import uuid
import requests

API = os.environ.get("TEST_API_URL", "http://stock-adjustment-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


def approx(a, b):
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


def stock(s, item_id, wh_id):
    r = s.get(f"{API}/item-warehouse", params={"warehouse_id": wh_id, "item_id": item_id}, timeout=15)
    check(r.status_code == 200, "Posisi stok dapat dibaca")
    rows = r.json()
    return float(rows[0].get("current_stock", 0)) if rows else 0.0


def adjustments(s):
    r = s.get(f"{API}/adjustments", timeout=15)
    check(r.status_code == 200, "Daftar adjustment dapat dibaca")
    return r.json()


def detail(s, did):
    r = s.get(f"{API}/adjustments/{did}", timeout=15)
    check(r.status_code == 200, "Detail adjustment dapat dibaca")
    return r.json()


def adj_payload(wh, div, item, delta, kind="Barang Rusak", reason="Kerusakan fisik"):
    return {
        "date": "2026-09-20", "warehouse_id": wh, "division_id": div,
        "adj_type": kind, "reason": reason, "notes": "STOCK ADJUSTMENT INTEGRITY TEST",
        "lines": [{"item_id": item, "adjustment": delta, "reason": reason}],
    }


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]
    div = master(s, "divisions", {"code": f"ADJ{run}", "name": f"Adjustment {run}"})
    wh = master(s, "warehouses", {"code": f"ADW{run}", "name": f"Gudang Adjustment {run}", "division_id": div["id"]})
    item = master(s, "items", {"code": f"ADI{run}", "name": f"Filter Test {run}", "unit": "pcs", "division_id": div["id"]})

    opening = s.post(f"{API}/adjustments", json=adj_payload(wh["id"], div["id"], item["id"], 10, "Saldo Awal Test", "Opening"), timeout=15)
    check(opening.status_code == 200, "Saldo awal 10 berhasil dibuat")
    check(approx(stock(s, item["id"], wh["id"]), 10), "Saldo awal menghasilkan stok 10")

    count_before = len(adjustments(s))
    bad = s.post(f"{API}/adjustments", json=adj_payload(wh["id"], div["id"], item["id"], -11), timeout=15)
    check(bad.status_code == 400, "Adjustment rusak melebihi stok ditolak")
    check(len(adjustments(s)) == count_before, "Adjustment invalid tidak meninggalkan header orphan")
    check(approx(stock(s, item["id"], wh["id"]), 10), "Adjustment invalid tidak mengubah stok")

    damaged = s.post(f"{API}/adjustments", json=adj_payload(wh["id"], div["id"], item["id"], -3), timeout=15)
    check(damaged.status_code == 200, "Adjustment barang rusak -3 berhasil")
    did = damaged.json()["id"]
    d = detail(s, did)
    line = d["lines"][0]
    check(approx(line.get("before"), 10) and approx(line.get("adjustment"), -3) and approx(line.get("after"), 7), "Before/adjustment/after tercatat 10/-3/7")
    check(approx(stock(s, item["id"], wh["id"]), 7), "Barang rusak mengurangi stok menjadi 7")

    edit = s.put(f"{API}/transactions/adjustment/{did}", json=adj_payload(wh["id"], div["id"], item["id"], -5), timeout=15)
    check(edit.status_code == 200, "Edit adjustment -3 menjadi -5 berhasil")
    check(approx(stock(s, item["id"], wh["id"]), 5), "Edit adjustment melakukan reversal dan menghasilkan stok 5")

    bad_edit = s.put(f"{API}/transactions/adjustment/{did}", json=adj_payload(wh["id"], div["id"], item["id"], -11), timeout=15)
    check(bad_edit.status_code == 400, "Edit adjustment yang akan membuat stok minus ditolak")
    check(approx(stock(s, item["id"], wh["id"]), 5), "Edit invalid tidak mengubah stok")
    check(approx(detail(s, did)["lines"][0].get("adjustment"), -5), "Edit invalid tidak mengubah transaksi existing")

    dele = s.delete(f"{API}/transactions/adjustment/{did}", timeout=15)
    check(dele.status_code == 200, "Delete adjustment rusak berhasil dengan reversal")
    check(approx(stock(s, item["id"], wh["id"]), 10), "Delete adjustment rusak mengembalikan stok ke 10")

    plus = s.post(f"{API}/adjustments", json=adj_payload(wh["id"], div["id"], item["id"], 5, "Koreksi Tambah", "Koreksi stok"), timeout=15)
    check(plus.status_code == 200, "Adjustment tambah +5 berhasil")
    plus_id = plus.json()["id"]
    check(approx(stock(s, item["id"], wh["id"]), 15), "Adjustment tambah menghasilkan stok 15")

    mi = s.post(f"{API}/mi", json={
        "date": "2026-09-20", "division_id": div["id"], "default_warehouse_id": wh["id"],
        "receiver": "Adjustment Tester", "department": "Workshop", "source_type": "Direct",
        "notes": "CONSUME POSITIVE ADJUSTMENT",
        "lines": [{"item_id": item["id"], "qty": 12, "unit": "pcs", "warehouse_id": wh["id"], "notes": "consume"}],
    }, timeout=15)
    check(mi.status_code == 200, "MI 12 berhasil untuk menguji reversal blocker")
    mi_id = mi.json()["id"]
    check(approx(stock(s, item["id"], wh["id"]), 3), "MI menurunkan stok menjadi 3")

    cap = s.get(f"{API}/transactions/adjustment/{plus_id}/capability", timeout=15)
    check(cap.status_code == 200 and cap.json().get("can_delete") is False, "Adjustment tambah yang sudah terpakai diblokir untuk delete")
    blocked = s.delete(f"{API}/transactions/adjustment/{plus_id}", timeout=15)
    check(blocked.status_code == 409, "Delete adjustment tambah yang akan membuat stok minus ditolak")

    check(s.delete(f"{API}/transactions/mi/{mi_id}", timeout=15).status_code == 200, "MI test dapat direversal")
    check(approx(stock(s, item["id"], wh["id"]), 15), "Reversal MI mengembalikan stok ke 15")
    check(s.delete(f"{API}/transactions/adjustment/{plus_id}", timeout=15).status_code == 200, "Adjustment tambah dapat dihapus setelah stok tersedia")
    check(approx(stock(s, item["id"], wh["id"]), 10), "Reversal adjustment tambah mengembalikan stok ke 10")

    print("\nRESULT: PASS - adjustment barang rusak dan reversal stok konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
