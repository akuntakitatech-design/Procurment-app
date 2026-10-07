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
    "belum bernilai" dihitung pada tanggal yang sama (historis = posisi valuation ledger; hari ini = state pool / reconcile).
    Nilai mencakup barang nonaktif yang masih bersaldo (A aktif 1.000 + B nonaktif 500 = 1.500; Jumlah Item = 1).
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
    _, h = inv("date_from=2026-09-01&date_to=2026-09-30")
    check("Fixture lengkap (saldo awal + ledger): per 30/09 tidak ada pool historis yang belum dapat direkonstruksi",
          h.get("unreconstructable_pools") == 0 and h.get("unreconstructable_items") == 0, (h.get("unreconstructable_pools"), h.get("unreconstructable_items")))

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

    # ---- "Belum bernilai" mengikuti tanggal yang sama dengan nilai (rule valuation-reconcile `missing_average`)
    # Engine menolak posting tanpa biaya, jadi data "belum bernilai" hanya ada dari data lama/impor. Simulasikan di tenant
    # QA sementara (dihapus lagi setelah cek):
    #   Y @ Gudang 1: ledger 2026-09-02 qty 2 / nilai 0 (belum bernilai) -> 2026-10-02 dinilai 2 x 1.000 ; pool kini bernilai
    #   W @ Gudang 1: pool saat ini qty 2 / avg 0 (belum bernilai), tanpa riwayat ledger
    #   L @ Gudang 1: pool lama qty 5 / nilai 5.000 saat ini, TANPA saldo awal / ledger -> historis tidak dapat direkonstruksi
    #   K @ Gudang 1: entri ledger pertama 2026-10-03 dengan qty_before 4 (stok lama tanpa riwayat) -> per 30/09 tidak dapat
    #                 direkonstruksi; saat ini 6 / 6.000
    if os.environ.get("DATABASE_URL"):
        import json as _json
        from urllib.parse import unquote, urlparse

        import pymysql
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from mariadb_motor import _pick_pk
        Y = call("POST", "master/items", {"code": f"VY{u}", "name": "Barang Y", "division_id": dA["id"], **ref}, 200)[1]
        W = call("POST", "master/items", {"code": f"VW{u}", "name": "Barang W", "division_id": dA["id"], **ref}, 200)[1]
        L = call("POST", "master/items", {"code": f"VL{u}", "name": "Barang L legacy", "division_id": dA["id"], **ref}, 200)[1]
        K = call("POST", "master/items", {"code": f"VK{u}", "name": "Barang K legacy", "division_id": dA["id"], **ref}, 200)[1]
        tenant = call("GET", "auth/me")[1].get("tenant_id")
        base = {"tenant_id": tenant, "warehouse_id": w1["id"]}
        legacy = [("valuation_ledger", {**base, "id": f"vl-y1-{u}", "item_id": Y["id"], "doc_type": "Legacy Import", "qty_in": 2, "qty_out": 0,
                                         "qty_after": 2.0, "value_after": 0.0, "avg_after": 0.0, "txn_at": "2026-09-02", "at": "2026-09-02T01:00:00+00:00"}),
                  ("valuation_ledger", {**base, "id": f"vl-y2-{u}", "item_id": Y["id"], "doc_type": "Opening Valuation", "qty_in": 0, "qty_out": 0,
                                         "qty_after": 2.0, "value_after": 2000.0, "avg_after": 1000.0, "txn_at": "2026-10-02", "at": "2026-10-02T01:00:00+00:00"}),
                  ("item_warehouse", {**base, "id": f"iw::{Y['id']}::{w1['id']}", "item_id": Y["id"], "current_stock": 2.0, "avg_cost": 1000.0,
                                      "total_value": 2000.0, "min_stock": 0, "max_stock": 0}),
                  ("item_warehouse", {**base, "id": f"iw::{W['id']}::{w1['id']}", "item_id": W["id"], "current_stock": 2.0, "avg_cost": 0.0,
                                      "total_value": 0.0, "min_stock": 0, "max_stock": 0}),
                  ("item_warehouse", {**base, "id": f"iw::{L['id']}::{w1['id']}", "item_id": L["id"], "current_stock": 5.0, "avg_cost": 1000.0,
                                      "total_value": 5000.0, "min_stock": 0, "max_stock": 0}),
                  ("valuation_ledger", {**base, "id": f"vl-k1-{u}", "item_id": K["id"], "doc_type": "Adjustment", "qty_in": 2, "qty_out": 0,
                                         "qty_before": 4.0, "qty_after": 6.0, "value_after": 6000.0, "avg_after": 1000.0, "txn_at": "2026-10-03",
                                         "at": "2026-10-03T01:00:00+00:00"}),
                  ("item_warehouse", {**base, "id": f"iw::{K['id']}::{w1['id']}", "item_id": K["id"], "current_stock": 6.0, "avg_cost": 1000.0,
                                      "total_value": 6000.0, "min_stock": 0, "max_stock": 0})]
        dbu = urlparse(os.environ["DATABASE_URL"].replace("mariadb://", "mysql://"))
        cn = pymysql.connect(host=dbu.hostname, port=dbu.port or 3306, user=unquote(dbu.username or ""), password=unquote(dbu.password or ""),
                             database=dbu.path.lstrip("/"), autocommit=True)
        pks = []
        try:
            for table, doc in legacy:
                pk = _pick_pk(doc)
                cn.cursor().execute(f"INSERT INTO `{table}` (pk, doc) VALUES (%s, %s)", (pk, _json.dumps(doc)))
                pks.append((table, pk))
            _, h = inv("date_from=2026-09-01&date_to=2026-09-30")
            check("Historis per 30/09: 'belum bernilai' = 1 (Y: posisi ledger qty 2, nilai 0) — bukan state saat ini",
                  h.get("unvalued_items") == 1 and h.get("inventory_value_as_of") == "2026-09-30", (h.get("unvalued_items"), h.get("inventory_value_as_of")))
            check("Historis per 30/09: nilai = 27.500 (Y bernilai 0; W/L/K tanpa riwayat TIDAK diberi nilai saat ini)",
                  abs((h.get("inventory_value") or 0) - 27500) < 0.01, h.get("inventory_value"))
            check("Historis per 30/09: 3 pool (W, L, K) ditandai belum dapat direkonstruksi — bukan diam-diam 0",
                  h.get("unreconstructable_pools") == 3 and h.get("unreconstructable_items") == 3,
                  (h.get("unreconstructable_pools"), h.get("unreconstructable_items")))
            _, hB = inv(f"date_from=2026-09-01&date_to=2026-09-30&division_id={dB['id']}")
            check("Historis per 30/09 filter Divisi B: pool legacy Divisi A tidak ikut (scope sama dengan nilai)",
                  hB.get("unreconstructable_pools") == 0 and abs((hB.get("inventory_value") or 0) - 3000) < 0.01,
                  (hB.get("unreconstructable_pools"), hB.get("inventory_value")))
            _, hK = inv("date_from=2026-10-01&date_to=2026-10-04")
            check("Historis per 04/10: Y 2.000 (02/10) + K terekonstruksi dari ledger 03/10 (6.000) = 35.500; W & L tetap ditandai",
                  abs((hK.get("inventory_value") or 0) - (27500 + 2000 + 6000)) < 0.01 and hK.get("unreconstructable_pools") == 2,
                  (hK.get("inventory_value"), hK.get("unreconstructable_pools")))
            _, h0 = inv("date_from=2026-08-01&date_to=2026-08-31")
            check("Historis per 31/08: 'belum bernilai' = 0 (Y belum ada pada tanggal itu)", h0.get("unvalued_items") == 0, h0.get("unvalued_items"))
            _, c = inv("period=all")
            _, rec = call("GET", "reports/valuation-reconcile")
            n_rec = len({d["item_id"] for d in (rec or {}).get("diagnostics", []) if d.get("type") == "missing_average"})
            check("Saat ini: 'belum bernilai' = 1 (W) = diagnostik missing_average valuation-reconcile (Y sudah bernilai)",
                  c.get("unvalued_items") == 1 == n_rec, (c.get("unvalued_items"), n_rec))
            check("Saat ini: nilai = 27.500 + Y 2.000 + L 5.000 + K 6.000 = 40.500 = Valuation Summary (current MWA)",
                  abs((c.get("inventory_value") or 0) - 40500) < 0.01 and abs(call("GET", "reports/valuation-summary")[1]["total_value"] - 40500) < 0.01,
                  c.get("inventory_value"))
            check("Saat ini: tidak ada peringatan rekonstruksi historis", c.get("unreconstructable_pools") == 0, c.get("unreconstructable_pools"))
        finally:
            for table, pk in pks:
                cn.cursor().execute(f"DELETE FROM `{table}` WHERE pk = %s", (pk,))
            cn.close()
    else:
        print("  info: DATABASE_URL tidak tersedia — kasus 'belum bernilai' historis/saat ini dilewati")

    # ---- Nilai Persediaan mencakup barang NONAKTIF yang masih bersaldo; KPI jumlah/status hanya barang aktif
    dC = call("POST", "master/divisions", {"code": f"VC{u}", "name": f"Divisi Nonaktif {u}"}, 200)[1]
    wC = call("POST", "master/warehouses", {"code": f"VC{u}", "name": f"Gudang VC {u}", "division_id": dC["id"], "is_active": True}, 200)[1]
    A2 = call("POST", "master/items", {"code": f"VA{u}", "name": "Barang A aktif", "division_id": dC["id"], **ref}, 200)[1]
    B2 = call("POST", "master/items", {"code": f"VN{u}", "name": "Barang B nonaktif", "division_id": dC["id"], **ref}, 200)[1]
    for it, cost in ((A2, 1000), (B2, 500)):
        sc, r = adj(wC["id"], dC["id"], it["id"], 1, cost, "2026-10-03")
        check(f"Posting {it['name']} 1 @ {cost}", sc == 200, (sc, r))
    sc, _ = call("PUT", f"master/items/{B2['id']}", {**B2, "is_active": False})
    check("Barang B dinonaktifkan", sc == 200)
    _, cc = inv(f"period=all&division_id={dC['id']}")
    check("Divisi C: Jumlah Item = 1 (barang nonaktif tidak masuk KPI status)", (cc.get("stock") or {}).get("total") == 1, cc.get("stock"))
    check("Divisi C: Nilai Persediaan = 1.000 + 500 = 1.500 (barang nonaktif bersaldo ikut)", abs((cc.get("inventory_value") or 0) - 1500) < 0.01,
          cc.get("inventory_value"))
    _, ch = inv(f"date_from=2026-10-01&date_to=2026-10-05&division_id={dC['id']}") if TODAY > "2026-10-05" else (None, {"inventory_value": 1500})
    check("Divisi C per 05/10 (historis): nilai = 1.500 termasuk barang nonaktif", abs((ch.get("inventory_value") or 0) - 1500) < 0.01, ch.get("inventory_value"))
    sc, vs = call("GET", "reports/valuation-summary")
    _, ca = inv("period=all")
    check("Tanpa filter: Nilai Persediaan Dashboard = total Valuation Summary (termasuk nonaktif)", abs(ca["inventory_value"] - vs["total_value"]) < 0.01,
          (ca["inventory_value"], vs["total_value"]))


if __name__ == "__main__":
    main()
    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)
