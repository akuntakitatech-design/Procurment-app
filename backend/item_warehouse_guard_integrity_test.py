"""Disposable integration test for item-warehouse stock mutation guard."""
import os
import sys
import time
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://item-warehouse-guard-api:8000/api").rstrip("/")
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
    raise RuntimeError("Backend item-warehouse guard test tidak siap")


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


def row(s, item_id, warehouse_id):
    r = s.get(f"{API}/item-warehouse", params={"item_id": item_id, "warehouse_id": warehouse_id}, timeout=15)
    check(r.status_code == 200, "Item-warehouse dapat dibaca")
    rows = r.json()
    check(len(rows) == 1, "Item-warehouse target ditemukan tepat satu")
    return rows[0]


def ledger_count(s, item_id, warehouse_id):
    r = s.get(f"{API}/inventory/ledger", params={"item_id": item_id, "warehouse_id": warehouse_id, "limit": 100}, timeout=15)
    check(r.status_code == 200, "Ledger stok dapat dibaca")
    return len(r.json())


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]

    div = master(s, "divisions", {"code": f"IWD{run}", "name": f"Divisi IW {run}"})
    wh = master(s, "warehouses", {"code": f"IWW{run}", "name": f"Gudang IW {run}", "division_id": div["id"]})
    item = master(s, "items", {"code": f"IWI{run}", "name": f"Barang IW {run}", "unit": "pcs", "division_id": div["id"]})

    seed = s.post(f"{API}/adjustments", json={
        "date": "2026-09-21", "warehouse_id": wh["id"], "division_id": div["id"],
        "adj_type": "Saldo Test", "reason": "Seed item-warehouse guard",
        "lines": [{"item_id": item["id"], "adjustment": 20, "reason": "Saldo awal"}],
    }, timeout=15)
    check(seed.status_code == 200, "Saldo awal 20 dibuat melalui ledger")
    before = row(s, item["id"], wh["id"])
    check(near(before.get("current_stock", 0), 20), "Stok awal item-warehouse = 20")
    before_ledger = ledger_count(s, item["id"], wh["id"])

    attack = s.post(f"{API}/item-warehouse", json={
        "item_id": item["id"], "warehouse_id": wh["id"],
        "min_stock": 7, "max_stock": 70, "current_stock": 999999,
    }, timeout=15)
    check(attack.status_code == 200, "Update konfigurasi min/max tetap diizinkan")
    after = row(s, item["id"], wh["id"])
    check(near(after.get("current_stock", 0), 20), "current_stock 999999 diabaikan; stok tetap 20")
    check(near(after.get("min_stock", 0), 7) and near(after.get("max_stock", 0), 70), "Min/max stock tetap dapat diperbarui")
    check(ledger_count(s, item["id"], wh["id"]) == before_ledger, "Update konfigurasi tidak membuat mutasi ledger")

    attack_negative = s.post(f"{API}/item-warehouse", json={
        "item_id": item["id"], "warehouse_id": wh["id"],
        "min_stock": 8, "max_stock": 80, "current_stock": -500,
    }, timeout=15)
    check(attack_negative.status_code == 200, "Percobaan current_stock negatif tidak merusak konfigurasi")
    final = row(s, item["id"], wh["id"])
    check(near(final.get("current_stock", 0), 20), "current_stock negatif juga diabaikan; stok tetap 20")
    check(near(final.get("min_stock", 0), 8) and near(final.get("max_stock", 0), 80), "Konfigurasi terakhir min/max tersimpan")

    print("\nRESULT: PASS - Item-warehouse hanya mengubah konfigurasi min/max; stok fisik tetap ledger-controlled.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
