"""Nilai Persediaan Dashboard PER TANGGAL AKHIR FILTER (engine valuation/MWA existing, read-only).

Fixture (tenant QA sementara; posting via Penyesuaian -> stock & valuation ledger existing, urut tanggal):
    X @ Gudang 1: 2026-08-10 +10 @1.000 (nilai 10.000) ; 2026-09-05 +10 @2.000 (30.000, avg 1.500) ; 2026-09-28 -5 (22.500)
    X @ Gudang 2: 2026-09-15 +4 @500 (2.000)
    Z (Divisi B) @ Gudang B: 2026-09-01 +3 @1.000 (3.000)
Expected:
    per 2026-07-31 = 0 ; per 2026-08-31 = 10.000 ; per 2026-09-10 = 30.000 + 3.000 ; per 2026-09-30 = 22.500 + 2.000 + 3.000
    per hari ini (Bulan Ini / Semua) = Valuation Summary = Σ item_warehouse.total_value
    nilai per tanggal = value_after laporan Valuation Ledger untuk tanggal tsb ; filter Divisi ikut ; tanpa izin harga -> null
    ledger / avg_cost / total_value tidak berubah karena dashboard dibaca.
"""
import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import receipt_control_test as T
from master_item_stock_test import mk_user

call, check = T.call, T.check
TODAY = datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()
CC = "dashboard/control-center"


def adj(wh, div, item, qty, cost, date):
    line = {"item_id": item, "adjustment": qty, "reason": "QA nilai per tanggal"}
    if qty > 0:
        line["approved_unit_cost"] = cost
    return call("POST", "adjustments", {"date": date, "warehouse_id": wh, "division_id": div, "adj_type": "Opening" if qty > 0 else "Koreksi",
                                        "reason": "QA nilai per tanggal", "notes": "INVENTORY VALUE AS-OF TEST", "lines": [line]})


