"""Parity ringkasan stok canonical: Master Barang = Inventory = Dashboard (lama & baru) pada scope/filter sama.

Fixture (tenant QA sementara via /saas/register; stok via transaksi Penyesuaian -> ledger/MWA existing):
    A aktif, stok di 2 gudang (10 + 4; min 5+5, max 50+50)  -> 1 item, Normal
    B aktif, stok 5 lalu -5 = 0                             -> Stok Habis
    C aktif, tidak pernah punya item_warehouse              -> Stok Habis, stock_records = 0, sel "Belum ada stok"
    D aktif, stok 3 <= min 5                                 -> Stok Menipis
    E aktif, stok 80 > max 50                                -> Overstock
    F NONAKTIF, stok 3                                       -> tidak masuk KPI Inventory / Dashboard
    G aktif, Divisi B @ gudang Divisi B                      -> tidak terlihat oleh user Divisi A
Regresi valuation: avg_cost / total_value / valuation-summary identik sebelum vs sesudah endpoint ringkasan dipanggil;
Nilai Persediaan Dashboard = Σ total_value engine MWA untuk barang aktif dalam scope.
"""
import sys
import uuid

import requests

import receipt_control_test as T
from master_item_stock_test import adjust, mk_user

call, check = T.call, T.check
MASTER, INV, CC, OLD = "master-items/stock-list", "inventory/item-stock", "dashboard/control-center", "dashboard"
KEYS = ("total", "out_of_stock", "low_stock", "overstock", "normal", "no_stock")


def summ(path, qs="", caller=call):
    sc, r = caller("GET", f"{path}?page_size=100&{qs}")
    return sc, (r or {})


def pick(s):
    return {k: (s or {}).get(k) for k in KEYS}


