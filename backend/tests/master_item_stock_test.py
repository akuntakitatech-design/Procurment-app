"""Master Barang + stok per gudang: server-side pagination/search/filter/sort, ringkasan, status Min/Max,
tenant isolation, permission, cakupan divisi, cakupan gudang, tanpa N+1, kompatibilitas & Hapus Massal.
Dijalankan terhadap backend dev/staging (tenant QA sementara via /saas/register) — BUKAN production."""
import re
import sys
import uuid

import requests

import receipt_control_test as T
from vendor_invoice_test import PW, U

call, check, API = T.call, T.check, T.API
EP = "master-items/stock-list"


def page(qs, caller=call):
    sc, r = caller("GET", f"{EP}?{qs}")
    return sc, (r if isinstance(r, dict) else {})


def codes(r):
    return [x.get("code") for x in r.get("items") or []]


def qcount(session, qs):
    r = session.get(f"{API}/{EP}?{qs}")
    m = re.search(r'desc="(\d+) q', r.headers.get("server-timing", ""))
    return r.status_code, (int(m.group(1)) if m else None), r.json()


def mk_user(role, divs=None, overrides=None, warehouses=None):
    email = f"mis_{role}_{uuid.uuid4().hex[:6]}@example.com"
    sc, u = call("POST", "users", {"email": email, "password": PW, "name": f"QA {role}", "role": role}, 200)
    body = {"overrides": overrides or {}}
    if divs is not None:
        body["division_override"] = {"mode": "selected", "divisions": divs}
    call("PUT", f"access/users/{u['id']}", body, 200)
    if warehouses is not None:
        call("PUT", f"users/{u['id']}", {"warehouses": warehouses}, 200)
    return U(email)


def adjust(wh, div, item, qty):
    return call("POST", "adjustments", {"date": "2026-09-20", "warehouse_id": wh, "division_id": div, "adj_type": "Opening",
                                        "reason": "Saldo Awal QA", "notes": "MASTER ITEM STOCK TEST",
                                        "lines": [{"item_id": item, "adjustment": qty, "approved_unit_cost": 1000, "reason": "Saldo Awal QA"}]}, 200)


