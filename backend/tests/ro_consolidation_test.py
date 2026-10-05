"""RO Consolidation — multi MRO / multi SPK (throwaway tenant, localhost, dev DB)."""
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402

call, check = T.call, T.check


def mro(M, no, qty, div=None, item="item", project=None, unit=None):
    line = {"item_id": M[item]["id"], "qty": qty, "warehouse_id": M["wh"]["id"]}
    if project:
        line["project_id"] = M[project]["id"]
    if unit:
        line["unit_id"] = unit
    sc, d = call("POST", "mro", {"no": no, "division_id": div or M["div"]["id"], "requester": "Budi", "submitted": True, "lines": [line]}, 200)
    call("POST", f"mro/{d['id']}/submit", {})
    return d, d["lines"][0]


def src(d, ml, qty):
    return {"mro_id": d["id"], "line_id": ml["id"], "qty": qty, "base_qty": qty}


def ro_body(M, item, qty, sources, div=None):
    return {"division_id": div or M["div"]["id"], "lines": [{"item_id": M[item]["id"], "qty": qty, "uom_id": M["uom"]["id"], "conversion_factor": 1,
                                                             "warehouse_id": M["wh"]["id"], "sources": sources}]}


def main():
    M = T.setup()
    T.M = M
    import vendor_invoice_test as V
    V.M = M
    u = uuid.uuid4().hex[:5]
    sc, spkA = call("POST", "spk", {"spk_number": f"SPK-A-{u}", "project_name": "Proyek A", "spk_value": 1000, "procurement_budget": 1000, "status": "active"}, 200)
    sc, spkB = call("POST", "spk", {"spk_number": f"SPK-B-{u}", "project_name": "Proyek B", "spk_value": 1000, "procurement_budget": 1000, "status": "active"}, 200)
    sc, unitX = call("POST", "master/units", {"code": f"UX{u}", "name": "Excavator 01", "division_id": M["div"]["id"]}, 200)
    m1, l1 = mro(M, f"MRO-1-{u}", 10, project="pa", unit=unitX["id"])
    m2, l2 = mro(M, f"MRO-2-{u}", 15, project="pb")
    m3, l3 = mro(M, f"MRO-3-{u}", 5)
    sc, _ = call("PUT", f"spk-allocations/mro/line/{l1['id']}", {"allocations": [{"spk_id": spkA["id"], "allocated_qty": 10}]}, 200)
    sc, _ = call("PUT", f"spk-allocations/mro/line/{l2['id']}", {"allocations": [{"spk_id": spkB["id"], "allocated_qty": 15}]}, 200)
    sc, dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)
    mB, lB = mro(M, f"MRO-B-{u}", 7, div=dB["id"])

    # --- pull: field konsolidasi tersedia
    sc, rows = call("GET", "pull/mro-for-ro")
    mine = {r["line_id"]: r for r in rows if r.get("line_id") in (l1["id"], l2["id"], l3["id"])}
    check("pull: 3 sumber MRO tersedia dengan divisi & label SPK", len(mine) == 3 and mine[l1["id"]].get("division_id") == M["div"]["id"]
          and mine[l1["id"]].get("spk_label") == f"SPK-A-{u}" and mine[l3["id"]].get("spk_label") == "Non-SPK", mine.get(l1["id"]))

    # --- validasi backend
    sc, r = call("POST", "ro", ro_body(M, "item", 30, [src(m1, l1, 10), src(m2, l2, 15), src(mB, lB, 5)]))
    check("tolak: campur divisi dalam satu RO", sc == 400 and "Divisi" in str(r), (sc, r))
    sc, r = call("POST", "ro", ro_body(M, "item", 25, [src(m1, l1, 10), src(m2, l2, 10)]))
    check("tolak: sum alokasi != Qty RO", sc == 400 and "Total alokasi" in str(r), (sc, r))
    sc, r = call("POST", "ro", ro_body(M, "item", 12, [src(m1, l1, 12)]))
    check("tolak: alokasi > sisa MRO", sc == 400 and "melebihi sisa" in str(r), (sc, r))
    sc, r = call("POST", "ro", ro_body(M, "item2", 10, [src(m1, l1, 10)]))
    check("tolak: barang berbeda dengan sumber", sc in (400, 404), (sc, r))
    b = ro_body(M, "item", 10, [src(m1, l1, 10)]); b["division_id"] = ""
    sc, r = call("POST", "ro", b)
    check("tolak: divisi RO kosong", sc == 400 and "Divisi" in str(r), (sc, r))

    # --- konsolidasi penuh 3 MRO -> 1 baris RO
    sc, ro1 = call("POST", "ro", ro_body(M, "item", 30, [src(m1, l1, 10), src(m2, l2, 15), src(m3, l3, 5)]), 200)
    lines = ro1.get("lines") or []
    check("RO konsolidasi: 1 baris, qty 30, 3 MRO", sc == 200 and len(lines) == 1 and lines[0]["qty"] == 30 and lines[0].get("mro_count") == 3, lines)
    srcs = {s["mro_no"]: s for s in lines[0].get("sources") or []}
    check("breakdown: MRO -> SPK -> Proyek -> Unit tersimpan", srcs.get(f"MRO-1-{u}", {}).get("spk_label") == f"SPK-A-{u}" and srcs[f"MRO-1-{u}"]["qty"] == 10
          and srcs[f"MRO-1-{u}"].get("project_name") == "Project A" and srcs[f"MRO-1-{u}"].get("unit_name") == "Excavator 01"
          and srcs.get(f"MRO-2-{u}", {}).get("spk_label") == f"SPK-B-{u}" and srcs.get(f"MRO-3-{u}", {}).get("spk_label") == "Non-SPK", srcs)
    sc, al = call("GET", f"spk-allocations/ro/doc/{ro1['id']}")
    la = (al.get("lines") or [{}])[0]
    got = {a.get("spk_number"): a.get("allocated_qty") for a in la.get("allocations") or []}
    check("SPK diwariskan per sumber: A=10, B=15, Non-SPK=5", got == {f"SPK-A-{u}": 10, f"SPK-B-{u}": 15} and la.get("non_spk_qty") == 5, (got, la.get("non_spk_qty")))
    sc, rows = call("GET", "pull/mro-for-ro")
    check("sisa: MRO yang habis tidak ditawarkan lagi", not any(r.get("line_id") in (l1["id"], l2["id"], l3["id"]) for r in rows))
    sc, r = call("POST", "ro", ro_body(M, "item", 1, [src(m1, l1, 1)]))
    check("tolak: MRO yang sama terambil dua kali", sc == 400 and "melebihi sisa" in str(r), (sc, r))

    # --- batal RO -> sisa kembali
    call("POST", f"ro/{ro1['id']}/cancel", {}, 200)
    sc, rows = call("GET", "pull/mro-for-ro")
    back = {r["line_id"]: r for r in rows if r.get("line_id") in (l1["id"], l2["id"], l3["id"])}
    check("batal RO: sisa MRO kembali penuh", len(back) == 3 and back[l2["id"]]["outstanding"] == 15, back)

    # --- parsial: 20 dari 30, sumber diketahui
    sc, ro2 = call("POST", "ro", ro_body(M, "item", 20, [src(m3, l3, 5), src(m2, l2, 15)]), 200)
    sc, al = call("GET", f"spk-allocations/ro/doc/{ro2['id']}")
    la = (al.get("lines") or [{}])[0]
    got = {a.get("spk_number"): a.get("allocated_qty") for a in la.get("allocations") or []}
    check("parsial: SPK hanya dari sumber yang diambil (B=15, Non-SPK=5, tanpa SPK-A)", got == {f"SPK-B-{u}": 15} and la.get("non_spk_qty") == 5, got)
    sc, rows = call("GET", "pull/mro-for-ro")
    left = {r["line_id"]: r for r in rows if r.get("line_id") in (l1["id"], l2["id"], l3["id"])}
    check("parsial: sisa hanya MRO-1 (10)", set(left) == {l1["id"]} and left[l1["id"]]["outstanding"] == 10, left)

    # --- edit: atur ulang alokasi sumber (backend revalidate)
    sc, g = call("GET", f"ro/{ro2['id']}")
    line = g["lines"][0]
    edit = {**{k: g.get(k) for k in ("date", "division_id", "requester", "notes")}, "lines": [{**{k: line.get(k) for k in ("id", "item_id", "warehouse_id")},
            "qty": 25, "uom_id": M["uom"]["id"], "conversion_factor": 1, "sources": [src(m3, l3, 5), src(m2, l2, 15), src(m1, l1, 5)]}]}
    sc, r = call("PUT", f"transactions/ro/{ro2['id']}", edit)
    sc2, g2 = call("GET", f"ro/{ro2['id']}")
    tot = sum(s["qty"] for s in g2["lines"][0]["sources"]) if g2.get("lines") else 0
    check("edit: alokasi diatur ulang (25 dari 3 MRO)", sc == 200 and tot == 25 and g2["lines"][0].get("mro_count") == 3, (sc, r, tot))
    edit["lines"][0]["qty"] = 31; edit["lines"][0]["sources"][2]["qty"] = edit["lines"][0]["sources"][2]["base_qty"] = 11
    sc, r = call("PUT", f"transactions/ro/{ro2['id']}", edit)
    check("edit: tolak alokasi > sisa saat edit", sc == 400 and "melebihi sisa" in str(r), (sc, r))

    # --- SPK per sumber (bukan pool): 4 dari MRO-1 (SPK-A) + 6 dari MRO-4 (Non-SPK)
    m4, l4 = mro(M, f"MRO-4-{u}", 6)
    sc, ro3 = call("POST", "ro", ro_body(M, "item", 10, [src(m1, l1, 4), src(m4, l4, 6)]), 200)
    sc, al = call("GET", f"spk-allocations/ro/doc/{ro3['id']}")
    la = (al.get("lines") or [{}])[0]
    got = {a.get("spk_number"): a.get("allocated_qty") for a in la.get("allocations") or []}
    check("SPK per sumber: SPK-A=4 (sesuai qty diambil), Non-SPK=6", got == {f"SPK-A-{u}": 4} and la.get("non_spk_qty") == 6, (got, la.get("non_spk_qty")))
    sc, pv = call("POST", "spk-allocations/preview-inherit", {"target_type": "ro", "sources": [{"source_line_id": l1["id"], "qty": 1}, {"source_line_id": l4["id"], "qty": 0}]})
    check("preview-inherit konsisten per sumber", sc == 200 and [a.get("allocated_qty") for a in pv.get("allocations") or []] == [1], pv)

    # --- edit: Qty berubah tanpa rincian -> wajib balance ulang
    sc, g = call("GET", f"ro/{ro3['id']}")
    ln = g["lines"][0]
    base = {**{k: g.get(k) for k in ("date", "division_id", "requester", "notes")}}
    sc, r = call("PUT", f"transactions/ro/{ro3['id']}", {**base, "lines": [{"id": ln["id"], "item_id": ln["item_id"], "qty": 8, "uom_id": M["uom"]["id"], "warehouse_id": ln.get("warehouse_id")}]})
    check("edit: Qty berubah tanpa rincian sumber ditolak", sc == 400 and "Rincian" in str(r), (sc, r))
    # --- edit tanpa perubahan (kirim ulang sources hasil GET) -> sumber MRO/SPK tidak hilang
    resend = [{"mro_id": s["mro_id"], "line_id": s["line_id"], "qty": s["qty"], "base_qty": s["qty"]} for s in ln["sources"]]
    sc, r = call("PUT", f"transactions/ro/{ro3['id']}", {**base, "lines": [{"id": ln["id"], "item_id": ln["item_id"], "qty": 10, "uom_id": M["uom"]["id"], "warehouse_id": ln.get("warehouse_id"), "sources": resend}]})
    sc2, g3 = call("GET", f"ro/{ro3['id']}")
    l3x = (g3.get("lines") or [{}])[0]
    sc, al = call("GET", f"spk-allocations/ro/doc/{ro3['id']}")
    la = (al.get("lines") or [{}])[0]
    got = {a.get("spk_number"): a.get("allocated_qty") for a in la.get("allocations") or []}
    check("edit ulang: sumber MRO & SPK tetap (2 MRO, SPK-A=4)", sc2 == 200 and l3x.get("mro_count") == 2 and sum(s["qty"] for s in l3x.get("sources") or []) == 10
          and got == {f"SPK-A-{u}": 4}, (l3x.get("sources"), got))
    # --- edit tanpa sources, qty sama -> sumber lama dipertahankan
    sc, r = call("PUT", f"transactions/ro/{ro3['id']}", {**base, "lines": [{"id": l3x["id"], "item_id": l3x["item_id"], "qty": 10, "uom_id": M["uom"]["id"], "warehouse_id": l3x.get("warehouse_id")}]})
    sc2, g4 = call("GET", f"ro/{ro3['id']}")
    check("edit tanpa rincian (qty sama): alokasi lama dipertahankan", sc == 200 and (g4.get("lines") or [{}])[0].get("mro_count") == 2, (sc, r))

    # --- concurrency: dua request bersamaan berebut sisa MRO yang sama -> hanya satu lolos
    m5, l5 = mro(M, f"MRO-5-{u}", 8)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda _: call("POST", "ro", ro_body(M, "item", 8, [src(m5, l5, 8)])), range(4)))
    oks = [x for x in res if x[0] == 200]
    sc, rows = call("GET", "pull/mro-for-ro")
    check("concurrency: 4 RO paralel atas sisa 8 -> tepat 1 berhasil, tanpa over-allocation", len(oks) == 1 and not any(r.get("line_id") == l5["id"] for r in rows),
          [x[0] for x in res])

    # --- RO lama (tanpa sumber MRO) tetap dapat dibuka
    sc, legacy = call("POST", "ro", {"division_id": M["div"]["id"], "lines": [{"item_id": M["item2"]["id"], "qty": 3, "uom_id": M["uom"]["id"], "warehouse_id": M["wh"]["id"]}]}, 200)
    sc, lg = call("GET", f"ro/{legacy['id']}")
    check("backward compat: RO tanpa sumber MRO dapat dibuka (sources kosong)", sc == 200 and lg["lines"][0].get("sources") == [] and lg["lines"][0].get("mro_count") == 0, lg.get("lines"))

    # --- stok tidak berubah
    sc, st = call("GET", f"stock/by-warehouse/{M['item']['id']}")
    check("RO tidak mengubah stok", all((w.get("stock") or 0) == 0 for w in st.get("warehouses") or []), st)

    # --- divisi scope: user divisi B tidak bisa membuka RO divisi A
    ub = mk_user("purchasing", divs=[dB["id"]])
    check("division scope: user Divisi B -> RO Divisi A ditolak", ub("GET", f"ro/{ro2['id']}")[0] in (403, 404))

    # --- batal tidak menduplikasi allocation (sisa kembali dari status, bukan baris baru)
    sc, before = call("GET", f"ro/{ro3['id']}")
    n_before = len((before.get("lines") or [{}])[0].get("sources") or [])
    call("POST", f"ro/{ro3['id']}/cancel", {}, 200)
    call("POST", f"ro/{ro3['id']}/cancel", {})
    sc, after = call("GET", f"ro/{ro3['id']}")
    sc, rows = call("GET", "pull/mro-for-ro")
    l4row = next((r for r in rows if r.get("line_id") == l4["id"]), {})
    check("batal 2x: allocation tidak ganda & sisa MRO-4 kembali tepat 6", len((after.get("lines") or [{}])[0].get("sources") or []) == n_before
          and l4row.get("outstanding") == 6, (n_before, l4row))

    # --- information disclosure: MRO di luar cakupan divisi == MRO tidak ada (status & pesan identik)
    m6, l6 = mro(M, f"MRO-6-{u}", 4)  # Divisi A, masih ada sisa
    sc, wB = call("POST", "master/warehouses", {"code": f"WB{u}", "name": "Gudang Div B", "division_id": dB["id"], "is_active": True})
    sc, itB = call("POST", "master/items", {"code": f"IB{u}", "name": "Barang Div B", "unit": "PCS", "is_active": True,
                                            "category_id": M["cat"]["id"], "division_id": dB["id"], "base_uom_id": M["uom"]["id"]})
    def ro_b(item_id, srcs):
        return {"division_id": dB["id"], "lines": [{"item_id": item_id, "qty": 1, "uom_id": M["uom"]["id"], "warehouse_id": (wB or {}).get("id"), "sources": srcs}]}
    fake = {"mro_id": str(uuid.uuid4()), "line_id": str(uuid.uuid4()), "qty": 1, "base_qty": 1}
    r_foreign_same_item = ub("POST", "ro", ro_b(M["item"]["id"], [src(m6, l6, 1)]))
    r_foreign_other_item = ub("POST", "ro", ro_b((itB or {}).get("id") or M["item2"]["id"], [src(m6, l6, 1)]))
    r_missing = ub("POST", "ro", ro_b(M["item"]["id"], [fake]))
    check("disclosure divisi: MRO divisi lain (barang sama) == tidak ada", r_foreign_same_item[0] == r_missing[0] == 404 and r_foreign_same_item[1] == r_missing[1],
          (r_foreign_same_item, r_missing))
    check("disclosure divisi: MRO divisi lain (barang beda) == tidak ada", r_foreign_other_item[0] == r_missing[0] and r_foreign_other_item[1] == r_missing[1],
          (r_foreign_other_item, r_missing))
    # admin (global) tetap mendapat pesan bisnis jelas untuk MRO yang memang dapat diakses
    sc, r = call("POST", "ro", ro_body(M, "item", 1, [{**src(m6, l6, 1), "mro_id": m1["id"]}]))
    check("mro_id tidak cocok dengan baris MRO -> pesan generik", sc == 404 and "tidak dapat diakses" in str(r), (sc, r))

    # --- tenant isolation: tenant lain tidak dapat menarik baris MRO tenant ini
    import requests
    sess_a = T.S
    T.S = requests.Session()  # sesi bersih (tanpa cookie/token tenant A)
    M2 = T.setup()
    sc, me = call("GET", "auth/me")
    check("tenant isolation: login tenant B terpisah", sc == 200 and T.S.headers.get("Authorization") not in (None, "Bearer None"), (sc, me))
    sc, r = call("POST", "ro", ro_body(M2, "item", 1, [src(m4, l4, 1)]))
    sc2, rows2 = call("GET", "pull/mro-for-ro")
    check("tenant isolation: MRO tenant lain ditolak & tidak tampil", sc in (400, 403, 404) and not any(x.get("line_id") == l4["id"] for x in rows2), (sc, r, sc2, [x.get("line_id") for x in rows2 or []][:5]))
    fake = {"mro_id": str(uuid.uuid4()), "line_id": str(uuid.uuid4()), "qty": 1, "base_qty": 1}
    miss = call("POST", "ro", ro_body(M2, "item", 1, [fake]))
    check("disclosure tenant (create): MRO tenant lain == tidak ada", (sc, r) == miss and sc == 404, ((sc, r), miss))
    # edit RO milik tenant B dengan sumber tenant A vs sumber fiktif -> identik
    sc, own = call("POST", "ro", {"division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 1, "uom_id": M2["uom"]["id"], "warehouse_id": M2["wh"]["id"]}]}, 200)
    def put_src(s):
        return call("PUT", f"transactions/ro/{own['id']}", {"division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 1, "uom_id": M2["uom"]["id"], "warehouse_id": M2["wh"]["id"], "sources": [s]}]})
    pf, pm = put_src(src(m4, l4, 1)), put_src(fake)
    check("disclosure tenant (edit): MRO tenant lain == tidak ada", pf == pm and pf[0] == 404, (pf, pm))
    T.S = sess_a

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
