"""Source picker / current-form reservation + aggregate source guard (RO<-MRO, PO<-RO, DO<-PO, MI<-MRO).

Throwaway tenant (saas/register) on localhost dev DB. Covers:
- pull endpoints: source fully used by a saved doc disappears; partial shows remaining;
- Edit: ?current_doc_id= excludes ONLY the edited doc's allocations (no double subtraction),
  allocations of other docs still reduce availability;
- current_doc_id validation: unknown / other tenant -> 404, other division -> 403/404;
- API tampering: 2 target lines on the same source with total > available -> rejected (create & edit),
  total <= available -> consistent consumption (allocations == requested, no double count);
- concurrency: parallel docs competing for the same remainder never exceed the source.
Frontend reservation rules (hide / partial / qty change / delete / merge) are covered by
frontend/src/lib/sourceReservation.test.mjs (run via node, see main()).
"""
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/app/backend/tests")
import receipt_control_test as T  # noqa: E402
import vendor_invoice_test as V  # noqa: E402
from ro_consolidation_test import mro, src  # noqa: E402

call, check = T.call, T.check
EPS = 1e-6


def rows(path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items() if v)
    sc, data = call("GET", f"{path}{'?' + q if q else ''}")
    return sc, (data if isinstance(data, list) else [])


def row_of(path, line_id, **params):
    return next((r for r in rows(path, **params)[1] if r.get("line_id") == line_id), None)


