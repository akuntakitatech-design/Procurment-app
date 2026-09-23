"""Disposable integration test for core master data integrity and delete guards."""
import os
import sys
import time
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://master-data-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


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


def create_master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    check(r.status_code == 200, f"Master {name} berhasil dibuat")
    return r.json()


def list_master(s, name, **params):
    r = s.get(f"{API}/master/{name}", params=params, timeout=15)
    check(r.status_code == 200, f"Master {name} dapat dibaca")
    return r.json()


def update_master(s, name, rid, payload):
    return s.put(f"{API}/master/{name}/{rid}", json=payload, timeout=15)


def delete_master(s, name, rid):
    return s.delete(f"{API}/master/{name}/{rid}", timeout=15)


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8].upper()

    prefixes = {
        "items": "BRG-", "warehouses": "GDG-", "projects": "PRJ-", "units": "UNT-",
        "suppliers": "SUP-", "supplier_categories": "KSP-", "divisions": "DIV-",
        "uoms": "SAT-", "item_categories": "KAT-", "taxes": "PJK-",
    }
    for name, prefix in prefixes.items():
        r = s.get(f"{API}/master-code/{name}/preview", timeout=15)
        check(r.status_code == 200 and str(r.json().get("code", "")).startswith(prefix), f"Preview kode otomatis {name} valid")

    pcs = create_master(s, "uoms", {"code": f"PCS-{run}", "name": "Pieces", "symbol": "pcs"})
    box = create_master(s, "uoms", {"code": f"BOX-{run}", "name": "Box", "symbol": "box"})
    cat = create_master(s, "item_categories", {"code": f"CAT-{run}", "name": f"Sparepart {run}"})
    tax = create_master(s, "taxes", {"code": f"VAT-{run}", "name": f"PPN Test {run}", "rate": 11})
    supcat = create_master(s, "supplier_categories", {"code": f"SC-{run}", "name": f"Vendor Parts {run}"})
    div = create_master(s, "divisions", {"code": f"DIV-{run}", "name": f"Divisi Test {run}"})
    wh = create_master(s, "warehouses", {"code": f"WH-{run}", "name": f"Gudang Test {run}", "division_id": div["id"]})
    project = create_master(s, "projects", {"code": f"PRJ-{run}", "name": f"Project Test {run}"})
    unit = create_master(s, "units", {"code": f"UNT-{run}", "name": f"Unit Test {run}", "division_id": div["id"]})

    item = create_master(s, "items", {
        "code": f"ITEM-{run}", "name": f"Bearing Master {run}", "division_id": div["id"],
        "category_id": cat["id"], "base_uom_id": pcs["id"],
        "uoms": [{"uom_id": box["id"], "factor": 12}],
    })
    check(item.get("unit") == "pcs", "Barang menyimpan satuan dasar dari UOM")
    check(len(item.get("uoms") or []) == 2, "Barang menyimpan UOM dasar dan alternatif")

    supplier = create_master(s, "suppliers", {
        "code": f"SUP-{run}", "name": f"Supplier Test {run}",
        "supplier_category_id": supcat["id"], "default_tax_id": tax["id"],
        "supplied_category_ids": [cat["id"]], "lead_time_days": 3, "min_order": 100000,
        "contacts": [
            {"name": "PIC Satu", "phone": "0800000001", "is_primary": True},
            {"name": "PIC Dua", "phone": "0800000002", "is_primary": True},
        ],
        "banks": [
            {"bank_name": "Bank A", "account_no": "001", "account_name": "Supplier", "is_primary": True},
            {"bank_name": "Bank B", "account_no": "002", "account_name": "Supplier", "is_primary": True},
        ],
    })
    check(sum(1 for x in supplier.get("contacts", []) if x.get("is_primary")) == 1, "Supplier hanya memiliki satu kontak utama")
    check(sum(1 for x in supplier.get("banks", []) if x.get("is_primary")) == 1, "Supplier hanya memiliki satu rekening utama")

    dup = s.post(f"{API}/master/projects", json={"code": project["code"], "name": "Duplikat"}, timeout=15)
    check(dup.status_code == 400, "Kode master duplikat saat create ditolak")

    p2 = create_master(s, "projects", {"code": f"PRJ2-{run}", "name": f"Project Kedua {run}"})
    dup_edit = update_master(s, "projects", p2["id"], {"code": project["code"]})
    check(dup_edit.status_code == 400, "Kode master duplikat saat edit ditolak")
    ok_edit = update_master(s, "projects", p2["id"], {"code": f"PRJ2E-{run}", "name": f"Project Kedua Edited {run}"})
    check(ok_edit.status_code == 200 and ok_edit.json().get("code") == f"PRJ2E-{run}", "Kode master dapat diedit dengan ID tetap")

    bad_tax = s.post(f"{API}/master/taxes", json={"code": f"NEG-{run}", "name": "Tax Negatif", "rate": -1}, timeout=15)
    check(bad_tax.status_code == 400, "Tarif pajak negatif ditolak")
    bad_item = s.post(f"{API}/master/items", json={
        "code": f"BADITEM-{run}", "name": "Bad UOM", "division_id": div["id"],
        "base_uom_id": pcs["id"], "uoms": [{"uom_id": box["id"], "factor": 0}],
    }, timeout=15)
    check(bad_item.status_code == 400, "Faktor konversi UOM nol ditolak")
    bad_supplier = s.post(f"{API}/master/suppliers", json={
        "code": f"BADSUP-{run}", "name": "Bad Supplier", "lead_time_days": -1,
    }, timeout=15)
    check(bad_supplier.status_code == 400, "Lead time supplier negatif ditolak")

    temp_wh = create_master(s, "warehouses", {"code": f"TMPWH-{run}", "name": f"Gudang Nonaktif {run}"})
    deact = update_master(s, "warehouses", temp_wh["id"], {"is_active": False})
    check(deact.status_code == 200 and deact.json().get("is_active") is False, "Master dapat dinonaktifkan tanpa dihapus")
    active_rows = list_master(s, "warehouses", active_only="true")
    all_rows = list_master(s, "warehouses")
    check(not any(x.get("id") == temp_wh["id"] for x in active_rows), "Master nonaktif tidak muncul pada active_only")
    check(any(x.get("id") == temp_wh["id"] for x in all_rows), "Master nonaktif tetap tersimpan untuk histori")
    check(delete_master(s, "warehouses", temp_wh["id"]).status_code == 200, "Master unused dapat dihapus permanen")

    search_rows = list_master(s, "items", q=f"Bearing Master {run}")
    check(any(x.get("id") == item["id"] for x in search_rows), "Pencarian master barang bekerja")

    mro = s.post(f"{API}/mro", json={
        "date": "2026-09-20", "division_id": div["id"], "requester": "Master Tester",
        "notes": "MASTER DATA LINE REFERENCE TEST",
        "lines": [{
            "item_id": item["id"], "qty": 1, "uom_id": box["id"], "unit": "box",
            "warehouse_id": wh["id"], "project_id": project["id"], "unit_id": unit["id"],
        }],
    }, timeout=15)
    check(mro.status_code == 200, "MRO line-only reference berhasil dibuat")

    # These four are intentionally referenced only from the MRO line (not default header fields).
    for name, rec, label in [
        ("items", item, "Barang"),
        ("warehouses", wh, "Gudang"),
        ("projects", project, "Proyek"),
        ("units", unit, "Unit/Aset"),
    ]:
        blocked = delete_master(s, name, rec["id"])
        check(blocked.status_code == 409, f"{label} yang sudah dipakai baris transaksi tidak dapat dihapus")

    po = s.post(f"{API}/po", json={
        "date": "2026-09-20", "supplier_id": supplier["id"], "division_id": div["id"],
        "currency": "IDR",
        "lines": [{
            "item_id": item["id"], "qty": 1, "uom_id": pcs["id"], "unit": "pcs",
            "warehouse_id": wh["id"], "price": 1000, "tax_id": tax["id"], "tax": 11,
        }],
    }, timeout=15)
    check(po.status_code == 200, "PO master-reference berhasil dibuat")
    check(delete_master(s, "suppliers", supplier["id"]).status_code == 409, "Supplier yang dipakai PO tidak dapat dihapus")

    for name, rec, label in [
        ("uoms", pcs, "UOM dasar"),
        ("uoms", box, "UOM alternatif"),
        ("item_categories", cat, "Kategori barang"),
        ("taxes", tax, "Pajak"),
        ("supplier_categories", supcat, "Kategori supplier"),
        ("divisions", div, "Divisi"),
    ]:
        check(delete_master(s, name, rec["id"]).status_code == 409, f"{label} yang masih direferensikan tidak dapat dihapus")

    # Editing the human-readable code is allowed even after use because relations use stable IDs.
    edit_used = update_master(s, "projects", project["id"], {"code": f"PRJ-USED-EDIT-{run}"})
    check(edit_used.status_code == 200, "Kode master yang sudah dipakai dapat diedit tanpa memutus ID referensi")
    check(delete_master(s, "projects", project["id"]).status_code == 409, "Setelah edit kode, guard histori tetap bekerja berdasarkan ID")

    unused = create_master(s, "projects", {"name": f"Auto Code Unused {run}"})
    check(str(unused.get("code", "")).startswith("PRJ-"), "Create tanpa kode menghasilkan kode otomatis")
    check(delete_master(s, "projects", unused["id"]).status_code == 200, "Master auto-code unused dapat dihapus")

    print("\nRESULT: PASS - master data, validasi, kode, nonaktif, dan delete guard konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