def inv(qs, caller=call):
    sc, r = caller("GET", f"{CC}?{qs}")
    return sc, (r or {}).get("inventory") or {}


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:5]
    dA = M["div"]
    dB = call("POST", "master/divisions", {"code": f"VB{u}", "name": f"Divisi Val {u}"}, 200)[1]
    w1 = call("POST", "master/warehouses", {"code": f"V1{u}", "name": f"Gudang V1 {u}", "division_id": dA["id"], "is_active": True}, 200)[1]
    w2 = call("POST", "master/warehouses", {"code": f"V2{u}", "name": f"Gudang V2 {u}", "division_id": dA["id"], "is_active": True}, 200)[1]
    wB = call("POST", "master/warehouses", {"code": f"VB{u}", "name": f"Gudang VB {u}", "division_id": dB["id"], "is_active": True}, 200)[1]
    cat = call("POST", "master/item_categories", {"code": f"KV{u}", "name": f"Valuasi {u}"}, 200)[1]
    ref = {"unit": "PCS", "base_uom_id": M["uom"]["id"], "category_id": cat["id"], "is_active": True}
    X = call("POST", "master/items", {"code": f"VX{u}", "name": "Barang X", "division_id": dA["id"], **ref}, 200)[1]
    Z = call("POST", "master/items", {"code": f"VZ{u}", "name": "Barang Z", "division_id": dB["id"], **ref}, 200)[1]
    steps = [(w1, dA, X, 10, 1000, "2026-08-10"), (wB, dB, Z, 3, 1000, "2026-09-01"), (w1, dA, X, 10, 2000, "2026-09-05"),
             (w2, dA, X, 4, 500, "2026-09-15"), (w1, dA, X, -5, None, "2026-09-28")]
    for wh, dv, it, q, c, dt in steps:
        sc, r = adj(wh["id"], dv["id"], it["id"], q, c, dt)
        check(f"Posting penyesuaian {it['name']} {q:+} @ {dt}", sc == 200, (sc, r))
    print(f"setup: tenant + X (2 gudang) + Z (Divisi B) ({u})")

    sc, iw0 = call("GET", "item-warehouse")
    snap0 = sorted((x.get("item_id"), x.get("warehouse_id"), x.get("current_stock"), x.get("avg_cost"), x.get("total_value")) for x in iw0 or [])
    sc, led0 = call("GET", "reports/valuation-ledger")
    n_led0 = len((led0 or {}).get("rows", []))

    cases = (("2026-07-01", "2026-07-31", 0.0), ("2026-08-01", "2026-08-31", 10000.0),
             ("2026-09-01", "2026-09-10", 33000.0), ("2026-09-01", "2026-09-30", 27500.0))
    for df, dt, exp in cases:
        sc, i = inv(f"date_from={df}&date_to={dt}")
        check(f"Nilai Persediaan per {dt} = {exp:,.0f}", sc == 200 and abs((i.get("inventory_value") or 0) - exp) < 0.01
              and i.get("inventory_value_as_of") == dt, (i.get("inventory_value"), i.get("inventory_value_as_of")))

    # nilai per tanggal = value_after laporan Valuation Ledger existing. Laporan memuat entri urut posting; fixture
    # diposting urut tanggal dokumen, jadi entri ke-k per pool = langkah ke-k fixture (tanggal dokumen diketahui).
    sc, r = call("GET", "reports/valuation-ledger")
    per_pool = {}
    for e in (r or {}).get("rows", []):
        per_pool.setdefault((e.get("item_name"), e.get("warehouse_name")), []).append(e.get("value_after") or 0)
    dates = {}
    for wh, dv, it, q, c, dt in steps:
        dates.setdefault((it["name"], wh["name"]), []).append(dt)
    check("Laporan Valuation Ledger memuat 5 entri fixture", sum(len(v) for v in per_pool.values()) == 5, per_pool)
    for dt in ("2026-08-31", "2026-09-10", "2026-09-30"):
        exp = sum(next((v for d, v in reversed(list(zip(dates[k], per_pool.get(k, [])))) if d <= dt), 0) for k in dates)
        _, i = inv(f"date_from=2026-08-01&date_to={dt}")
        check(f"Per {dt}: dashboard = Σ value_after Valuation Ledger ({exp:,.0f})", abs(exp - (i.get("inventory_value") or 0)) < 0.01,
              (exp, i.get("inventory_value")))

    sc, vs = call("GET", "reports/valuation-summary")
    for q in ("period=all", ""):
        _, i = inv(q)
        check(f"Per hari ini [{q or 'Bulan Ini'}] = Valuation Summary ({vs['total_value']:,.0f}), tanggal per = hari ini",
              abs((i.get("inventory_value") or 0) - vs["total_value"]) < 0.01 and i.get("inventory_value_as_of") == TODAY,
              (i.get("inventory_value"), vs["total_value"], i.get("inventory_value_as_of")))
    _, i = inv("period=all")
    check("Per hari ini = 22.500 + 2.000 + 3.000 = 27.500 (tanpa transaksi setelah 28/09)", abs(i["inventory_value"] - 27500) < 0.01, i["inventory_value"])

    _, iA = inv(f"date_from=2026-09-01&date_to=2026-09-10&division_id={dA['id']}")
    check("Filter Divisi A per 10/09: Z (Divisi B) dikecualikan -> 30.000", abs((iA.get("inventory_value") or 0) - 30000) < 0.01, iA.get("inventory_value"))
    _, iB = inv(f"period=all&division_id={dB['id']}")
    check("Filter Divisi B per hari ini -> 3.000", abs((iB.get("inventory_value") or 0) - 3000) < 0.01, iB.get("inventory_value"))
    check("Tidak ada barang 'belum bernilai' pada fixture bernilai", i.get("unvalued_items") == 0, i.get("unvalued_items"))

    # Barang punya stok tetapi belum bernilai (rule valuation-reconcile `missing_average`: qty > 0, avg_cost <= 0)
    Y = call("POST", "master/items", {"code": f"VY{u}", "name": "Barang Y", "division_id": dA["id"], **ref}, 200)[1]
    sc, r = adj(w1["id"], dA["id"], Y["id"], 2, 0, "2026-10-01")
    if sc == 200:
        _, i2 = inv("period=all")
        _, rec = call("GET", "reports/valuation-reconcile")
        n_rec = len({d["item_id"] for d in (rec or {}).get("diagnostics", []) if d.get("type") == "missing_average"})
        check("Info 'belum bernilai' = 1 (Y) = diagnostik missing_average valuation-reconcile", i2.get("unvalued_items") == 1 == n_rec,
              (i2.get("unvalued_items"), n_rec))
        check("Nilai tetap 27.500 (Y bernilai 0)", abs(i2["inventory_value"] - 27500) < 0.01, i2["inventory_value"])
    elif os.environ.get("DATABASE_URL"):
        # Engine menolak posting tanpa biaya; data "belum bernilai" hanya ada dari data lama/impor. Simulasikan SATU pool
        # lama (qty 2, avg 0) di tenant QA sementara, lalu hapus lagi — tidak menyentuh ledger.
        import json as _json
        import pymysql
        from urllib.parse import unquote, urlparse
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from mariadb_motor import _pick_pk
        tenant = call("GET", "auth/me")[1].get("tenant_id")
        doc = {"id": f"iw::{Y['id']}::{w1['id']}", "tenant_id": tenant, "item_id": Y["id"], "warehouse_id": w1["id"],
               "current_stock": 2.0, "avg_cost": 0.0, "total_value": 0.0, "min_stock": 0, "max_stock": 0}
        dbu = urlparse(os.environ["DATABASE_URL"].replace("mariadb://", "mysql://"))
        cn = pymysql.connect(host=dbu.hostname, port=dbu.port or 3306, user=unquote(dbu.username or ""), password=unquote(dbu.password or ""),
                             database=dbu.path.lstrip("/"), autocommit=True)
        pk = _pick_pk(doc)
        cn.cursor().execute("INSERT INTO item_warehouse (pk, doc) VALUES (%s, %s)", (pk, _json.dumps(doc)))
        try:
            _, i2 = inv("period=all")
            _, rec = call("GET", "reports/valuation-reconcile")
            n_rec = len({d["item_id"] for d in (rec or {}).get("diagnostics", []) if d.get("type") == "missing_average"})
            check("Info 'belum bernilai' = 1 (Y, pool lama qty 2 avg 0) = diagnostik missing_average valuation-reconcile",
                  i2.get("unvalued_items") == 1 == n_rec, (i2.get("unvalued_items"), n_rec))
            check("Nilai tetap 27.500 (Y bernilai 0)", abs(i2["inventory_value"] - 27500) < 0.01, i2["inventory_value"])
        finally:
            cn.cursor().execute("DELETE FROM item_warehouse WHERE pk = %s", (pk,))
            cn.close()
    else:
        print("  info: DATABASE_URL tidak tersedia — kasus 'belum bernilai' dilewati")
    lim = mk_user("manager", divs=[dA["id"]], overrides={"view_purchase_price": "deny", "po.view": "allow"})
    _, il = inv("date_from=2026-09-01&date_to=2026-09-30", lim)
    check("Tanpa view_purchase_price: nilai, tanggal & info belum bernilai tidak dikirim", il.get("inventory_value") is None
          and il.get("inventory_value_as_of") is None and il.get("unvalued_items") is None, il)
    limv = mk_user("manager", divs=[dA["id"]], overrides={"view_purchase_price": "allow", "po.view": "allow"})
    _, ilv = inv("date_from=2026-09-01&date_to=2026-09-10", limv)
    check("User Divisi A (berhak harga) per 10/09 -> 30.000 (Divisi B tidak bocor)", abs((ilv.get("inventory_value") or 0) - 30000) < 0.01, ilv.get("inventory_value"))

    sc, iw1 = call("GET", "item-warehouse")
    snap1 = sorted((x.get("item_id"), x.get("warehouse_id"), x.get("current_stock"), x.get("avg_cost"), x.get("total_value")) for x in iw1 or [])
    sc, led1 = call("GET", "reports/valuation-ledger")
    check("item_warehouse (qty, avg_cost, total_value) tidak berubah setelah dashboard dibaca", snap0 == snap1)
    check("Valuation ledger tidak bertambah (read-only)", n_led0 == len((led1 or {}).get("rows", [])), (n_led0, len((led1 or {}).get("rows", []))))


if __name__ == "__main__":
    main()
    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)
