"""Saldo Awal (Import Excel) Harga Beli -> Opening Inventory Valuation (throwaway tenant, dev DB)."""
import os
import sys
import threading
import uuid
from io import BytesIO

import requests
from openpyxl import Workbook

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402

call, check = T.call, T.check
COLS = ["item_code", "item_name", "uom_code", "warehouse_code", "project_code", "qty", "purchase_price"]


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(COLS)
    for r in rows:
        ws.append(r)
    b = BytesIO()
    wb.save(b)
    return b.getvalue()


def imp(rows, sess=None):
    s = sess or T.S
    r = s.post(f"{T.API}/excel/import/opening_inventory",
               files={"file": ("saldo_awal.xlsx", xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def dbq(sql, args=()):
    """Hitung baris ledger langsung di DB dev (verifikasi duplikasi). Menolak DB production."""
    import pymysql
    from urllib.parse import urlparse, unquote
    url = os.environ.get("TEST_DATABASE_URL") or next(x.split("=", 1)[1].strip().strip('"') for x in open("/app/backend/.env") if x.startswith("DATABASE_URL="))
    assert "prod" not in url.lower()
    u = urlparse(url.replace("mariadb://", "mysql://"))
    c = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""), database=u.path.lstrip("/"))
    with c.cursor() as cur:
        cur.execute(sql, args)
        v = cur.fetchone()[0]
    c.close()
    return v


def n_ledger(table, item_id, wh_id, doc_type=None):
    sql = f"SELECT COUNT(*) FROM {table} WHERE JSON_UNQUOTE(JSON_EXTRACT(doc,'$.item_id'))=%s AND JSON_UNQUOTE(JSON_EXTRACT(doc,'$.warehouse_id'))=%s"
    args = [item_id, wh_id]
    if doc_type:
        sql += " AND JSON_UNQUOTE(JSON_EXTRACT(doc,'$.doc_type'))=%s"
        args.append(doc_type)
    return dbq(sql, args)


def cands(fn=None, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    sc, d = (fn or call)("GET", f"valuation/opening-candidates{'?' + q if q else ''}")
    return sc, {(r["item_id"], r["warehouse_id"]): r for r in (d or {}).get("rows", [])} if sc == 200 else d


def tetapkan(item, wh, cost, fn=None):
    return (fn or call)("POST", "valuation/opening", {"item_id": item["id"], "warehouse_id": wh["id"], "opening_avg_cost": cost, "cutoff_date": "2026-01-01"})


def main():
    M = T.setup()
    import vendor_invoice_test as V
    V.M = M
    u = uuid.uuid4().hex[:6]
    sc, dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)
    sc, whC = call("POST", "master/warehouses", {"code": f"WC{u}", "name": "Gudang C", "is_active": True, "division_id": dB["id"]}, 200)
    sc, box = call("POST", "master/uoms", {"code": f"BOX{u}", "name": "Box"}, 200)
    sc, dus = call("POST", "master/uoms", {"code": f"DUS{u}", "name": "Dus"}, 200)
    ref = T.item_ref(M)
    sc, itB = call("POST", "master/items", {"code": f"BX{u}", "name": "Kabel Roll", "unit": "PCS", "is_active": True, **ref,
                                            "uoms": [{"uom_id": box["id"], "factor": 10}]}, 200)
    sc, itC = call("POST", "master/items", {"code": f"PJ{u}", "name": "Sekring", "unit": "PCS", "is_active": True, **ref}, 200)
    sc, itD = call("POST", "master/items", {"code": f"DP{u}", "name": "Lampu", "unit": "PCS", "is_active": True, **ref}, 200)
    A, wh, wh2, pcs = M["item"], M["wh"], M["wh2"], M["uom"]["code"]

    # --- validasi import: duplikat & UOM tak terbukti -> ditolak, tidak ada stok/harga dikarang
    sc, r = imp([[itD["code"], "Lampu", pcs, wh["code"], "", 5, 1000], [itD["code"], "Lampu", pcs, wh["code"], "", 3, 2000]])
    check("import: baris duplikat Barang+Gudang(+Proyek) dalam file ditolak", sc == 200 and r.get("ok") is False and any("duplikat" in e for e in r.get("errors", [])), r)
    sc, r = imp([[itD["code"], "Lampu", dus["code"], wh["code"], "", 5, 1000]])
    check("import: satuan tanpa faktor konversi ditolak (tidak bisa dinormalisasi)", r.get("ok") is False and any("belum terdaftar" in e for e in r.get("errors", [])), r)
    sc, c0 = cands()
    check("import ditolak: tidak ada stok/kandidat untuk Lampu", (itD["id"], wh["id"]) not in c0)

    # --- import saldo awal (multi barang, multi gudang, UOM, proyek ganda)
    rows = [
        [A["code"], A["name"], pcs, wh["code"], "", 22, 85000],                           # 22 PCS @85.000
        [A["code"], A["name"], pcs, wh2["code"], "", 5, 90000],                           # multi gudang
        [itB["code"], "Kabel Roll", box["code"], wh["code"], "", 2, 100000],             # 2 BOX @100.000 -> 20 PCS @10.000
        [itC["code"], "Sekring", pcs, wh["code"], M["pa"]["code"], 10, 1000],            # proyek A
        [itC["code"], "Sekring", pcs, wh["code"], M["pb"]["code"], 30, 2000],            # proyek B -> rata-rata tertimbang
        [A["code"], A["name"], pcs, whC["code"], "", 4, 70000],                           # gudang divisi B (scope)
    ]
    sc, r = imp(rows)
    check("import saldo awal OK (6 baris)", sc == 200 and r.get("ok") and r.get("imported") == 6, r)
    sc, C = cands()
    a1, a2, b1, c1 = C.get((A["id"], wh["id"]), {}), C.get((A["id"], wh2["id"]), {}), C.get((itB["id"], wh["id"]), {}), C.get((itC["id"], wh["id"]), {})
    check("Qty Existing benar (22 / 5 / 20 PCS / 40)", a1.get("qty_existing") == 22 and a2.get("qty_existing") == 5 and b1.get("qty_existing") == 20 and c1.get("qty_existing") == 40,
          [x.get("qty_existing") for x in (a1, a2, b1, c1)])
    check("Harga Beli muncul sebagai kandidat Opening Average Cost (85.000)", a1.get("opening_cost_candidate") == 85000 and a1.get("opening_cost_source") == "Import Saldo Awal", a1)
    check("kandidat Opening Inventory Value = Qty x Cost (1.870.000)", a1.get("opening_value_candidate") == 1870000, a1.get("opening_value_candidate"))
    check("status tetap Belum Dinilai; avg_cost/total_value pool belum diposting (0)", a1.get("status") == "unvalued" and a1.get("avg_cost") == 0 and a1.get("inventory_value") == 0, a1)
    check("multi gudang: Gudang B kandidat 90.000", a2.get("opening_cost_candidate") == 90000 and a2.get("opening_value_candidate") == 450000, a2)
    check("UOM: 2 BOX @100.000 (1 BOX=10 PCS) -> 10.000 / PCS", b1.get("opening_cost_candidate") == 10000 and b1.get("opening_value_candidate") == 200000, b1)
    check("Barang+Gudang dengan 2 proyek: rata-rata tertimbang (10x1.000+30x2.000)/40 = 1.750", c1.get("opening_cost_candidate") == 1750 and c1.get("opening_value_candidate") == 70000, c1)
    sl_before = n_ledger("stock_ledger", A["id"], wh["id"])

    # --- Tetapkan
    sc, res = tetapkan(A, wh, a1["opening_cost_candidate"])
    check("Tetapkan berhasil: value 1.870.000", sc == 200 and res.get("inventory_value") == 1870000 and res.get("qty_on_hand") == 22, (sc, res))
    sc, C = cands()
    a1 = C[(A["id"], wh["id"])]
    check("setelah Tetapkan: Sudah Dinilai, avg_cost 85.000, total_value 1.870.000", a1["status"] == "valued" and a1["avg_cost"] == 85000 and a1["inventory_value"] == 1870000, a1)
    check("Tetapkan tidak mengubah Qty (tetap 22)", a1["qty_existing"] == 22)
    check("Tetapkan tidak membuat stock movement qty kedua", n_ledger("stock_ledger", A["id"], wh["id"]) == sl_before, (sl_before, n_ledger("stock_ledger", A["id"], wh["id"])))
    check("valuation ledger Opening Valuation tepat satu", n_ledger("valuation_ledger", A["id"], wh["id"], "Opening Valuation") == 1)
    sc, r2 = tetapkan(A, wh, 85000)
    check("repost ditolak (400 existing contract: sudah ada)", sc == 400 and "sudah ada" in str(r2.get("detail")), (sc, r2))
    sc, C = cands()
    check("repost: ledger tetap satu, value tidak bertambah dua kali, qty tetap",
          n_ledger("valuation_ledger", A["id"], wh["id"], "Opening Valuation") == 1 and C[(A["id"], wh["id"])]["inventory_value"] == 1870000 and C[(A["id"], wh["id"])]["qty_existing"] == 22)
    sc, sb = call("GET", f"stock/by-warehouse/{A['id']}")
    q = {x.get("warehouse_id"): x.get("stock") for x in (sb.get("warehouses") or [])}
    check("stok fisik per gudang tidak berubah (22 / 5)", float(q.get(wh["id"]) or 0) == 22 and float(q.get(wh2["id"]) or 0) == 5, q)

    # --- Tetapkan bersamaan -> tepat satu valuasi
    out = []
    def go():
        out.append(tetapkan(A, wh2, 90000)[0])
    ths = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    sc, C = cands()
    check("Tetapkan paralel x6: tepat 1 sukses, sisanya 400/409 (bukan 500)", out.count(200) == 1 and all(x in (200, 400, 409) for x in out), out)
    check("Tetapkan paralel: ledger satu, total_value 450.000 (tidak ganda)", n_ledger("valuation_ledger", A["id"], wh2["id"], "Opening Valuation") == 1
          and C[(A["id"], wh2["id"])]["inventory_value"] == 450000, C[(A["id"], wh2["id"])])

    # --- UOM & weighted juga lewat engine Tetapkan
    sc, _ = tetapkan(itB, wh, 10000)
    sc2, _ = tetapkan(itC, wh, 1750)
    sc3, C = cands()
    check("Tetapkan UOM/tertimbang: Kabel 200.000 (20 PCS), Sekring 70.000 (40)", sc == 200 and sc2 == 200 and C[(itB["id"], wh["id"])]["inventory_value"] == 200000
          and C[(itC["id"], wh["id"])]["inventory_value"] == 70000 and C[(itB["id"], wh["id"])]["qty_existing"] == 20)

    # --- Moving Average transaksi berikutnya: 22 @85.000 + DO 10 @1.000 -> (1.870.000+10.000)/32 = 58.750
    po, _, _ = T.make_po(M, "supX", 10)
    sc, d1 = call("POST", "do", T.do_body(M, po, 10, "supX"), 200)
    sc, C = cands()
    a1 = C[(A["id"], wh["id"])]
    check("Moving Average setelah DO: qty 32, avg 58.750, value 1.880.000", a1["qty_existing"] == 32 and abs(a1["avg_cost"] - 58750) < 0.01
          and abs(a1["inventory_value"] - 1880000) < 0.01, a1)

    # --- warehouse / division scope
    # Aksi Tetapkan wajib view_purchase_price AND stock_adjustment (engine izin existing; bukan nama role).
    up = mk_user("purchasing", overrides={"adjustment.create": "deny", "adjustment.post": "deny"}, divs=[M["div"]["id"]])
    sc, r = tetapkan(A, wh2, 70000, up)
    check("izin: punya Lihat Harga Beli tanpa Penyesuaian Stok -> Tetapkan 403", sc == 403, (sc, r))
    ua = mk_user("purchasing", overrides={"adjustment.create": "allow", "adjustment.post": "allow"}, divs=[M["div"]["id"]])
    sc, Ca = cands(ua)
    check("scope: user Divisi Teknik tidak melihat Gudang C (Divisi B)", sc == 200 and (A["id"], whC["id"]) not in Ca and (A["id"], wh2["id"]) in Ca, list(Ca)[:3] if isinstance(Ca, dict) else Ca)
    sc, r = tetapkan(A, whC, 70000, ua)
    check("scope: Tetapkan gudang di luar cakupan ditolak 404", sc == 404, (sc, r))
    ub = mk_user("purchasing", divs=[dB["id"]])
    sc, Cb = cands(ub)
    check("scope: user Divisi B melihat Gudang C dengan kandidat 70.000", (A["id"], whC["id"]) in Cb and Cb[(A["id"], whC["id"])]["opening_cost_candidate"] == 70000)
    nop = mk_user("warehouse", overrides={"view_purchase_price": "deny"})
    sc, _ = cands(nop)
    sc2, _ = tetapkan(A, whC, 70000, nop)
    check("izin: tanpa Lihat Harga Beli tidak bisa melihat/menetapkan nilai (403)", sc == 403 and sc2 == 403, (sc, sc2))

    # ================= HARDENING: re-import setelah Tetapkan & movement sebelum Tetapkan =================
    mkit = lambda code, name: call("POST", "master/items", {"code": f"{code}{u}", "name": name, "unit": "PCS", "is_active": True, **ref}, 200)[1]
    itE, itF, itG = mkit("PP", "Pipa"), mkit("VV", "Valve"), mkit("GS", "Gasket")
    sc, r = imp([[itE["code"], "Pipa", pcs, wh["code"], "", 100, 10000]])
    sc, _ = tetapkan(itE, wh, 10000)
    snap = lambda: (cands()[1][(itE["id"], wh["id"])], n_ledger("valuation_ledger", itE["id"], wh["id"], "Opening Valuation"),
                    n_ledger("stock_ledger", itE["id"], wh["id"]))
    e0, vl0, sl0 = snap()
    check("pool Pipa: import 100 x 10.000 lalu Tetapkan = 1.000.000", sc == 200 and e0["status"] == "valued" and e0["inventory_value"] == 1000000 and vl0 == 1, e0)
    sc, r = imp([[itE["code"], "Pipa", pcs, wh["code"], "", 120, 10000]])
    check("import ulang pool yang sudah ditetapkan DITOLAK dengan pesan jelas", sc == 200 and r.get("ok") is False
          and any("sudah ditetapkan. Saldo awal tidak dapat diubah." in e for e in r.get("errors", [])), r)
    sc, r2 = imp([[itE["code"], "Pipa", pcs, wh["code"], "", 100, 12000]])
    check("import ulang harga saja (qty sama) juga ditolak", r2.get("ok") is False, r2)
    e1, vl1, sl1 = snap()
    check("setelah import ulang gagal: qty/avg/value/opening slice/ledger tidak berubah",
          (e1["qty_existing"], e1["avg_cost"], e1["inventory_value"], e1["opening_import_qty"], e1["opening_cost_candidate"], e1["opening_value_candidate"], vl1, sl1)
          == (100, 10000, 1000000, 100, 10000, 1000000, 1, sl0), (e1, vl1, sl1, sl0))
    sc, r = imp([[itE["code"], "Pipa", pcs, wh["code"], "", 100, 10000]])
    e2, vl2, sl2 = snap()
    check("import ulang identik (tanpa perubahan) diterima tanpa menulis apa pun", r.get("ok") is True and (e2["qty_existing"], e2["inventory_value"], vl2, sl2) == (100, 1000000, 1, sl0), (r, e2))
    sc, r = imp([[itE["code"], "Pipa", pcs, wh["code"], "", 130, 10000], [itG["code"], "Gasket", pcs, wh["code"], "", 8, 5000]])
    sc2, Cg = cands()
    check("file campuran (pool terkunci + pool lain) ditolak utuh: pool lain belum tersentuh", r.get("ok") is False and (itG["id"], wh["id"]) not in Cg, r)
    sc, r = imp([[itG["code"], "Gasket", pcs, wh["code"], "", 8, 5000]])
    sc2, _ = tetapkan(itG, wh, 5000)
    sc3, Cg = cands()
    check("pool lain tetap dapat diproses (import + Tetapkan Gasket 40.000)", r.get("ok") and sc2 == 200 and Cg[(itG["id"], wh["id"])]["inventory_value"] == 40000, (r, sc2))

    # movement sebelum Tetapkan: saldo awal 100 x 10.000 lalu DO +20
    M["valve"] = itF
    sc, r = imp([[itF["code"], "Valve", pcs, wh["code"], "", 100, 10000]])
    pov, _, _ = T.make_po(M, "supX", 20, item="valve")
    sc, _ = call("POST", "do", T.do_body(M, pov, 20, "supX"), 200)
    sc, C = cands()
    f1 = C[(itF["id"], wh["id"])]
    check("movement +20: Current Qty 120, Opening Qty tetap 100", f1["qty_existing"] == 120 and f1["opening_import_qty"] == 100, f1)
    check("kandidat opening berdasarkan slice 100 (1.000.000), BUKAN 120 x 10.000", f1["opening_cost_candidate"] == 10000 and f1["opening_value_candidate"] == 1000000, f1)
    check("baris diberi alasan blokir (perlu review)", f1["status"] == "unvalued" and "transaksi stok setelah saldo awal" in (f1.get("opening_blocked_reason") or ""), f1)
    pool_before = (f1["avg_cost"], f1["inventory_value"])
    sc, r = tetapkan(itF, wh, 10000)
    sc2, C = cands()
    f2 = C[(itF["id"], wh["id"])]
    check("Tetapkan setelah movement ditolak (400) — histori/HPP tidak diubah otomatis", sc == 400 and "transaksi stok setelah saldo awal" in str(r.get("detail"))
          and (f2["avg_cost"], f2["inventory_value"]) == pool_before and f2["qty_existing"] == 120
          and n_ledger("valuation_ledger", itF["id"], wh["id"], "Opening Valuation") == 0, (sc, r, f2))

    # concurrency: Tetapkan vs import ulang bersamaan -> state selalu konsisten, tanpa 500
    bad = []
    for i in range(4):
        itX = mkit(f"CC{i}", f"Konkuren {i}")
        imp([[itX["code"], "Konkuren", pcs, wh["code"], "", 50, 1000]])
        res = {}
        th = [threading.Thread(target=lambda: res.__setitem__("t", tetapkan(itX, wh, 1000)[0])),
              threading.Thread(target=lambda: res.__setitem__("i", imp([[itX["code"], "Konkuren", pcs, wh["code"], "", 60, 1000]])))]
        [t.start() for t in th]
        [t.join() for t in th]
        x = cands()[1][(itX["id"], wh["id"])]
        nvl = n_ledger("valuation_ledger", itX["id"], wh["id"], "Opening Valuation")
        ok_state = (x["status"] == "valued" and nvl == 1 and x["opening_import_qty"] == x["qty_existing"] and abs(x["inventory_value"] - x["qty_existing"] * x["avg_cost"]) < 0.01) \
            or (x["status"] == "unvalued" and nvl == 0 and x["qty_existing"] == 60 and x["opening_import_qty"] == 60)
        if not ok_state or res.get("t") not in (200, 400, 409) or res.get("i", (0,))[0] not in (200, 409):
            bad.append((res.get("t"), res.get("i"), x, nvl))
    check("konkuren Tetapkan vs import ulang x4: state konsisten, tanpa 500", not bad, bad)

    # --- tenant isolation
    sess_a = T.S
    T.S = requests.Session()
    M2 = T.setup()
    sc, C2 = cands()
    check("tenant: kandidat tenant lain tidak terlihat", sc == 200 and not any(k[0] in (A["id"], itB["id"], itC["id"]) for k in C2))
    sc, r = tetapkan(A, whC, 70000)
    check("tenant: Tetapkan barang/gudang tenant lain ditolak 404", sc == 404, (sc, r))
    sc, r = imp([[itE["code"], "Pipa", pcs, wh["code"], "", 1, 1]])
    check("tenant: import saldo awal memakai kode barang/gudang tenant lain ditolak (tidak ditemukan)", r.get("ok") is False
          and any("tidak ditemukan" in e for e in r.get("errors", [])), r)
    T.S = sess_a
    sc, C = cands()
    check("tenant: pool tenant asal tidak berubah", C[(A["id"], whC["id"])]["status"] == "unvalued" and C[(A["id"], whC["id"])]["inventory_value"] == 0)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
