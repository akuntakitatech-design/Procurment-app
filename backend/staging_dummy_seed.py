"""Seed realistic dummy master + transaction data into the private SaaS staging tenant.

Safety:
- refuses to run unless DB_NAME == procurement_saas_staging;
- requires ALLOW_STAGING_DUMMY_SEED=true;
- uses the normal authenticated HTTP API, so tenant isolation/business rules stay active;
- idempotent by master code and per-transaction marker; existing staging data is not wiped.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import requests


API = os.environ.get("SEED_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
EMAIL = os.environ.get("ADMIN_EMAIL", "").strip()
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MARK = "DEMO-STAGING-V1"
TODAY = date.today().isoformat()


def die(msg: str):
    raise RuntimeError(msg)


def check_safe():
    if os.environ.get("DB_NAME") != "procurement_saas_staging":
        die("REFUSED: dummy seed hanya boleh untuk DB_NAME=procurement_saas_staging")
    if os.environ.get("ALLOW_STAGING_DUMMY_SEED", "").lower() not in {"1", "true", "yes"}:
        die("REFUSED: set ALLOW_STAGING_DUMMY_SEED=true untuk staging dummy seed")
    if not EMAIL or not PASSWORD:
        die("ADMIN_EMAIL / ADMIN_PASSWORD staging tidak tersedia")


def req(s, method, path, *, ok=(200,), **kwargs):
    r = s.request(method, f"{API}{path}", timeout=30, **kwargs)
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:800]}")
    return r


def login():
    r = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        die(f"Login tenant admin staging gagal: HTTP {r.status_code} {r.text[:500]}")
    token = r.json().get("token")
    if not token:
        die("Login staging tidak mengembalikan token")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def master_map(s, name):
    rows = req(s, "GET", f"/master/{name}").json()
    return {str(x.get("code") or "").upper(): x for x in rows}


def ensure_master(s, name, code, payload):
    current = master_map(s, name)
    if code.upper() in current:
        print(f"SKIP master {name}: {code}")
        return current[code.upper()]
    body = {"code": code, **payload}
    row = req(s, "POST", f"/master/{name}", json=body).json()
    print(f"ADD  master {name}: {code} — {row.get('name', '')}")
    return row


def rows(s, endpoint):
    return req(s, "GET", endpoint).json()


def marker_in(row, marker):
    for key in ("notes", "internal_notes", "supplier_notes", "reason", "requester", "department"):
        if marker in str(row.get(key) or ""):
            return True
    return False


def find_marked(s, endpoint, marker):
    for row in rows(s, endpoint):
        if marker_in(row, marker):
            return row
    return None


def detail(s, endpoint, did):
    return req(s, "GET", f"{endpoint}/{did}").json()


def setup_masters(s):
    print("\n== MASTER DATA ==")
    pcs = ensure_master(s, "uoms", "DM-PCS", {"name": "Pieces", "symbol": "pcs"})
    liter = ensure_master(s, "uoms", "DM-LTR", {"name": "Liter", "symbol": "L"})
    kg = ensure_master(s, "uoms", "DM-KG", {"name": "Kilogram", "symbol": "kg"})
    box = ensure_master(s, "uoms", "DM-BOX", {"name": "Box", "symbol": "box"})
    rim = ensure_master(s, "uoms", "DM-RIM", {"name": "Rim", "symbol": "rim"})

    cat_sp = ensure_master(s, "item_categories", "DEMO-CAT-SP", {"name": "Sparepart Mesin"})
    cat_con = ensure_master(s, "item_categories", "DEMO-CAT-CON", {"name": "Consumable Workshop"})
    cat_ast = ensure_master(s, "item_categories", "DEMO-CAT-AST", {"name": "Asset & Tools"})
    cat_atk = ensure_master(s, "item_categories", "DEMO-CAT-ATK", {"name": "ATK"})

    div_sp = ensure_master(s, "divisions", "DEMO-SPR", {"name": "Sparepart"})
    div_con = ensure_master(s, "divisions", "DEMO-CON", {"name": "Consumable"})
    div_ast = ensure_master(s, "divisions", "DEMO-AST", {"name": "Asset"})
    div_atk = ensure_master(s, "divisions", "DEMO-ATK", {"name": "ATK / General Affair"})

    wh_pku = ensure_master(s, "warehouses", "DEMO-WH-PKU", {
        "name": "Gudang Pekanbaru Utama", "location": "Pekanbaru", "pic": "Budi Gudang", "division_id": div_sp["id"]
    })
    wh_work = ensure_master(s, "warehouses", "DEMO-WH-WRK", {
        "name": "Gudang Workshop", "location": "Workshop Pekanbaru", "pic": "Andi Workshop", "division_id": div_sp["id"]
    })
    wh_site = ensure_master(s, "warehouses", "DEMO-WH-SITE", {
        "name": "Gudang Site Project", "location": "Site Minas", "pic": "Rizal Site", "division_id": div_sp["id"]
    })

    prj_maint = ensure_master(s, "projects", "DEMO-PRJ-MNT", {"name": "Maintenance Fleet 2026", "status": "Aktif", "pic": "Supervisor Workshop"})
    prj_site = ensure_master(s, "projects", "DEMO-PRJ-SITE", {"name": "Project Site Minas", "status": "Aktif", "pic": "Site Manager"})
    prj_ho = ensure_master(s, "projects", "DEMO-PRJ-HO", {"name": "Operasional Head Office", "status": "Aktif", "pic": "GA"})

    unit_dt = ensure_master(s, "units", "DEMO-UNT-DT01", {"name": "Dump Truck Hino 500", "plate_no": "BM 8123 XX", "type": "Dump Truck", "division_id": div_ast["id"]})
    unit_ex = ensure_master(s, "units", "DEMO-UNT-EX01", {"name": "Excavator CAT 320", "plate_no": "EX-320-01", "type": "Excavator", "division_id": div_ast["id"]})
    unit_gen = ensure_master(s, "units", "DEMO-UNT-GEN01", {"name": "Genset 100 KVA", "plate_no": "GEN-100-01", "type": "Genset", "division_id": div_ast["id"]})

    supcat = ensure_master(s, "supplier_categories", "DEMO-KSP-MRO", {"name": "Supplier MRO / Industrial"})
    tax = ensure_master(s, "taxes", "DEMO-PPN11", {"name": "PPN Demo 11%", "rate": 11})

    sup_tech = ensure_master(s, "suppliers", "DEMO-SUP-TECH", {
        "name": "PT Sumber Teknik Riau", "supplier_category_id": supcat["id"], "default_tax_id": tax["id"],
        "address": "Jl. Soekarno Hatta, Pekanbaru", "pkp": True, "lead_time_days": 3,
        "contacts": [{"name": "Rian", "role": "Sales", "phone": "0812-0000-1001", "email": "rian@example.test", "is_primary": True}],
        "banks": [{"bank_name": "Bank Demo", "account_no": "000111222", "account_name": "PT Sumber Teknik Riau", "is_primary": True}],
    })
    sup_ind = ensure_master(s, "suppliers", "DEMO-SUP-IND", {
        "name": "CV Mitra Industri", "supplier_category_id": supcat["id"], "address": "Jl. Arengka, Pekanbaru",
        "lead_time_days": 2, "contacts": [{"name": "Dedi", "role": "Marketing", "phone": "0812-0000-1002", "is_primary": True}],
    })
    sup_safe = ensure_master(s, "suppliers", "DEMO-SUP-SAFE", {
        "name": "PT Riau Safety Indonesia", "supplier_category_id": supcat["id"], "address": "Kawasan Industri Tenayan",
        "lead_time_days": 5, "contacts": [{"name": "Siska", "role": "Account Executive", "phone": "0812-0000-1003", "is_primary": True}],
    })

    def item(code, name, div, cat, uom, **extra):
        return ensure_master(s, "items", code, {
            "name": name, "division_id": div["id"], "category_id": cat["id"], "base_uom_id": uom["id"],
            "uoms": extra.pop("uoms", []), "part_number": extra.pop("part_number", ""), **extra,
        })

    items = {
        "filter": item("DEMO-BRG-001", "Filter Oli Hino 500", div_sp, cat_sp, pcs, part_number="15613-E0110"),
        "oil": item("DEMO-BRG-002", "Oli Mesin Diesel 15W-40", div_con, cat_con, liter, part_number="15W40-CI4"),
        "air_filter": item("DEMO-BRG-003", "Filter Udara Excavator CAT 320", div_sp, cat_sp, pcs, part_number="CAT-320-AF"),
        "grease": item("DEMO-BRG-004", "Grease EP2", div_con, cat_con, kg),
        "gloves": item("DEMO-BRG-005", "Sarung Tangan Safety", div_con, cat_con, pcs, uoms=[{"uom_id": box["id"], "factor": 12}]),
        "helmet": item("DEMO-BRG-006", "Safety Helmet", div_con, cat_con, pcs),
        "bearing": item("DEMO-BRG-007", "Bearing 6205 ZZ", div_sp, cat_sp, pcs, part_number="6205-ZZ"),
        "drill": item("DEMO-BRG-008", "Mesin Bor Tangan 13mm", div_ast, cat_ast, pcs),
        "paper": item("DEMO-BRG-009", "Kertas A4 80gsm", div_atk, cat_atk, rim),
        "toner": item("DEMO-BRG-010", "Toner Printer Laser", div_atk, cat_atk, pcs),
    }

    return {
        "uoms": {"pcs": pcs, "liter": liter, "kg": kg, "box": box, "rim": rim},
        "divs": {"sp": div_sp, "con": div_con, "ast": div_ast, "atk": div_atk},
        "wh": {"pku": wh_pku, "work": wh_work, "site": wh_site},
        "projects": {"maint": prj_maint, "site": prj_site, "ho": prj_ho},
        "units": {"dt": unit_dt, "ex": unit_ex, "gen": unit_gen},
        "suppliers": {"tech": sup_tech, "ind": sup_ind, "safe": sup_safe},
        "items": items,
    }


def seed_opening_stock(s, m):
    marker = f"{MARK} | SALDO AWAL"
    if find_marked(s, "/adjustments", marker):
        print("SKIP transaksi: saldo awal dummy sudah ada")
        return
    print("\n== SALDO AWAL DUMMY ==")
    plans = [
        (m["wh"]["pku"], [("filter", 40), ("oil", 240), ("air_filter", 15), ("grease", 100), ("gloves", 120), ("helmet", 30), ("bearing", 50), ("drill", 8), ("paper", 40), ("toner", 12)]),
        (m["wh"]["work"], [("filter", 8), ("oil", 80), ("grease", 30), ("gloves", 36), ("bearing", 12)]),
        (m["wh"]["site"], [("filter", 5), ("oil", 60), ("air_filter", 4), ("helmet", 12)]),
    ]
    for idx, (wh, pairs) in enumerate(plans, 1):
        req(s, "POST", "/adjustments", json={
            "date": TODAY, "warehouse_id": wh["id"], "division_id": m["divs"]["sp"]["id"],
            "adj_type": "Saldo Awal Demo", "reason": "Inisialisasi data dummy staging",
            "notes": f"{marker} #{idx}",
            "lines": [{"item_id": m["items"][key]["id"], "adjustment": qty, "reason": "Saldo awal dummy"} for key, qty in pairs],
        })
        print(f"ADD  saldo awal: {wh['name']}")


def seed_procurement(s, m):
    print("\n== TRANSAKSI PROCUREMENT ==")
    mro_marker = f"{MARK} | MRO PEMBELIAN"
    mro = find_marked(s, "/mro", mro_marker)
    if not mro:
        mro = req(s, "POST", "/mro", json={
            "date": TODAY, "need_date": (date.today() + timedelta(days=5)).isoformat(),
            "division_id": m["divs"]["sp"]["id"], "default_warehouse_id": m["wh"]["pku"]["id"],
            "default_project_id": m["projects"]["maint"]["id"], "requester": "Supervisor Workshop",
            "department": "Maintenance", "notes": mro_marker,
            "lines": [
                {"item_id": m["items"]["filter"]["id"], "qty": 10, "unit": "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["dt"]["id"], "notes": "Service berkala unit DT"},
                {"item_id": m["items"]["air_filter"]["id"], "qty": 6, "unit": "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["ex"]["id"], "notes": "Preventive maintenance excavator"},
            ],
        }).json()
        req(s, "POST", f"/mro/{mro['id']}/submit")
        print(f"ADD  MRO: {mro.get('no')}")
    mro = detail(s, "/mro", mro["id"])

    ro_marker = f"{MARK} | RO PEMBELIAN"
    ro = find_marked(s, "/ro", ro_marker)
    if not ro:
        ml = mro["lines"]
        ro = req(s, "POST", "/ro", json={
            "date": TODAY, "division_id": m["divs"]["sp"]["id"], "default_warehouse_id": m["wh"]["pku"]["id"],
            "default_project_id": m["projects"]["maint"]["id"], "requester": "Purchasing Demo", "notes": ro_marker,
            "lines": [
                {"item_id": ml[0]["item_id"], "qty": 8, "unit": ml[0].get("unit") or "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["dt"]["id"], "sources": [{"mro_id": mro["id"], "line_id": ml[0]["id"], "qty": 8, "base_qty": 8}]},
                {"item_id": ml[1]["item_id"], "qty": 4, "unit": ml[1].get("unit") or "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["ex"]["id"], "sources": [{"mro_id": mro["id"], "line_id": ml[1]["id"], "qty": 4, "base_qty": 4}]},
            ],
        }).json()
        req(s, "POST", f"/ro/{ro['id']}/submit")
        print(f"ADD  RO: {ro.get('no')}")
    ro = detail(s, "/ro", ro["id"])

    po_marker = f"{MARK} | PO PEMBELIAN"
    po = find_marked(s, "/po", po_marker)
    if not po:
        rl = ro["lines"]
        po = req(s, "POST", "/po", json={
            "date": TODAY, "division_id": m["divs"]["sp"]["id"], "supplier_id": m["suppliers"]["tech"]["id"],
            "default_warehouse_id": m["wh"]["pku"]["id"], "default_project_id": m["projects"]["maint"]["id"],
            "payment_term": "30 hari", "currency": "IDR", "internal_notes": po_marker,
            "supplier_notes": "Mohon barang dikirim sesuai spesifikasi dan surat jalan mencantumkan nomor PO.",
            "lines": [
                {"item_id": rl[0]["item_id"], "qty": 8, "unit": rl[0].get("unit") or "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["dt"]["id"], "price": 185000, "tax": 11, "sources": [{"ro_id": ro["id"], "line_id": rl[0]["id"], "qty": 8, "base_qty": 8}]},
                {"item_id": rl[1]["item_id"], "qty": 4, "unit": rl[1].get("unit") or "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["ex"]["id"], "price": 425000, "tax": 11, "sources": [{"ro_id": ro["id"], "line_id": rl[1]["id"], "qty": 4, "base_qty": 4}]},
            ],
        }).json()
        po = req(s, "POST", f"/po/{po['id']}/submit").json()
        print(f"ADD  PO: {po.get('no')} ({po.get('status')})")
    po = detail(s, "/po", po["id"])

    do_marker = f"{MARK} | DO PARTIAL"
    if not find_marked(s, "/do", do_marker):
        if str(po.get("status")) in {"Approved", "Partially Received"}:
            pl = po["lines"]
            do = req(s, "POST", "/do", json={
                "date": TODAY, "supplier_id": m["suppliers"]["tech"]["id"], "supplier_dn": "SJ-DEMO-001",
                "supplier_invoice": "INV-DEMO-001", "default_warehouse_id": m["wh"]["pku"]["id"],
                "default_project_id": m["projects"]["maint"]["id"], "receiver": "Petugas Gudang Demo", "notes": do_marker,
                "lines": [
                    {"po_id": po["id"], "po_line_id": pl[0]["id"], "item_id": pl[0]["item_id"], "qty": 5, "unit": pl[0].get("unit") or "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["dt"]["id"], "condition": "Baik", "sources": [{"po_id": po["id"], "line_id": pl[0]["id"], "qty": 5, "base_qty": 5}]},
                    {"po_id": po["id"], "po_line_id": pl[1]["id"], "item_id": pl[1]["item_id"], "qty": 2, "unit": pl[1].get("unit") or "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["ex"]["id"], "condition": "Baik", "sources": [{"po_id": po["id"], "line_id": pl[1]["id"], "qty": 2, "base_qty": 2}]},
                ],
            }).json()
            print(f"ADD  DO partial: {do.get('no')}")
        else:
            print(f"INFO DO partial dilewati karena PO status {po.get('status')} (approval staging sedang aktif)")
    else:
        print("SKIP transaksi: DO partial dummy sudah ada")

    draft_marker = f"{MARK} | PO DRAFT"
    if not find_marked(s, "/po", draft_marker):
        draft = req(s, "POST", "/po", json={
            "date": TODAY, "division_id": m["divs"]["con"]["id"], "supplier_id": m["suppliers"]["safe"]["id"],
            "default_warehouse_id": m["wh"]["pku"]["id"], "currency": "IDR", "internal_notes": draft_marker,
            "lines": [{"item_id": m["items"]["helmet"]["id"], "qty": 20, "unit": "pcs", "warehouse_id": m["wh"]["pku"]["id"], "price": 85000, "tax": 11}],
        }).json()
        print(f"ADD  PO Draft: {draft.get('no')}")


def seed_inventory_transactions(s, m):
    print("\n== TRANSAKSI GUDANG ==")
    mi_marker = f"{MARK} | MI DIRECT"
    if not find_marked(s, "/mi", mi_marker):
        mi = req(s, "POST", "/mi", json={
            "date": TODAY, "division_id": m["divs"]["con"]["id"], "default_warehouse_id": m["wh"]["pku"]["id"],
            "default_project_id": m["projects"]["maint"]["id"], "receiver": "Mekanik Demo", "department": "Workshop",
            "source_type": "Direct", "notes": mi_marker,
            "lines": [{"item_id": m["items"]["gloves"]["id"], "qty": 10, "unit": "pcs", "warehouse_id": m["wh"]["pku"]["id"], "project_id": m["projects"]["maint"]["id"], "unit_id": m["units"]["dt"]["id"], "notes": "Pemakaian workshop"}],
        }).json()
        print(f"ADD  MI: {mi.get('no')}")

    trf_marker = f"{MARK} | TRANSFER SITE"
    if not find_marked(s, "/transfers", trf_marker):
        trf = req(s, "POST", "/transfers", json={
            "date": TODAY, "from_warehouse_id": m["wh"]["pku"]["id"], "to_warehouse_id": m["wh"]["site"]["id"],
            "project_id": m["projects"]["site"]["id"], "notes": trf_marker,
            "lines": [{"item_id": m["items"]["filter"]["id"], "qty": 3, "unit": "pcs", "project_id": m["projects"]["site"]["id"], "unit_id": m["units"]["dt"]["id"], "notes": "Stok operasional site"}],
        }).json()
        print(f"ADD  Transfer: {trf.get('no')}")

    loan_marker = f"{MARK} | LOAN WORKSHOP"
    loan = find_marked(s, "/loans", loan_marker)
    if not loan:
        loan = req(s, "POST", "/loans", json={
            "date": TODAY, "due_date": (date.today() + timedelta(days=7)).isoformat(),
            "from_warehouse_id": m["wh"]["pku"]["id"], "to_warehouse_id": m["wh"]["work"]["id"],
            "project_id": m["projects"]["maint"]["id"], "requester": "Kepala Workshop", "notes": loan_marker,
            "lines": [{"item_id": m["items"]["bearing"]["id"], "qty": 4, "unit": "pcs", "project_id": m["projects"]["maint"]["id"], "notes": "Pinjam untuk pekerjaan urgent"}],
        }).json()
        print(f"ADD  Loan: {loan.get('no')}")
        returnable = req(s, "GET", f"/loans/{loan['id']}/returnable").json()
        if returnable:
            req(s, "POST", f"/loans/{loan['id']}/return", json={
                "date": TODAY, "notes": f"{MARK} | RETURN PARTIAL",
                "lines": [{"loan_line_id": returnable[0]["loan_line_id"], "qty": 2}],
            })
            print("ADD  Loan return partial: 2 pcs")

    adj_marker = f"{MARK} | ADJUSTMENT RUSAK"
    if not find_marked(s, "/adjustments", adj_marker):
        adj = req(s, "POST", "/adjustments", json={
            "date": TODAY, "warehouse_id": m["wh"]["pku"]["id"], "division_id": m["divs"]["sp"]["id"],
            "project_id": m["projects"]["maint"]["id"], "adj_type": "Barang Rusak", "reason": "Kerusakan fisik saat penyimpanan",
            "notes": adj_marker, "lines": [{"item_id": m["items"]["filter"]["id"], "adjustment": -1, "reason": "Kemasan rusak / tidak layak pakai"}],
        }).json()
        print(f"ADD  Adjustment: {adj.get('no')}")

    op_marker = f"{MARK} | STOCK OPNAME"
    op = find_marked(s, "/opname", op_marker)
    if not op:
        op = req(s, "POST", "/opname", json={
            "date": TODAY, "warehouse_id": m["wh"]["pku"]["id"], "division_id": m["divs"]["sp"]["id"],
            "mode": "live", "scope": "division", "notes": op_marker,
        }).json()
        detail_op = detail(s, "/opname", op["id"])
        count_lines = []
        for ln in detail_op.get("lines", []):
            counted = float(ln.get("snapshot") or 0)
            if ln.get("item_id") == m["items"]["bearing"]["id"] and counted > 0:
                counted -= 1
            count_lines.append({"line_id": ln["id"], "counted": counted})
        req(s, "PUT", f"/opname/{op['id']}/count", json={"status": "Review", "lines": count_lines})
        req(s, "POST", f"/opname/{op['id']}/post")
        print(f"ADD  Stock Opname: {op.get('no')} (Posted)")


def main():
    check_safe()
    s = login()
    print(f"==> Dummy seed staging tenant: {EMAIL}")
    masters = setup_masters(s)
    seed_opening_stock(s, masters)
    seed_procurement(s, masters)
    seed_inventory_transactions(s, masters)
    print("\n==> PASS: data dummy staging lengkap tersedia")
    print("    Master: UOM, kategori, divisi, gudang, proyek, unit/aset, supplier, pajak, barang")
    print("    Transaksi: saldo awal, MRO, RO, PO, DO (jika PO approved), MI, transfer, loan/return, adjustment, opname")
    print("    Seeder idempotent: jalankan ulang tidak menggandakan marker transaksi utama.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\n==> FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
