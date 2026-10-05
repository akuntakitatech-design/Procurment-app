"""PO dari RO terkonsolidasi — supplier split / PO parsial (throwaway tenant, localhost, dev DB)."""
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
from vendor_invoice_test import mk_user  # noqa: E402
from ro_consolidation_test import mro, src  # noqa: E402

call, check = T.call, T.check


def mk_item(M, code, name, primary=None, div=None):
    body = {"code": code, "name": name, "unit": "PCS", "is_active": True, "category_id": M["cat"]["id"],
            "division_id": div or M["div"]["id"], "base_uom_id": M["uom"]["id"]}
    if primary:
        body["primary_supplier_id"] = primary
    return call("POST", "master/items", body, 200)[1]


def mk_ro(M, lines, div=None):
    """lines: [(item, qty, [(mro_doc, mro_line, qty)])]"""
    body = {"division_id": div or M["div"]["id"], "lines": [
        {"item_id": it["id"], "qty": q, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"],
         "sources": [src(d, ml, sq) for d, ml, sq in srcs]} for it, q, srcs in lines]}
    sc, ro = call("POST", "ro", body, 200)
    call("POST", f"ro/{ro['id']}/submit", {})
    return ro


def po_body(M, supplier, lines, div=None):
    """lines: [(item, qty, [ {ro_id,line_id,qty[,ro_alloc_id]} ])]"""
    return {"supplier_id": supplier["id"] if isinstance(supplier, dict) else supplier, "division_id": div if div is not None else M["div"]["id"],
            "lines": [{"item_id": it["id"], "qty": q, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"],
                       "price": 1000, "sources": srcs} for it, q, srcs in lines]}


def rs(ro, line, qty, via=None):
    s = {"ro_id": ro["id"], "line_id": line["id"], "qty": qty, "base_qty": qty}
    if via:
        s["ro_alloc_id"] = via
    return s


def pull_row(line_id):
    sc, rows = call("GET", "pull/ro-for-po")
    return next((r for r in rows or [] if r.get("line_id") == line_id), None)


def spk_of(po_id):
    sc, al = call("GET", f"spk-allocations/po/doc/{po_id}")
    return [{a.get("spk_number"): a.get("allocated_qty") for a in (ln.get("allocations") or [])} for ln in al.get("lines") or []]