def ro_line_body(M, qty, sources, line_id=None):
    l = {"item_id": M["item"]["id"], "qty": qty, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"], "sources": sources}
    if line_id:
        l["id"] = line_id
    return l


def ro_body(M, lines):
    return {"division_id": M["div"]["id"], "lines": lines}


def po_line(M, qty, srcs):
    return {"item_id": M["item"]["id"], "qty": qty, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"], "price": 1000, "sources": srcs}


def po_body(M, lines):
    return {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "lines": lines}


def rsrc(ro, rl, q):
    return {"ro_id": ro["id"], "line_id": rl["id"], "qty": q, "base_qty": q}


def do_line(po, q, reason=None):
    l = po["lines"][0]
    out = {"po_id": po["id"], "po_line_id": l["id"], "item_id": l["item_id"], "qty": q, "uom_id": l.get("uom_id"),
           "warehouse_id": l.get("warehouse_id"), "project_id": l.get("project_id"), "notes": l.get("notes"),
           "condition": "Baik", "exception_qty": 0, "sources": [{"po_id": po["id"], "line_id": l["id"], "qty": q}]}
    if reason:
        out["over_receipt_reason"] = reason
    return out


def do_body(M, lines):
    return {"supplier_id": M["supX"]["id"], "supplier_dn": f"SJ-{uuid.uuid4().hex[:6]}", "default_warehouse_id": M["wh"]["id"], "lines": lines}


def mi_line(M, d, ml, q):
    return {"item_id": M["item"]["id"], "qty": q, "uom_id": M["uom"]["id"], "conversion_factor": 1, "warehouse_id": M["wh"]["id"],
            "mro_id": d["id"], "mro_line_id": ml["id"], "sources": [{"mro_id": d["id"], "line_id": ml["id"], "qty": q, "base_qty": q}]}


def mi_body(M, lines):
    return {"division_id": M["div"]["id"], "source_type": "MRO", "default_warehouse_id": M["wh"]["id"], "lines": lines}


def fresh_mro(M, qty):
    return mro(M, f"MRO-SP-{uuid.uuid4().hex[:6]}", qty)


def main():
    M = T.setup()
    T.M = M
    V.M = M
    u = uuid.uuid4().hex[:5]

    # ================================================================== A. RO <- MRO
    d1, l1 = fresh_mro(M, 10)
    r = row_of("pull/mro-for-ro", l1["id"])
    check("RO: MRO sisa 10 tampil di picker", r and abs(float(r.get("outstanding_base", r.get("outstanding"))) - 10) < EPS, r)
    sc, roA = call("POST", "ro", ro_body(M, [ro_line_body(M, 10, [src(d1, l1, 10)])]), 200)
    check("RO: simpan RO tarik penuh 10", sc == 200)
    check("RO: setelah ditarik penuh, sumber hilang dari picker", row_of("pull/mro-for-ro", l1["id"]) is None)
    r = row_of("pull/mro-for-ro", l1["id"], current_doc_id=roA["id"])
    check("RO Edit: current_doc_id -> sumber milik RO ini tampil lagi dengan sisa 10 (tanpa double subtraction)",
          r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    # alokasi dokumen lain tetap mengurangi
    d2, l2 = fresh_mro(M, 10)
    sc, roB = call("POST", "ro", ro_body(M, [ro_line_body(M, 6, [src(d2, l2, 6)])]), 200)
    sc, roC = call("POST", "ro", ro_body(M, [ro_line_body(M, 1, [src(d2, l2, 1)])]), 200)
    r = row_of("pull/mro-for-ro", l2["id"])
    check("RO: tarik 6 + 1 tersimpan -> sisa 3", r and abs(float(r["outstanding_base"]) - 3) < EPS, r)
    r = row_of("pull/mro-for-ro", l2["id"], current_doc_id=roC["id"])
    check("RO Edit (RO C): alokasi RO B (dokumen lain) tetap mengurangi -> sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    # tampering create: dua baris RO dari sumber MRO yang sama 6 + 6 > 10
    d3, l3 = fresh_mro(M, 10)
    sc, _ = call("POST", "ro", ro_body(M, [ro_line_body(M, 6, [src(d3, l3, 6)]), ro_line_body(M, 6, [src(d3, l3, 6)])]))
    check("RO tamper create: 2 baris sumber sama 6+6 > 10 ditolak", sc == 400, sc)
    check("RO tamper create: tidak ada konsumsi parsial (sisa tetap 10)", abs(float((row_of("pull/mro-for-ro", l3["id"]) or {}).get("outstanding_base", -1)) - 10) < EPS)
    sc, roD = call("POST", "ro", ro_body(M, [ro_line_body(M, 6, [src(d3, l3, 6)]), ro_line_body(M, 4, [src(d3, l3, 4)])]), 200)
    check("RO duplikat total <= sisa (6+4) diterima", sc == 200)
    check("RO duplikat 6+4: konsumsi konsisten (sumber habis, bukan ganda)", row_of("pull/mro-for-ro", l3["id"]) is None)
    r = row_of("pull/mro-for-ro", l3["id"], current_doc_id=roD["id"])
    check("RO Edit duplikat: sisa untuk dokumen ini = 10 (bukan 20 / 0)", r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    sc, roDd = call("GET", f"ro/{roD['id']}")
    ids = [x["id"] for x in roDd["lines"]]
    sc, _ = call("PUT", f"transactions/ro/{roD['id']}", ro_body(M, [ro_line_body(M, 6, [src(d3, l3, 6)], ids[0]), ro_line_body(M, 6, [src(d3, l3, 6)], ids[1])]))
    check("RO tamper edit: 6+6 > 10 ditolak", sc == 400, sc)

    # ================================================================== B. PO <- RO
    d4, l4 = fresh_mro(M, 10)
    sc, ro4 = call("POST", "ro", ro_body(M, [ro_line_body(M, 10, [src(d4, l4, 10)])]), 200)
    call("POST", f"ro/{ro4['id']}/submit", {})
    rl4 = ro4["lines"][0]
    r = row_of("pull/ro-for-po", rl4["id"])
    check("PO: RO sisa 10 tampil", r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    sc, poA = call("POST", "po", po_body(M, [po_line(M, 6, [rsrc(ro4, rl4, 6)])]), 200)
    r = row_of("pull/ro-for-po", rl4["id"])
    check("PO: tarik 6 tersimpan -> sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    r = row_of("pull/ro-for-po", rl4["id"], current_doc_id=poA["id"])
    check("PO Edit: current_doc_id -> sisa untuk PO ini 10", r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    check("PO Edit: rincian sumber sisa ikut dihitung tanpa PO ini", r and abs(sum(float(s.get("sisa") or 0) for s in r.get("sources") or []) - 10) < EPS, r)
    sc, _ = call("POST", "po", po_body(M, [po_line(M, 3, [rsrc(ro4, rl4, 3)]), po_line(M, 3, [rsrc(ro4, rl4, 3)])]))
    check("PO tamper create: 2 baris sumber RO sama 3+3 > sisa 4 ditolak", sc == 400, sc)
    sc, poB = call("POST", "po", po_body(M, [po_line(M, 2, [rsrc(ro4, rl4, 2)]), po_line(M, 2, [rsrc(ro4, rl4, 2)])]), 200)
    check("PO duplikat 2+2 <= sisa 4 diterima & konsisten (sumber habis)", sc == 200 and row_of("pull/ro-for-po", rl4["id"]) is None)
    r = row_of("pull/ro-for-po", rl4["id"], current_doc_id=poB["id"])
    check("PO Edit (PO B): alokasi PO A tetap mengurangi -> sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    sc, poBd = call("GET", f"po/{poB['id']}")
    pl = [x["id"] for x in poBd["lines"]]
    tam = po_body(M, [dict(po_line(M, 3, [rsrc(ro4, rl4, 3)]), id=pl[0]), dict(po_line(M, 3, [rsrc(ro4, rl4, 3)]), id=pl[1])])
    sc, _ = call("PUT", f"transactions/po/{poB['id']}", tam)
    check("PO tamper edit: 3+3 > sisa 4 ditolak", sc == 400, sc)

    # ================================================================== C. DO <- PO
    po, _, _ = T.make_po(M, "supX", 10)
    pl0 = po["lines"][0]
    r = row_of("pull/po-for-do", pl0["id"])
    check("DO: PO outstanding 10 tampil", r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    sc, doA = call("POST", "do", do_body(M, [do_line(po, 6)]), 200)
    r = row_of("pull/po-for-do", pl0["id"])
    check("DO: terima 6 -> sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    sc, _ = call("POST", "do", do_body(M, [do_line(po, 3), do_line(po, 3)]))
    check("DO tamper create: 2 baris PO line sama 3+3 > sisa 4 tanpa alasan ditolak", sc == 400, sc)
    sc, doB = call("POST", "do", do_body(M, [do_line(po, 4)]), 200)
    check("DO: diterima penuh -> sumber hilang dari picker", row_of("pull/po-for-do", pl0["id"]) is None)
    r = row_of("pull/po-for-do", pl0["id"], current_doc_id=doB["id"])
    check("DO Edit (PO Fully Received oleh DO ini): sisa untuk DO ini 4 (DO A tetap mengurangi)", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    sc, doBd = call("GET", f"do/{doB['id']}")
    dl = doBd["lines"][0]["id"]
    sc, _ = call("PUT", f"transactions/do/{doB['id']}", do_body(M, [dict(do_line(po, 3), id=dl), do_line(po, 3)]))
    check("DO tamper edit: 3+3 > sisa 4 tanpa alasan ditolak", sc == 400, sc)
    po2, _, _ = T.make_po(M, "supX", 10)
    sc, doO = call("POST", "do", do_body(M, [do_line(po2, 6, "Bonus supplier"), do_line(po2, 6, "Bonus supplier")]))
    check("DO Over Receipt existing tetap: 6+6 > 10 dengan alasan diterima", sc == 200, sc)

    # ================================================================== D. MI <- MRO (stok dari DO di atas: 20+)
    wh_user = V.mk_user("warehouse", divs=[M["div"]["id"]])
    d5, l5 = fresh_mro(M, 10)
    r = row_of("pull/mro-for-mi", l5["id"])
    check("MI: MRO sisa 10 tampil", r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    sc, before = call("GET", "mi")
    n_before = len(before) if isinstance(before, list) else (before or {}).get("total")
    sc, body = wh_user("POST", "mi", mi_body(M, [mi_line(M, d5, l5, 6), mi_line(M, d5, l5, 6)]))
    check("MI tamper create: 2 baris MRO sama 6+6 > 10 ditolak", sc == 400, (sc, body))
    sc, after = call("GET", "mi")
    n_after = len(after) if isinstance(after, list) else (after or {}).get("total")
    check("MI tamper create: tidak ada dokumen/stok parsial", n_before == n_after and abs(float(row_of("pull/mro-for-mi", l5["id"])["outstanding_base"]) - 10) < EPS)
    sc, miA = wh_user("POST", "mi", mi_body(M, [mi_line(M, d5, l5, 6)]))
    check("MI: issue 6 tersimpan", sc == 200, (sc, miA))
    r = row_of("pull/mro-for-mi", l5["id"])
    check("MI: sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    r = row_of("pull/mro-for-mi", l5["id"], current_doc_id=miA.get("id"))
    check("MI Edit: current_doc_id -> sisa untuk MI ini 10", r and abs(float(r["outstanding_base"]) - 10) < EPS, r)
    sc, miB = wh_user("POST", "mi", mi_body(M, [mi_line(M, d5, l5, 4)]))
    check("MI: issue penuh -> sumber hilang", sc == 200 and row_of("pull/mro-for-mi", l5["id"]) is None, sc)
    r = row_of("pull/mro-for-mi", l5["id"], current_doc_id=miB.get("id"))
    check("MI Edit (MI B): alokasi MI A tetap mengurangi -> sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    sc, miBd = call("GET", f"mi/{miB['id']}")
    ml = miBd["lines"][0]["id"]
    sc, _ = call("PUT", f"transactions/mi/{miB['id']}", mi_body(M, [dict(mi_line(M, d5, l5, 3), id=ml), mi_line(M, d5, l5, 3)]))
    check("MI tamper edit: 3+3 > sisa 4 ditolak (admin pun, validasi agregat edit)", sc == 400, sc)

    # ================================================================== E. current_doc_id validation
    sc, _ = call("GET", f"pull/ro-for-po?current_doc_id={uuid.uuid4()}")
    check("current_doc_id tidak dikenal -> 404", sc == 404, sc)
    sc, _ = call("GET", f"pull/ro-for-po?current_doc_id={roA['id']}")
    check("current_doc_id modul berbeda (RO pada pull PO) -> 404", sc == 404, sc)
    saved, saved_cookies = dict(T.S.headers), T.S.cookies.copy()
    T.S.headers.pop("Authorization", None); T.S.cookies.clear()
    M2 = T.setup()  # tenant lain (header sesi berganti ke tenant baru)
    d6, l6 = mro(M2, f"MRO-T2-{u}", 5)
    sc, ro_t2 = call("POST", "ro", {"division_id": M2["div"]["id"], "lines": [{"item_id": M2["item"]["id"], "qty": 5, "uom_id": M2["uom"]["id"], "conversion_factor": 1, "warehouse_id": M2["wh"]["id"], "sources": [src(d6, l6, 5)]}]}, 200)
    T.S.headers.clear(); T.S.headers.update(saved); T.S.cookies.clear(); T.S.cookies.update(saved_cookies)
    check("Tenant lain: dokumen dibuat di tenant berbeda (fixture valid)", ro_t2.get("id") and call("GET", f"ro/{ro_t2['id']}")[0] in (403, 404))
    sc, _ = call("GET", f"pull/mro-for-ro?current_doc_id={ro_t2['id']}")
    check("current_doc_id tenant lain -> 404 (tidak bisa mengecualikan dokumen tenant lain)", sc == 404, sc)
    sc, div2 = call("POST", "master/divisions", {"code": f"DX{u}", "name": "Divisi Lain"}, 200)
    other = V.mk_user("purchasing", divs=[div2["id"]])
    sc, _ = other("GET", f"pull/ro-for-po?current_doc_id={poA['id']}")
    check("current_doc_id dokumen di luar cakupan divisi -> 403/404", sc in (403, 404), sc)

    # ================================================================== F. concurrency
    d7, l7 = fresh_mro(M, 10)
    sc, ro7 = call("POST", "ro", ro_body(M, [ro_line_body(M, 10, [src(d7, l7, 10)])]), 200)
    call("POST", f"ro/{ro7['id']}/submit", {})
    rl7 = ro7["lines"][0]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: call("POST", "po", po_body(M, [po_line(M, 6, [rsrc(ro7, rl7, 6)])]))[0], range(4)))
    check("Concurrency PO: 4 PO paralel x6 dari RO 10 -> tepat 1 sukses", res.count(200) == 1, res)
    r = row_of("pull/ro-for-po", rl7["id"])
    check("Concurrency PO: sisa 4 (tidak pernah melebihi sumber)", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    po3, _, _ = T.make_po(M, "supX", 10)
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: call("POST", "do", do_body(M, [do_line(po3, 6)]))[0], range(4)))
    check("Concurrency DO: 4 DO paralel x6 dari PO 10 (tanpa alasan) -> tepat 1 sukses", res.count(200) == 1, res)
    d8, l8 = fresh_mro(M, 10)
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: wh_user("POST", "mi", mi_body(M, [mi_line(M, d8, l8, 6)]))[0], range(4)))
    check("Concurrency MI: 4 MI paralel x6 dari MRO 10 -> tepat 1 sukses", res.count(200) == 1, res)
    r = row_of("pull/mro-for-mi", l8["id"])
    check("Concurrency MI: sisa 4", r and abs(float(r["outstanding_base"]) - 4) < EPS, r)
    d9, l9 = fresh_mro(M, 10)
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: call("POST", "ro", ro_body(M, [ro_line_body(M, 6, [src(d9, l9, 6)])]))[0], range(4)))
    check("Concurrency RO: 4 RO paralel x6 dari MRO 10 -> tepat 1 sukses", res.count(200) == 1, res)

    # ================================================================== G. frontend reservation rules (node)
    js = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "lib", "sourceReservation.test.mjs")
    out = subprocess.run(["node", js], capture_output=True, text=True, timeout=60)
    for ln in out.stdout.splitlines():
        if ln.startswith(("PASS ", "FAIL ")):
            check("FE " + ln[5:], ln.startswith("PASS "))
    check("FE reservation test runner exit 0", out.returncode == 0, out.stderr[-500:])

    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\n{ok}/{len(T.RESULTS)} passed")
    sys.exit(0 if ok == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