def main():
    M = T.setup()
    u = uuid.uuid4().hex[:5]
    dA = M["div"]
    dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": f"Divisi B {u}"}, 200)[1]
    whA = call("POST", "master/warehouses", {"code": f"GA{u}", "name": f"Corporate {u}", "division_id": dA["id"], "is_active": True}, 200)[1]
    whA2 = call("POST", "master/warehouses", {"code": f"GC{u}", "name": f"EW PPPRE {u}", "division_id": dA["id"], "is_active": True}, 200)[1]
    whB = call("POST", "master/warehouses", {"code": f"GB{u}", "name": f"OMSS {u}", "division_id": dB["id"], "is_active": True}, 200)[1]
    whOff = call("POST", "master/warehouses", {"code": f"GX{u}", "name": f"Nonaktif {u}", "division_id": dA["id"], "is_active": False}, 200)[1]
    cats = [call("POST", "master/item_categories", {"code": f"KC{u}{i}", "name": f"Kat{u} {n}"}, 200)[1] for i, n in enumerate(("Alfa", "Beta"))]
    uom = call("POST", "master/uoms", {"code": f"S{u}", "name": f"Pieces {u}", "symbol": f"PC{u[:2]}"}, 200)[1]
    items = []
    for i in range(30):
        items.append(call("POST", "master/items", {"code": f"MS{u}-{i:02d}", "name": f"Barang Stok {i:02d}", "unit": "PCS", "is_active": True,
                                                   "base_uom_id": uom["id"], "category_id": cats[i % 2]["id"],
                                                   "division_id": (dA if i < 20 else dB)["id"]}, 200)[1])
    # Stok via transaksi Penyesuaian (ledger) — tidak menulis current_stock langsung.
    adjust(whA["id"], dA["id"], items[0]["id"], 10)      # 0: Corporate 10, min 5 max 50 -> Normal
    adjust(whA2["id"], dA["id"], items[0]["id"], 4)      #    EW 4, min 5 -> sel Stok Menipis; total 14 vs min 10 -> Normal
    adjust(whA["id"], dA["id"], items[1]["id"], 3)       # 1: 3 <= min 5 -> Stok Menipis
    adjust(whA["id"], dA["id"], items[2]["id"], 80)      # 2: 80 > max 50 -> Overstock
    adjust(whA["id"], dA["id"], items[3]["id"], 5)
    adjust(whA["id"], dA["id"], items[3]["id"], -5)      # 3: 0 -> Stok Habis
    adjust(whB["id"], dB["id"], items[20]["id"], 7)      # 20: divisi B @ OMSS
    for it, wh, mn, mx in ((items[0], whA, 5, 50), (items[0], whA2, 5, 50), (items[1], whA, 5, 50), (items[2], whA, 5, 50), (items[3], whA, 1, 50)):
        call("POST", "item-warehouse", {"item_id": it["id"], "warehouse_id": wh["id"], "min_stock": mn, "max_stock": mx, "current_stock": 9999}, 200)
    print(f"setup: tenant + 30 barang + 4 gudang ({u})")

    # --- kompatibilitas: endpoint lama tidak berubah
    sc, r = call("GET", "master/items")
    check("kompatibilitas: /master/items tanpa page tetap array", sc == 200 and isinstance(r, list) and len(r) == 32)
    sc, r = call("GET", "master/items?page=1&page_size=25")
    check("kompatibilitas: /master/items?page tetap envelope lama", sc == 200 and r.get("total") == 32 and "summary" not in r)
    sc, r = call("GET", "item-warehouse")
    check("item_warehouse: current_stock dari POST Min/Max diabaikan (ledger-controlled)",
          all(x["current_stock"] != 9999 for x in r) and len(r) == 6, f"{[(x.get('item_code'), x.get('current_stock')) for x in r]}")

    # --- envelope + page size
    sc, r = page("page=1")
    check("envelope {items,total,page,page_size,summary,warehouses,filters}", sc == 200 and {"items", "total", "page", "page_size", "summary", "warehouses", "filters"} <= set(r), f"{sc} {list(r)}")
    check("default 25 per halaman", r.get("page_size") == 25 and len(r["items"]) == 25 and r["total"] == 32, f"{r.get('page_size')} {r.get('total')}")
    check("default urut terbaru dahulu", r["items"][0]["code"] == f"MS{u}-29")
    for n in (50, 100):
        sc, r = page(f"page=1&page_size={n}")
        check(f"page_size {n} diterima", r.get("page_size") == n and len(r["items"]) == 32)
    check("page_size tidak valid -> 25", page("page=1&page_size=7")[1].get("page_size") == 25)
    sc, r = page("page=99&page_size=25")
    check("halaman di luar jangkauan -> halaman terakhir", r.get("page") == 2 and len(r["items"]) == 7)

    # --- kolom gudang dinamis dari Master Gudang (aktif, sesuai scope), bukan hardcode
    sc, r = page("page=1&page_size=100")
    wh_ids = [w["id"] for w in r["warehouses"]]
    check("kolom gudang = gudang aktif tenant (urut nama)", set(wh_ids) == {M["wh"]["id"], M["wh2"]["id"], whA["id"], whA2["id"], whB["id"]}
          and whOff["id"] not in wh_ids and [w["name"] for w in r["warehouses"]] == sorted([w["name"] for w in r["warehouses"]], key=str.lower), f"{[w['name'] for w in r['warehouses']]}")
    by = {x["code"]: x for x in r["items"]}
    i0, i1, i2, i3, i5 = (by[f"MS{u}-{k:02d}"] for k in (0, 1, 2, 3, 5))
    check("stok per gudang = item_warehouse (Corporate 10, EW 4)", i0["stock"][whA["id"]]["qty"] == 10 and i0["stock"][whA2["id"]]["qty"] == 4, i0["stock"])
    check("status sel: Normal & Stok Menipis (min/max existing)", i0["stock"][whA["id"]]["status"] == "Normal" and i0["stock"][whA2["id"]]["status"] == "Low Stock")
    check("Total Stok = jumlah seluruh gudang terlihat", i0["total_stock"] == 14)
    check("status barang: Normal / Menipis / Overstock / Habis", (i0["stock_status"], i1["stock_status"], i2["stock_status"], i3["stock_status"]) == ("Normal", "Low Stock", "Overstock", "Out of Stock"),
          (i0["stock_status"], i1["stock_status"], i2["stock_status"], i3["stock_status"]))
    check("barang tanpa record stok -> Belum ada stok (tanpa sel)", i5["stock_status"] == "No Stock" and i5["stock"] == {} and i5["total_stock"] == 0)
    check("label Kategori/Divisi/Satuan human-readable", i0["category_label"] == f"Kat{u} Alfa" and i0["division_label"] == dA["name"] and i0["unit_label"] == uom["symbol"], (i0["category_label"], i0["division_label"], i0["unit_label"]))
    blob = str(r).lower()
    check("tidak ada nilai HPP / moving average / harga", not any(k in blob for k in ("avg_cost", "average_cost", "moving", "hpp", "'price'", "total_value")))
    iw = {(x["item_id"], x["warehouse_id"]): x["current_stock"] for x in call("GET", "item-warehouse")[1]}
    check("seluruh sel cocok dengan sumber stok existing", all(iw.get((x["id"], w)) == c["qty"] for x in r["items"] for w, c in x["stock"].items())
          and sum(1 for x in r["items"] for _ in x["stock"]) == len(iw))

    # --- ringkasan (seluruh dataset sesuai filter, bukan halaman aktif)
    s = r["summary"]
    check("ringkasan: Jumlah Item / Habis / Menipis / Overstock", (s["total"], s["out_of_stock"], s["low_stock"], s["overstock"]) == (32, 1, 1, 1), s)
    sc, r1 = page("page=2&page_size=25")
    check("ringkasan sama di halaman lain", r1["summary"] == s)
    sc, rs = page("page=1&stock_status=Low Stock")
    check("filter status stok + ringkasan tetap utuh", codes(rs) == [f"MS{u}-01"] and rs["summary"] == s, f"{codes(rs)}")
    sc, rs = page(f"page=1&category_id={cats[1]['id']}")
    check("ringkasan mengikuti filter kategori", rs["summary"]["total"] == 15 and rs["summary"]["low_stock"] == 1 and rs["summary"]["out_of_stock"] == 1, rs["summary"])

    # --- search / filter / sort backend seluruh dataset
    sc, r = page(f"page=1&q=MS{u}-01")
    check("search: barang di halaman 2 tetap ditemukan", r.get("total") == 1 and codes(r) == [f"MS{u}-01"])
    sc, r = page("page=1&q=barang stok 2")
    exp = [x for x in items if all(t in f"{x['code']} {x['name']}".lower() for t in ("barang", "stok", "2"))]
    check("search nama multi-kata (AND, seluruh dataset)", r.get("total") == len(exp) >= 11, f"{r.get('total')} vs {len(exp)}")
    sc, r = page(f"page=1&division_id={dB['id']}")
    check("filter divisi", r.get("total") == 10 and all(x["division_id"] == dB["id"] for x in r["items"]))
    sc, r = page(f"page=1&warehouse_id={whA['id']}")
    check("filter gudang: hanya kolom gudang tsb + barang ber-stok di gudang tsb", [w["id"] for w in r["warehouses"]] == [whA["id"]] and sorted(codes(r)) == [f"MS{u}-0{k}" for k in range(4)]
          and r["items"] and all(set(x["stock"]) <= {whA["id"]} for x in r["items"]), f"{codes(r)}")
    sc, r = page(f"page=1&warehouse_id={whA2['id']}")
    check("filter gudang: total & status dihitung untuk gudang terpilih", r.get("total") == 1 and r["items"][0]["total_stock"] == 4 and r["items"][0]["stock_status"] == "Low Stock")
    call("PUT", f"master/items/{items[6]['id']}", {"is_active": False}, 200)
    sc, r = page("page=1&active=Nonaktif")
    check("filter status barang Nonaktif", codes(r) == [f"MS{u}-06"])
    sc, r = page("page=1&page_size=100&sort=code&dir=asc&q=MS" + u)
    check("sort kode naik", codes(r) == sorted(codes(r)) and codes(r)[0] == f"MS{u}-00")
    sc, r2 = page("page=1&page_size=100&sort=code&dir=desc&q=MS" + u)
    check("sort kode turun", codes(r2) == list(reversed(codes(r))))
    sc, r = page("page=1&page_size=25&sort=total_stock&dir=desc")
    check("sort Total Stok turun (seluruh dataset)", codes(r)[:3] == [f"MS{u}-02", f"MS{u}-00", f"MS{u}-20"], codes(r)[:3])
    sc, r = page("page=1&page_size=25&sort=stock_status&dir=asc")
    check("sort status: Habis lebih dulu", r["items"][0]["stock_status"] == "Out of Stock")
    sc, r = page("page=2&page_size=25&sort=code&dir=asc")
    check("sort + page: halaman 2 melanjutkan urutan global", codes(r)[:1] == [f"MS{u}-23"] or codes(r)[:1] == [sorted(codes(page('page=1&page_size=100&sort=code&dir=asc')[1]))[25]], codes(r)[:2])

    # --- tanpa N+1: jumlah query konstan terhadap ukuran halaman / jumlah barang
    sc, q25, _ = qcount(T.S, "page=1&page_size=25")
    sc, q100, _ = qcount(T.S, "page=1&page_size=100")
    for i in range(30, 45):
        call("POST", "master/items", {"code": f"MS{u}-{i:02d}", "name": f"Barang Stok {i:02d}", "unit": "PCS", "is_active": True, "division_id": dA["id"]}, 200)
    sc, q100b, _ = qcount(T.S, "page=1&page_size=100")
    print(f"  query/request: page25={q25} page100={q100} page100+15barang={q100b}")
    check("tanpa N+1: query konstan (25 vs 100 baris, +15 barang)", q25 is not None and q25 == q100 == q100b and q25 <= 15, f"{q25} {q100} {q100b}")

    # --- permission
    nv = mk_user("manager", overrides={"items.view": "deny"})
    check("permission: tanpa Barang.Lihat -> 403", nv("GET", f"{EP}?page=1")[0] == 403)

    # --- cakupan divisi + gudang (enforcement backend)
    A = mk_user("manager", divs=[dA["id"]])
    sc, r = page("page=1&page_size=100", A)
    vis_wh = {w["id"] for w in r["warehouses"]}
    check("divisi A: hanya barang divisi A (+ tanpa divisi)", sc == 200 and all(x.get("division_id") in (dA["id"], None, "") for x in r["items"])
          and f"MS{u}-20" not in codes(r) and r["total"] == 37, f"{sc} {r.get('total')}")
    check("divisi A: kolom gudang divisi B tersembunyi", whB["id"] not in vis_wh and {whA["id"], whA2["id"]} <= vis_wh, vis_wh)
    check("divisi A: opsi filter Divisi hanya divisi dalam cakupan", [d["id"] for d in r["filters"]["divisions"]] == [dA["id"]], r["filters"]["divisions"])
    check("divisi A: ringkasan hanya dataset dalam cakupan", r["summary"]["total"] == 37 and r["summary"]["out_of_stock"] == 1)
    check("divisi A: search tidak membocorkan barang divisi B", page(f"page=1&q=MS{u}-20", A)[1].get("total") == 0)
    check("divisi A: filter divisi B -> 403", page(f"page=1&division_id={dB['id']}", A)[0] == 403)
    check("divisi A: filter gudang divisi B -> 403", page(f"page=1&warehouse_id={whB['id']}", A)[0] == 403)
    B = mk_user("manager", divs=[dB["id"]])
    sc, r = page("page=1&page_size=100", B)
    b20 = next((x for x in r["items"] if x["code"] == f"MS{u}-20"), {})
    check("divisi B: barang divisi B + stok OMSS 7", b20.get("stock", {}).get(whB["id"], {}).get("qty") == 7 and whA["id"] not in {w["id"] for w in r["warehouses"]})
    W = mk_user("warehouse", divs=[dA["id"]], warehouses=[whA2["id"]])
    sc, r = page("page=1&page_size=100", W)
    w0 = next((x for x in r["items"] if x["code"] == f"MS{u}-00"), {})
    check("gudang ditugaskan: hanya kolom gudang tsb, Total = stok gudang tsb", sc == 200 and [w["id"] for w in r["warehouses"]] == [whA2["id"]]
          and w0.get("total_stock") == 4 and set(w0.get("stock", {})) == {whA2["id"]}, f"{sc} {[w['name'] for w in r.get('warehouses', [])]} {w0.get('total_stock')}")
    check("gudang ditugaskan: gudang lain via filter -> 403", page(f"page=1&warehouse_id={whA['id']}", W)[0] == 403)

    # --- tenant isolation
    Tb = requests.Session()
    v = uuid.uuid4().hex[:8]
    Tb.post(f"{API}/saas/register", json={"company_name": f"MIS {v}", "pic_name": "QA", "email": f"mis_{v}@example.com", "whatsapp": "+628123456789",
                                          "workspace_slug": f"mis-{v}", "plan_code": "starter", "password": PW, "address": "x", "terms_accepted": True})
    tok = Tb.post(f"{API}/auth/login", json={"email": f"mis_{v}@example.com", "password": PW}).json().get("token")
    Tb.headers.update({"Authorization": f"Bearer {tok}"})
    ob = lambda m, p, b=None: Tb.request(m, f"{API}/{p}", json=b).json()  # noqa: E731
    owh = ob("POST", "master/warehouses", {"code": "OW1", "name": "Gudang Tenant Lain", "is_active": True})
    odiv = ob("POST", "master/divisions", {"code": "OD1", "name": "Div Lain"})
    oit = ob("POST", "master/items", {"code": "OI1", "name": "Barang Tenant Lain", "unit": "PCS", "is_active": True, "division_id": odiv["id"]})
    Tb.post(f"{API}/adjustments", json={"date": "2026-09-20", "warehouse_id": owh["id"], "division_id": odiv["id"], "adj_type": "Opening", "reason": "x",
                                        "lines": [{"item_id": oit["id"], "adjustment": 99, "approved_unit_cost": 1000, "reason": "x"}]})
    r = ob("GET", f"{EP}?page=1&page_size=100")
    check("tenant lain: tidak melihat barang/gudang tenant A", r.get("total") == 1 and codes(r) == ["OI1"] and [w["id"] for w in r["warehouses"]] == [owh["id"]], f"{r.get('total')} {codes(r)}")
    check("tenant lain: stok sendiri 99", (r["items"][0]["stock"].get(owh["id"]) or {}).get("qty") == 99 if r.get("items") else False)
    check("tenant lain: filter gudang tenant A -> 403", Tb.get(f"{API}/{EP}?page=1&warehouse_id={whA['id']}").status_code == 403)
    sc, r = page("page=1&page_size=100")
    check("tenant A: agregat tidak tercampur stok tenant lain", r["summary"]["total"] == 47 and owh["id"] not in {w["id"] for w in r["warehouses"]}
          and sum(x["total_stock"] for x in r["items"]) == 10 + 4 + 3 + 80 + 0 + 7, f"{r['summary']} {sum(x['total_stock'] for x in r['items'])}")

    # --- Hapus Massal (Tahap 1) tetap all-or-nothing dari pilihan halaman aktif
    sc, r = page(f"page=1&page_size=25&q=MS{u}-4&sort=code&dir=desc")
    pick = [x["id"] for x in r["items"][:2]]
    sc, res = call("POST", "master-bulk-delete/items", {"ids": pick + [items[0]["id"]]})
    after = page("page=1&page_size=100&active=Aktif")[1]
    check("Hapus Massal campuran (ada yang berstok) -> 409, tidak ada yang terhapus", sc == 409 and after.get("total") == 46, f"{sc} {after.get('total')}")
    sc, res = call("POST", "master-bulk-delete/items", {"ids": pick})
    after = page("page=1&page_size=100&active=Aktif")[1]
    check("Hapus Massal barang tanpa dependensi -> berhasil", sc == 200 and after.get("total") == 44, f"{sc} {res} {after.get('total')}")

    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\nTOTAL {ok}/{len(T.RESULTS)} passed")
    sys.exit(0 if ok == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