def main():
    M = T.setup()
    T.M = M
    import vendor_invoice_test as V
    V.M = M
    u = uuid.uuid4().hex[:5]
    supX, supY = M["supX"], M["supY"]
    sc, spkA = call("POST", "spk", {"spk_number": f"SPK-A-{u}", "project_name": "Proyek A", "spk_value": 10**9, "procurement_budget": 10**9, "status": "active"}, 200)
    sc, spkB = call("POST", "spk", {"spk_number": f"SPK-B-{u}", "project_name": "Proyek B", "spk_value": 10**9, "procurement_budget": 10**9, "status": "active"}, 200)
    bolt = mk_item(M, f"BLT{u}", "Baut M10", primary=supX["id"])
    oli = mk_item(M, f"OLI{u}", "Oli Mesin", primary=supY["id"])
    bearing = mk_item(M, f"BRG{u}", "Bearing 6205")
    M["bolt"], M["oli"], M["bearing"] = bolt, oli, bearing
    # kontrak harga aktif supplier Y untuk bearing (engine kontrak existing)
    sc, vc = call("POST", "vendor-contracts", {"supplier_id": supY["id"], "contract_number": f"KHV-{u}", "start_date": "2020-01-01", "end_date": "2099-12-31"}, 200)
    call("POST", f"vendor-contracts/{vc['id']}/items", {"item_id": bearing["id"], "uom_id": M["uom"]["id"], "base_price": 50000}, 200)
    call("POST", f"vendor-contracts/{vc['id']}/activate", {}, 200)

    m1, l1 = mro(M, f"MRO-1-{u}", 60, item="bolt", project="pa")
    m2, l2 = mro(M, f"MRO-2-{u}", 40, item="bolt", project="pb")
    m3, l3 = mro(M, f"MRO-3-{u}", 30, item="oli")
    m4, l4 = mro(M, f"MRO-4-{u}", 20, item="bearing")
    call("PUT", f"spk-allocations/mro/line/{l1['id']}", {"allocations": [{"spk_id": spkA["id"], "allocated_qty": 60}]}, 200)
    call("PUT", f"spk-allocations/mro/line/{l2['id']}", {"allocations": [{"spk_id": spkB["id"], "allocated_qty": 40}]}, 200)
    ro1 = mk_ro(M, [(bolt, 100, [(m1, l1, 60), (m2, l2, 40)]), (oli, 30, [(m3, l3, 30)]), (bearing, 20, [(m4, l4, 20)])])
    by_item = {l["item_id"]: l for l in ro1["lines"]}
    RB, RO_, RG = by_item[bolt["id"]], by_item[oli["id"]], by_item[bearing["id"]]
    sc, dB = call("POST", "master/divisions", {"code": f"DB{u}", "name": "Divisi B"}, 200)
    sc, whB = call("POST", "master/warehouses", {"code": f"WB{u}", "name": "Gudang B", "division_id": dB["id"], "is_active": True})
    boltB = mk_item(M, f"BLB{u}", "Baut Divisi B", div=dB["id"])
    M["boltB"] = boltB
    mb, lb = mro(M, f"MRO-B-{u}", 9, div=dB["id"], item="boltB")
    roB = mk_ro(M, [(boltB, 9, [(mb, lb, 9)])], div=dB["id"])

    # --- 1. Tarik RO: rekomendasi supplier & rincian sumber
    rb, rg, ro_oli = pull_row(RB["id"]), pull_row(RG["id"]), pull_row(RO_["id"])
    check("pull: kolom RO/Divisi/Qty/Sudah/Sisa/Satuan/MRO/SPK tersedia (human readable)",
          rb and rb.get("ro_no") == ro1["no"] and rb.get("division_name") and rb.get("qty_ro_base") == 100 and rb.get("ordered_base") == 0
          and rb.get("outstanding_base") == 100 and rb.get("base_unit") and sorted(rb.get("mro_nos") or []) == sorted([f"MRO-1-{u}", f"MRO-2-{u}"])
          and f"SPK-A-{u}" in rb.get("spk_label", "") and f"SPK-B-{u}" in rb.get("spk_label", "") and rb.get("po_status") == "Belum PO", rb)
    check("rekomendasi: Supplier Utama ditampilkan (Baut -> Supplier X)", rb and rb["recommended_supplier"]["supplier_id"] == supX["id"]
          and rb["recommended_supplier"]["source"] == "Supplier Utama" and rb.get("primary_supplier_name") == supX["name"], rb and rb.get("recommended_supplier"))
    check("rekomendasi: Kontrak Aktif didahulukan (Bearing -> Supplier Y, kontrak)", rg and rg["recommended_supplier"]["source"] == "Kontrak Aktif"
          and rg["recommended_supplier"]["supplier_id"] == supY["id"] and (rg.get("contract_suppliers") or [{}])[0].get("contract_number") == f"KHV-{u}", rg)
    check("rekomendasi Oli -> Supplier Y (grouping supplier berbeda)", ro_oli and ro_oli["recommended_supplier"]["supplier_id"] == supY["id"], ro_oli)
    via = {s["mro_no"]: s["ro_alloc_id"] for s in rb["sources"]}

    # --- 2. validasi
    sc, r = call("POST", "po", po_body(M, supX, [(bolt, 5, [rs(ro1, RB, 5)]), (boltB, 1, [rs(roB, roB["lines"][0], 1)])]))
    check("tolak: satu PO multi-divisi", sc == 400 and "Divisi" in str(r), (sc, r))
    b = po_body(M, supX, [(bolt, 5, [rs(ro1, RB, 5)])]); b["lines"][0]["supplier_id"] = supY["id"]
    sc, r = call("POST", "po", b)
    check("tolak: satu PO multi-supplier", sc == 400 and "Supplier" in str(r), (sc, r))
    sc, r = call("POST", "po", po_body(M, "", [(bolt, 5, [rs(ro1, RB, 5)])]))
    check("tolak: PO dari RO tanpa supplier", sc == 400 and "Supplier" in str(r), (sc, r))
    sc, r = call("POST", "po", po_body(M, supX, [(bolt, 101, [rs(ro1, RB, 101)])]))
    check("tolak: over-allocation Qty ke PO > Sisa PO", sc == 400 and "melebihi" in str(r), (sc, r))
    sc, r = call("POST", "po", po_body(M, supX, [(bolt, 50, [rs(ro1, RB, 50, via[f"MRO-2-{u}"])])]))
    check("tolak: alokasi sumber > sisa sumber (MRO-2 sisa 40)", sc == 400 and "melebihi" in str(r), (sc, r))
    sc, r = call("POST", "po", po_body(M, supX, [(bolt, 30, [rs(ro1, RB, 20)])]))
    check("tolak: total rincian != Qty PO", sc == 400 and "Rincian" in str(r), (sc, r))
    sc, r = call("POST", "po", po_body(M, supX, [(oli, 5, [rs(ro1, RB, 5)])]))
    check("tolak: barang PO beda dengan barang RO", sc == 400, (sc, r))

    # --- 3. RO -> Supplier X parsial 60 (proposal otomatis FIFO: MRO-1 / SPK-A)
    sc, poA = call("POST", "po", po_body(M, supX, [(bolt, 60, [rs(ro1, RB, 60)])]), 200)
    ln = (poA.get("lines") or [{}])[0]
    ent = ln.get("ro_sources") or []
    check("PO parsial 60: rincian sumber = MRO-1 / SPK-A (traceability PO->RO->MRO->SPK)",
          len(ent) == 1 and ent[0].get("mro_no") == f"MRO-1-{u}" and ent[0].get("spk_label") == f"SPK-A-{u}" and ent[0].get("qty") == 60
          and ent[0].get("ro_no") == ro1["no"] and ent[0].get("attributed"), ent)
    check("SPK PO diwariskan per sumber: SPK-A = 60", spk_of(poA["id"]) == [{f"SPK-A-{u}": 60}], spk_of(poA["id"]))
    sc, rv = call("GET", f"ro/{ro1['id']}")
    rvl = {l["item_id"]: l for l in rv["lines"]}
    check("status RO item: PO Sebagian (Sudah PO 60, Sisa 40)", rvl[bolt["id"]].get("po_status") == "PO Sebagian" and rvl[bolt["id"]].get("po_ordered") == 60
          and rvl[bolt["id"]].get("po_remaining") == 40, rvl[bolt["id"]])
    rb = pull_row(RB["id"])
    check("pull setelah PO: Sudah PO 60, Sisa 40, sumber MRO-1 habis", rb and rb.get("ordered_base") == 60 and rb.get("outstanding_base") == 40
          and {s["mro_no"]: s["sisa"] for s in rb["sources"]} == {f"MRO-1-{u}": 0, f"MRO-2-{u}": 40}, rb and rb.get("sources"))

    # --- 4. sisa 40 ke Supplier Y (manual berbeda dari Supplier Utama X) + Oli dalam PO yang sama
    sc, poB = call("POST", "po", po_body(M, supY, [(bolt, 40, [rs(ro1, RB, 40, via[f"MRO-2-{u}"])]), (oli, 30, [rs(ro1, RO_, 30)])]))
    check("1 RO -> beberapa supplier: sisa 40 ke Supplier Y (manual) berhasil", sc == 200 and poB.get("supplier_id") == supY["id"], (sc, poB))
    check("SPK PO-B per sumber: SPK-B = 40 (tidak meminjam SPK-A)", spk_of(poB["id"])[0] == {f"SPK-B-{u}": 40}, spk_of(poB["id"]))
    sc, items = call("GET", "master/items")
    items = items.get("items", items) if isinstance(items, dict) else items
    it = next((x for x in items or [] if x.get("id") == bolt["id"]), {})
    check("Supplier Utama Master Barang tidak berubah", it.get("primary_supplier_id") == supX["id"], it)
    sc, rv = call("GET", f"ro/{ro1['id']}")
    rvl = {l["item_id"]: l for l in rv["lines"]}
    check("status RO item: Sudah PO Penuh", rvl[bolt["id"]].get("po_status") == "Sudah PO Penuh" and rvl[oli["id"]].get("po_status") == "Sudah PO Penuh", rvl[bolt["id"]].get("po_status"))
    check("pull: baris RO penuh tidak ditawarkan lagi", pull_row(RB["id"]) is None)
    sc, r = call("POST", "po", po_body(M, supX, [(bolt, 1, [rs(ro1, RB, 1)])]))
    check("tolak: over-allocation setelah penuh", sc == 400 and "melebihi" in str(r), (sc, r))

    # --- 5. edit
    sc, r = call("PUT", f"transactions/po/{poA['id']}", {**po_body(M, supX, []), "lines": [{"id": ln["id"], "item_id": bolt["id"], "qty": 50, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"], "price": 1000}]})
    check("edit: Qty berubah tanpa rincian ditolak", sc == 400 and "Rincian" in str(r), (sc, r))
    resend = [rs(ro1, RB, e["qty"] - 10, e["ro_alloc_id"]) for e in ent]
    sc, r = call("PUT", f"transactions/po/{poA['id']}", {**po_body(M, supX, []), "lines": [{"id": ln["id"], "item_id": bolt["id"], "qty": 50, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"], "price": 1000, "sources": resend}]})
    sc2, pa = call("GET", f"po/{poA['id']}")
    la = (pa.get("lines") or [{}])[0]
    check("edit: Qty 60 -> 50 dengan rincian seimbang, sumber/SPK tetap", sc == 200 and la.get("qty") == 50 and [e.get("mro_no") for e in la.get("ro_sources") or []] == [f"MRO-1-{u}"]
          and spk_of(poA["id"]) == [{f"SPK-A-{u}": 50}] and pa.get("supplier_id") == supX["id"] and pa.get("division_id") == M["div"]["id"], (sc, r, la.get("ro_sources"), spk_of(poA["id"])))
    sc, r = call("PUT", f"transactions/po/{poA['id']}", {**po_body(M, supX, []), "lines": [{"id": la["id"], "item_id": bolt["id"], "qty": 50, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"], "price": 1000}]})
    sc2, pa2 = call("GET", f"po/{poA['id']}")
    e2 = ((pa2.get("lines") or [{}])[0]).get("ro_sources") or []
    check("edit tanpa rincian (qty sama): atribusi sumber tidak hilang", sc == 200 and len(e2) == 1 and e2[0].get("attributed") and e2[0].get("mro_no") == f"MRO-1-{u}", (sc, r, e2))
    rb = pull_row(RB["id"])
    check("setelah edit: Sisa PO baris RO = 10 (dari MRO-1)", rb and rb.get("outstanding_base") == 10 and {s["mro_no"]: s["sisa"] for s in rb["sources"]}[f"MRO-1-{u}"] == 10, rb and rb.get("sources"))

    # --- 6. cancel / reversal
    call("POST", f"po/{poB['id']}/cancel", {}, 200)
    call("POST", f"po/{poB['id']}/cancel", {})
    rb = pull_row(RB["id"])
    sc, rv = call("GET", f"ro/{ro1['id']}")
    check("cancel PO-B: Sudah PO turun, sisa MRO-2 kembali 40, status PO Sebagian",
          rb and rb.get("outstanding_base") == 50 and {s["mro_no"]: s["sisa"] for s in rb["sources"]}[f"MRO-2-{u}"] == 40
          and {l["item_id"]: l for l in rv["lines"]}[bolt["id"]].get("po_status") == "PO Sebagian" and {l["item_id"]: l for l in rv["lines"]}[oli["id"]].get("po_status") == "Belum PO", (rb and rb.get("sources"), rv["lines"]))

    # --- 7. concurrency (paralel, sisa bearing 20)
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(lambda _: call("POST", "po", po_body(M, supY, [(bearing, 20, [rs(ro1, RG, 20)])])), range(5)))
    oks = [x for x in res if x[0] == 200]
    check("concurrency: 5 PO paralel atas sisa 20 -> tepat 1 berhasil", len(oks) == 1 and pull_row(RG["id"]) is None, [x[0] for x in res])

    # --- 8. legacy body (tanpa ro_alloc_id) tetap didukung & PO lama dapat dibuka
    sc, poL = call("POST", "po", {"supplier_id": supY["id"], "division_id": M["div"]["id"], "lines": [{"item_id": bolt["id"], "qty": 30, "uom_id": M["uom"]["id"], "price": 1000,
                                                                                                    "sources": [{"ro_id": ro1["id"], "line_id": RB["id"], "qty": 30}]}]})
    lL = (poL.get("lines") or [{}])[0]
    check("legacy body: proposal otomatis FIFO (MRO-1 10 + MRO-2 20) & SPK per sumber", sc == 200 and sorted((e["mro_no"], e["qty"]) for e in lL.get("ro_sources") or []) == [(f"MRO-1-{u}", 10), (f"MRO-2-{u}", 20)]
          and spk_of(poL["id"]) == [{f"SPK-A-{u}": 10, f"SPK-B-{u}": 20}], (sc, lL.get("ro_sources"), spk_of(poL.get("id"))))

    # --- 9. stok tidak berubah
    sc, cA0 = call("GET", f"spk-allocations/spk/{spkA['id']}/commitment")
    check("SPK commitment: PO Draft tidak mengubah commitment SPK", sc == 200 and int(cA0.get("commitment") or 0) == 0, cA0.get("commitment"))
    call("POST", f"po/{poA['id']}/submit", {})
    sc, pa3 = call("GET", f"po/{poA['id']}")
    if pa3.get("status") == "Waiting Approval":
        call("POST", f"po/{poA['id']}/approve", {})
        sc, pa3 = call("GET", f"po/{poA['id']}")
    sc, cA1 = call("GET", f"spk-allocations/spk/{spkA['id']}/commitment")
    sc, cB1 = call("GET", f"spk-allocations/spk/{spkB['id']}/commitment")
    check("SPK commitment: PO Approved -> commit ke SPK-A sesuai nilai PO (formula existing), SPK-B tidak",
          pa3.get("status") == "Approved" and int(cA1.get("commitment") or 0) == round(float(pa3.get("grand_total") or 0)) and int(cB1.get("commitment") or 0) == 0,
          (pa3.get("status"), cA1.get("commitment"), pa3.get("grand_total"), cB1.get("commitment")))
    sc, st = call("GET", f"stock/by-warehouse/{bolt['id']}")
    check("PO tidak mengubah stok", all((w.get("stock") or 0) == 0 for w in st.get("warehouses") or []), st)

    # --- 10. division scope & disclosure
    ub = mk_user("purchasing", divs=[dB["id"]])
    fake = {"ro_id": str(uuid.uuid4()), "line_id": str(uuid.uuid4()), "qty": 1}
    a1 = ub("POST", "po", {"supplier_id": supX["id"], "division_id": dB["id"], "lines": [{"item_id": bolt["id"], "qty": 1, "uom_id": M["uom"]["id"], "sources": [rs(ro1, RB, 1)]}]})
    a2 = ub("POST", "po", {"supplier_id": supX["id"], "division_id": dB["id"], "lines": [{"item_id": boltB["id"], "qty": 1, "uom_id": M["uom"]["id"], "sources": [rs(ro1, RB, 1)]}]})
    a3 = ub("POST", "po", {"supplier_id": supX["id"], "division_id": dB["id"], "lines": [{"item_id": bolt["id"], "qty": 1, "uom_id": M["uom"]["id"], "sources": [fake]}]})
    check("division scope: RO divisi lain == tidak ada (barang sama/beda, pesan identik 404)", a1[0] == a2[0] == a3[0] == 404 and a1[1] == a2[1] == a3[1], (a1, a2, a3))
    sc, rows = ub("GET", "pull/ro-for-po")
    check("division scope: Tarik RO hanya RO divisi user", all(r.get("division_id") == dB["id"] for r in rows or []) and any(r.get("line_id") == roB["lines"][0]["id"] for r in rows or []), [r.get("division_name") for r in rows or []][:5])

    # --- 11. tenant isolation
    sess_a = T.S
    T.S = requests.Session()
    M2 = T.setup()
    p1 = call("POST", "po", {"supplier_id": M2["supX"]["id"], "division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 1, "uom_id": M2["uom"]["id"], "sources": [rs(ro1, RB, 1)]}]})
    p2 = call("POST", "po", {"supplier_id": M2["supX"]["id"], "division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 1, "uom_id": M2["uom"]["id"], "sources": [fake]}]})
    check("tenant isolation (create): RO tenant lain == tidak ada", p1 == p2 and p1[0] == 404, (p1, p2))
    sc, own = call("POST", "po", {"supplier_id": M2["supX"]["id"], "division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 1, "uom_id": M2["uom"]["id"], "price": 1}]}, 200)
    def put_src(s):
        return call("PUT", f"transactions/po/{own['id']}", {"supplier_id": M2["supX"]["id"], "division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 1, "uom_id": M2["uom"]["id"], "price": 1, "sources": [s]}]})
    q1, q2 = put_src(rs(ro1, RB, 1)), put_src(fake)
    check("tenant isolation (edit): RO tenant lain == tidak ada", q1 == q2 and q1[0] == 404, (q1, q2))
    sc, rows2 = call("GET", "pull/ro-for-po")
    check("tenant isolation: Tarik RO tenant lain kosong", not any(r.get("ro_id") == ro1["id"] for r in rows2 or []))
    T.S = sess_a

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