def valuation_snapshot():
    sc, v = call("GET", "reports/valuation-summary")
    sc2, iw = call("GET", "item-warehouse")
    rows = sorted((r["item_id"], r["warehouse_id"], r["qty_on_hand"], r["avg_cost"], r["inventory_value"]) for r in (v or {}).get("rows", []))
    iws = sorted((x.get("item_id"), x.get("warehouse_id"), x.get("current_stock"), x.get("avg_cost"), x.get("total_value")) for x in (iw or []))
    return sc, sc2, rows, iws, (v or {}).get("total_value")


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:5]
    dA = M["div"]
    dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": f"Divisi B {u}"}, 200)[1]
    whA = call("POST", "master/warehouses", {"code": f"GA{u}", "name": f"Gudang Satu {u}", "division_id": dA["id"], "is_active": True}, 200)[1]
    whA2 = call("POST", "master/warehouses", {"code": f"GC{u}", "name": f"Gudang Dua {u}", "division_id": dA["id"], "is_active": True}, 200)[1]
    whB = call("POST", "master/warehouses", {"code": f"GB{u}", "name": f"Gudang B {u}", "division_id": dB["id"], "is_active": True}, 200)[1]
    cat = call("POST", "master/item_categories", {"code": f"KP{u}", "name": f"Parity {u}"}, 200)[1]
    ref = {"unit": "PCS", "base_uom_id": M["uom"]["id"], "category_id": cat["id"], "division_id": dA["id"]}
    I = {}
    for k, active in (("A", True), ("B", True), ("C", True), ("D", True), ("E", True), ("F", False)):
        I[k] = call("POST", "master/items", {"code": f"P{u}-{k}", "name": f"Barang {k}", "is_active": True, **ref}, 200)[1]
    I["G"] = call("POST", "master/items", {"code": f"P{u}-G", "name": "Barang G", "is_active": True, **ref, "division_id": dB["id"]}, 200)[1]
    adjust(whA["id"], dA["id"], I["A"]["id"], 10)
    adjust(whA2["id"], dA["id"], I["A"]["id"], 4)
    adjust(whA["id"], dA["id"], I["B"]["id"], 5)
    adjust(whA["id"], dA["id"], I["B"]["id"], -5)
    adjust(whA["id"], dA["id"], I["D"]["id"], 3)
    adjust(whA["id"], dA["id"], I["E"]["id"], 80)
    adjust(whA["id"], dA["id"], I["F"]["id"], 3)
    adjust(whB["id"], dB["id"], I["G"]["id"], 7)
    for k, wh in (("A", whA), ("A", whA2), ("B", whA), ("D", whA), ("E", whA)):
        call("POST", "item-warehouse", {"item_id": I[k]["id"], "warehouse_id": wh["id"], "min_stock": 5, "max_stock": 50, "current_stock": 9999}, 200)
    sc, _ = call("PUT", f"master/items/{I['F']['id']}", {k: v for k, v in {**I["F"], "is_active": False}.items() if k not in ("_id",)})
    check("Fixture F dinonaktifkan", sc == 200)
    print(f"setup: tenant + barang A-G + 3 gudang ({u})")

    before = valuation_snapshot()
    check("Valuation summary & item-warehouse terbaca (baseline)", before[0] == 200 and before[1] == 200, before[:2])

    # ---- 1. Status per barang (kategori fixture, barang aktif)
    sc, inv = summ(INV, f"category_id={cat['id']}")
    rows = {r["code"].split("-")[-1]: r for r in inv.get("items", [])}
    check("Inventory item-stock 200", sc == 200, sc)
    check("Item A dihitung 1 item (bukan 2 baris gudang)", sum(1 for r in inv.get("items", []) if r["id"] == I["A"]["id"]) == 1
          and rows.get("A", {}).get("stock_records") == 2 and rows["A"]["total_stock"] == 14, rows.get("A"))
    check("Item A status Normal (14 > min_total 10, <= max_total 100)", rows.get("A", {}).get("stock_status") == "Normal")
    check("Item B = Stok Habis (stok 0)", rows.get("B", {}).get("stock_status") == "Out of Stock" and rows["B"]["stock_records"] == 1)
    check("Item C = Stok Habis + stock_records=0 + tanpa sel gudang (Belum ada stok)",
          rows.get("C", {}).get("stock_status") == "Out of Stock" and rows["C"]["stock_records"] == 0 and rows["C"]["stock"] == {}
          and rows["C"]["total_stock"] == 0, rows.get("C"))
    check("Item D = Stok Menipis", rows.get("D", {}).get("stock_status") == "Low Stock")
    check("Item E = Overstock", rows.get("E", {}).get("stock_status") == "Overstock")
    check("Item F nonaktif tidak masuk Inventory", "F" not in rows)
    # kategori fixture berisi A-E + G (Divisi B, Normal) yang aktif; F nonaktif dikecualikan
    exp = {"total": 6, "out_of_stock": 2, "low_stock": 1, "overstock": 1, "normal": 2, "no_stock": 1}
    check("Ringkasan Inventory kategori fixture = 6 item (A-E,G) / 2 habis (B,C) / 1 menipis / 1 over", pick(inv.get("summary")) == exp, inv.get("summary"))
    _, invA = summ(INV, f"category_id={cat['id']}&division_id={dA['id']}")
    check("Kategori fixture + Divisi A = A-E: 5 item / 2 habis / 1 menipis / 1 over / 1 normal",
          pick(invA.get("summary")) == {**exp, "total": 5, "normal": 1}, invA.get("summary"))

    # ---- 2. Parity Master Barang (Aktif) = Inventory per filter
    for lbl, qs in (("kategori", f"category_id={cat['id']}"), ("tanpa filter", ""), ("gudang", f"warehouse_id={whA['id']}"),
                    ("gudang+kategori", f"warehouse_id={whA2['id']}&category_id={cat['id']}"), ("divisi", f"division_id={dA['id']}"),
                    ("divisi B", f"division_id={dB['id']}"), ("q", f"q=P{u}-")):
        _, m = summ(MASTER, f"active=Aktif&{qs}")
        _, i = summ(INV, qs)
        check(f"Parity Master(Aktif) = Inventory [{lbl}]", pick(m.get("summary")) == pick(i.get("summary")) and m.get("total") == i.get("total"),
              (m.get("summary"), i.get("summary")))
    _, m_all = summ(MASTER, f"category_id={cat['id']}")
    _, m_off = summ(MASTER, f"category_id={cat['id']}&active=Nonaktif")
    check("Master Barang tetap ikut filter status: semua = 7 (termasuk F), Nonaktif = 1", m_all.get("summary", {}).get("total") == 7
          and m_off.get("summary", {}).get("total") == 1, (m_all.get("summary"), m_off.get("summary")))

    # ---- 3. Parity dengan Dashboard baru & lama (scope penuh tenant + filter divisi)
    _, m = summ(MASTER, "active=Aktif")
    sc, cc = call("GET", f"{CC}?period=all")
    sc2, old = call("GET", OLD)
    check("Dashboard baru: KPI persediaan = Master Barang (Aktif)", sc == 200 and pick((cc.get("inventory") or {}).get("stock")) == pick(m.get("summary")),
          ((cc.get("inventory") or {}).get("stock"), m.get("summary")))
    check("Dashboard lama /api/dashboard: stock = Master Barang (Aktif)", sc2 == 200 and pick(old.get("stock")) == pick(m.get("summary")),
          (old.get("stock"), m.get("summary")))
    check("Dashboard total item = unique item, bukan jumlah baris item_warehouse", cc["inventory"]["stock"]["total"] == m["summary"]["total"]
          and len(before[3]) != m["summary"]["total"], (cc["inventory"]["stock"]["total"], len(before[3])))
    for dv in (dA, dB):
        _, md = summ(MASTER, f"active=Aktif&division_id={dv['id']}")
        _, ccd = call("GET", f"{CC}?period=all&division_id={dv['id']}")
        check(f"Filter Divisi ({dv['name']}): Dashboard = Master = Inventory", pick(ccd["inventory"]["stock"]) == pick(md.get("summary"))
              == pick(summ(INV, f"division_id={dv['id']}")[1].get("summary")), (ccd["inventory"]["stock"], md.get("summary")))

    # ---- 4. Nilai Persediaan = engine MWA existing (aktif, scope), tanpa perhitungan baru
    sc, v = call("GET", "reports/valuation-summary")
    val_rows = v.get("rows", [])
    f_val = sum(r["inventory_value"] for r in val_rows if r["item_id"] == I["F"]["id"])
    check("Nilai Persediaan Dashboard = Σ total_value valuation-summary − barang nonaktif",
          abs(cc["inventory"]["inventory_value"] - (v["total_value"] - f_val)) < 0.01 and f_val > 0, (cc["inventory"]["inventory_value"], v["total_value"], f_val))
    a_val = sum(r["inventory_value"] for r in val_rows if r["item_id"] == I["A"]["id"])
    check("Nilai Item A (2 gudang) mengikuti MWA: 14 x 1.000", abs(a_val - 14000) < 0.01, a_val)

    # ---- 5. Scope user terbatas (Divisi A + gudang A) & tanpa izin harga
    lim = mk_user("manager", divs=[dA["id"]], overrides={"items.view": "allow", "view_purchase_price": "deny", "po.view": "allow"})
    _, ml = summ(MASTER, "active=Aktif", lim)
    _, il = summ(INV, "", lim)
    scl, ccl = lim("GET", f"{CC}?period=all")
    _, oldl = lim("GET", OLD)
    check("User Divisi A: Master = Inventory = Dashboard baru = Dashboard lama", pick(ml.get("summary")) == pick(il.get("summary"))
          == pick(ccl["inventory"]["stock"]) == pick(oldl.get("stock")), (ml.get("summary"), il.get("summary"), ccl["inventory"]["stock"], oldl.get("stock")))
    check("User Divisi A tidak melihat Barang G (Divisi B)", all(r["id"] != I["G"]["id"] for r in il.get("items", [])))
    check("User Divisi A: division_id Divisi B -> 403 (Inventory & Dashboard)", lim("GET", f"{INV}?division_id={dB['id']}")[0] == 403
          and lim("GET", f"{CC}?division_id={dB['id']}")[0] == 403)
    check("User Divisi A: gudang Divisi B -> 403", lim("GET", f"{INV}?warehouse_id={whB['id']}")[0] == 403)
    check("Tanpa view_purchase_price: Nilai Persediaan tidak dikirim (null)", ccl["inventory"]["inventory_value"] is None)
    whu = mk_user("warehouse", divs=[dA["id"]], warehouses=[whA2["id"]], overrides={"items.view": "allow"})
    _, mw = summ(MASTER, "active=Aktif", whu)
    _, iw = summ(INV, "", whu)
    _, ow = whu("GET", OLD)
    check("User gudang tertentu: kolom gudang hanya gudang yang ditugaskan", [w["id"] for w in iw.get("warehouses", [])] == [whA2["id"]], iw.get("warehouses"))
    check("User gudang tertentu: Master = Inventory = Dashboard lama", pick(mw.get("summary")) == pick(iw.get("summary")) == pick(ow.get("stock")),
          (mw.get("summary"), iw.get("summary"), ow.get("stock")))

    # ---- 6. Regresi valuation: endpoint ringkasan read-only (ledger / avg_cost / total_value / MWA tidak berubah)
    for path in (MASTER, INV, CC, OLD):
        call("GET", path)
    after = valuation_snapshot()
    check("Valuation-summary (qty, avg_cost, inventory_value) identik sebelum vs sesudah", before[2] == after[2] and before[4] == after[4])
    check("item_warehouse (current_stock, avg_cost, total_value) identik sebelum vs sesudah", before[3] == after[3])
    sc, led = call("GET", "inventory/ledger")
    check("Ledger tetap berisi 8 mutasi fixture (tidak ada posting baru)", sc == 200 and sum(1 for x in led if x.get("item_id") in {v["id"] for v in I.values()}) == 8,
          sum(1 for x in led if x.get("item_id") in {v["id"] for v in I.values()}))
    sc, pos = call("GET", "inventory/position")
    check("/inventory/position lama tetap kompatibel (array per baris gudang)", sc == 200 and isinstance(pos, list)
          and sum(1 for x in pos if x.get("item_id") == I["A"]["id"]) == 2)

    # ---- 7. Tenant isolation
    T.S = requests.Session()  # sesi bersih (tanpa header/cookie tenant pertama)
    T.setup()  # tenant lain
    _, other = summ(INV, f"category_id={cat['id']}")
    _, oth_m = summ(MASTER, "active=Aktif")
    _, oth_cc = call("GET", f"{CC}?period=all")
    _, oth_old = call("GET", OLD)
    check("Tenant lain: kategori tenant pertama -> 0 barang", other.get("total") == 0, other.get("summary"))
    check("Tenant lain: Dashboard baru = lama = Master miliknya (2 barang setup, tanpa stok)",
          pick(oth_cc["inventory"]["stock"]) == pick(oth_m.get("summary")) == pick(oth_old.get("stock")) and oth_m["summary"]["total"] == 2
          and oth_m["summary"]["out_of_stock"] == 2, (oth_cc["inventory"]["stock"], oth_m.get("summary")))


if __name__ == "__main__":
    main()
    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)
