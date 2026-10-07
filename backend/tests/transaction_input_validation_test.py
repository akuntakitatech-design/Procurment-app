"""Validasi global input transaksi: Divisi wajib (+ warisan/kunci dari sumber) dan Qty > 0.

Throwaway tenant (receipt_control_test.setup). Menguji create, edit, direct API/tampering:
- Divisi kosong -> 400 "Divisi wajib diisi." (MRO/Transfer/Pinjam/Penyesuaian/Opname)
- RO/PO/DO/MI mewarisi Divisi sumber; divisi lain -> 400; sumber beda divisi -> 400
- Qty null/kosong/0/negatif/NaN/Infinity -> 400 "Qty harus lebih besar dari 0."
- Penyesuaian: +/- boleh, 0/kosong -> "Qty Penyesuaian tidak boleh 0."
- Stock Opname counted = 0 tetap valid (count + post)
"""
import sys
import uuid

import receipt_control_test as rc

call, check = rc.call, rc.check
DIV = "Divisi wajib diisi."
QTY = "Qty harus lebih besar dari 0."
ADJ = "Qty Penyesuaian tidak boleh 0."
LOCK = "Divisi harus mengikuti dokumen sumber"


def detail(r):
    return str((r or {}).get("detail", r))


def mro(M, qty=10, div=None, **over):
    body = {"no": f"MRO-V-{uuid.uuid4().hex[:6]}", "division_id": div if div is not None else M["div"]["id"], "requester": "Budi",
            "submitted": True, "lines": [{"item_id": M["item"]["id"], "qty": qty, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]}
    body.update(over)
    return call("POST", "mro", body)


def ro_body(m, qty, div=None, extra_sources=None):
    ml = m["lines"][0]
    sources = [{"mro_id": m["id"], "line_id": ml["id"], "qty": qty}] + (extra_sources or [])
    tot = sum(s["qty"] for s in sources)
    b = {"lines": [{"item_id": ml["item_id"], "qty": tot, "warehouse_id": ml.get("warehouse_id"), "sources": sources}]}
    if div is not None:
        b["division_id"] = div
    return b


def main():
    M = rc.setup()
    sc, divB = call("POST", "master/divisions", {"code": f"DVB{uuid.uuid4().hex[:6]}", "name": "Divisi B"}, 200)
    wh, wh2 = M["wh"]["id"], M["wh2"]["id"]

    # ---------- A. Divisi wajib (transaksi tanpa sumber)
    for label, div in (("tanpa field", None), ("kosong", ""), ("spasi", "   ")):
        b = {"no": f"MRO-X-{uuid.uuid4().hex[:5]}", "requester": "Budi", "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": wh}]}
        if div is not None:
            b["division_id"] = div
        sc, r = call("POST", "mro", b)
        check(f"MRO divisi {label} -> 400", sc == 400 and detail(r) == DIV, (sc, r))
    sc, r = call("POST", "adjustments", {"warehouse_id": wh, "reason": "x", "lines": [{"item_id": M["item"]["id"], "adjustment": 20, "approved_unit_cost": 1000}]})
    check("Penyesuaian tanpa divisi -> 400", sc == 400 and detail(r) == DIV, (sc, r))
    sc, adj = call("POST", "adjustments", {"warehouse_id": wh, "division_id": M["div"]["id"], "reason": "seed",
                                           "lines": [{"item_id": M["item"]["id"], "adjustment": 50, "approved_unit_cost": 1000}]})
    check("Penyesuaian + dengan divisi -> 200", sc == 200, (sc, adj))
    sc, r = call("POST", "transfers", {"from_warehouse_id": wh, "to_warehouse_id": wh2, "lines": [{"item_id": M["item"]["id"], "qty": 1}]})
    check("Transfer tanpa divisi -> 400", sc == 400 and detail(r) == DIV, (sc, r))
    sc, trf = call("POST", "transfers", {"from_warehouse_id": wh, "to_warehouse_id": wh2, "division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": 1}]})
    check("Transfer dengan divisi -> 200 & divisi tersimpan", sc == 200 and trf.get("division_id") == M["div"]["id"], (sc, trf.get("division_id")))
    sc, r = call("POST", "loans", {"from_warehouse_id": wh, "to_warehouse_id": wh2, "lines": [{"item_id": M["item"]["id"], "qty": 1}]})
    check("Pinjam tanpa divisi -> 400", sc == 400 and detail(r) == DIV, (sc, r))
    sc, loan = call("POST", "loans", {"from_warehouse_id": wh, "to_warehouse_id": wh2, "division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": 1}]})
    check("Pinjam dengan divisi -> 200 & divisi tersimpan", sc == 200 and loan.get("division_id") == M["div"]["id"], (sc, loan.get("division_id")))
    sc, r = call("POST", "opname", {"warehouse_id": wh, "mode": "live", "scope": "all"})
    check("Opname tanpa divisi -> 400", sc == 400 and detail(r) == DIV, (sc, r))
    sc, r = call("PUT", f"transactions/transfer/{trf['id']}", {"division_id": "", "from_warehouse_id": wh, "to_warehouse_id": wh2,
                                                              "lines": [{"item_id": M["item"]["id"], "qty": 1}]})
    check("Edit Transfer divisi dikosongkan -> 400", sc == 400 and detail(r) == DIV, (sc, r))

    # ---------- B. Qty normal > 0 (create)
    for label, q in (("0", 0), ("negatif", -1), ("null", None), ("kosong", ""), ("teks", "abc"), ("NaN", "NaN"), ("Infinity", "Infinity"), ("-0.0", -0.0)):
        sc, r = mro(M, qty=q)
        check(f"MRO qty {label} -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, r = call("POST", "mro", {"no": "MRO-NOQ", "division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "warehouse_id": wh}]})
    check("MRO qty tidak dikirim -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, r = call("POST", "transfers", {"from_warehouse_id": wh, "to_warehouse_id": wh2, "division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": 0}]})
    check("Transfer qty 0 -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, r = call("POST", "loans", {"from_warehouse_id": wh, "to_warehouse_id": wh2, "division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": -2}]})
    check("Pinjam qty negatif -> 400", sc == 400 and detail(r) == QTY, (sc, r))

    # ---------- C. Penyesuaian +/- boleh, 0/kosong ditolak
    for label, q in (("0", 0), ("kosong", ""), ("null", None), ("teks", "x")):
        sc, r = call("POST", "adjustments", {"warehouse_id": wh, "division_id": M["div"]["id"], "reason": "x",
                                             "lines": [{"item_id": M["item"]["id"], "adjustment": q, "approved_unit_cost": 1000}]})
        check(f"Penyesuaian qty {label} -> 400", sc == 400 and detail(r) == ADJ, (sc, r))
    sc, r = call("POST", "adjustments", {"warehouse_id": wh, "division_id": M["div"]["id"], "reason": "koreksi", "lines": [{"item_id": M["item"]["id"], "adjustment": -2}]})
    check("Penyesuaian minus -> 200", sc == 200, (sc, r))
    sc, r = call("PUT", f"transactions/adjustment/{adj['id']}", {"warehouse_id": wh, "division_id": M["div"]["id"], "reason": "seed",
                                                                 "lines": [{"item_id": M["item"]["id"], "adjustment": 0, "approved_unit_cost": 1000}]})
    check("Edit Penyesuaian qty 0 -> 400", sc == 400 and detail(r) == ADJ, (sc, r))

    # ---------- D. Opname counted = 0 tetap valid
    sc, opn = call("POST", "opname", {"warehouse_id": wh, "division_id": M["div"]["id"], "mode": "live", "scope": "all"})
    check("Opname dengan divisi -> 200", sc == 200 and opn.get("division_id") == M["div"]["id"], (sc, opn))
    ol = next((l for l in opn.get("lines", []) if l.get("item_id") == M["item"]["id"]), None) or (opn.get("lines") or [{}])[0]
    sc, r = call("PUT", f"opname/{opn['id']}/count", {"lines": [{"line_id": ol.get("id"), "counted": -1}]})
    check("Opname counted negatif -> 400", sc == 400, (sc, r))
    sc, r = call("PUT", f"opname/{opn['id']}/count", {"lines": [{"line_id": ol.get("id"), "counted": 0, "reason": "habis"}], "status": "Review"})
    check("Opname counted = 0 -> 200", sc == 200, (sc, r))
    sc, r = call("POST", f"opname/{opn['id']}/post", {})
    check("Opname post dengan counted = 0 -> 200", sc == 200, (sc, r))
    sc, d = call("GET", f"opname/{opn['id']}")
    l0 = next((l for l in d.get("lines", []) if l.get("id") == ol.get("id")), {})
    check("Opname counted tersimpan 0", float(l0.get("counted") if l0.get("counted") is not None else -99) == 0.0, l0.get("counted"))
    sc, adj2 = call("POST", "adjustments", {"warehouse_id": wh, "division_id": M["div"]["id"], "reason": "seed ulang",
                                            "lines": [{"item_id": M["item"]["id"], "adjustment": 40, "approved_unit_cost": 1000}]})
    check("Seed stok ulang setelah opname -> 200", sc == 200, (sc, adj2))

    # ---------- E. RO mewarisi Divisi MRO & dikunci
    sc, mA = mro(M, qty=10)
    call("POST", f"mro/{mA['id']}/submit", {})
    sc, mB = mro(M, qty=5, div=divB["id"])
    call("POST", f"mro/{mB['id']}/submit", {})
    sc, r = call("POST", "ro", ro_body(mA, 4, div=divB["id"]))
    check("RO divisi beda dari MRO -> 400", sc == 400 and LOCK in detail(r), (sc, r))
    sc, r = call("POST", "ro", ro_body(mA, 2, extra_sources=[{"mro_id": mB["id"], "line_id": mB["lines"][0]["id"], "qty": 2}]))
    check("RO dari MRO beda divisi -> 400 (tidak dipilih otomatis)", sc == 400 and "Divisi" in detail(r), (sc, r))
    sc, r = call("POST", "ro", {**ro_body(mA, 4), "lines": [{**ro_body(mA, 4)["lines"][0], "qty": 0}]})
    check("RO qty 0 -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, ro = call("POST", "ro", ro_body(mA, 10))
    check("RO tanpa divisi -> mewarisi divisi MRO", sc == 200 and ro.get("division_id") == M["div"]["id"], (sc, ro))
    sc, r = call("PUT", f"transactions/ro/{ro['id']}", {"division_id": divB["id"], "lines": ro_body(mA, 10)["lines"]})
    check("Edit RO ganti divisi -> 400 (terkunci)", sc == 400 and LOCK in detail(r), (sc, r))
    sc, r = call("PUT", f"transactions/ro/{ro['id']}", {"division_id": M["div"]["id"], "lines": [{**ro_body(mA, 10)["lines"][0], "qty": -1}]})
    check("Edit RO qty negatif -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    call("POST", f"ro/{ro['id']}/submit", {})

    # ---------- F. PO mewarisi Divisi RO
    rl = ro["lines"][0]
    po_line = {"item_id": rl["item_id"], "qty": 10, "price": 1000, "warehouse_id": wh, "sources": [{"ro_id": ro["id"], "line_id": rl["id"], "qty": 10}]}
    sc, r = call("POST", "po", {"supplier_id": M["supX"]["id"], "division_id": divB["id"], "lines": [po_line]})
    check("PO divisi beda dari RO -> 400", sc == 400 and "Divisi" in detail(r), (sc, r))
    sc, r = call("POST", "po", {"supplier_id": M["supX"]["id"], "lines": [{**po_line, "qty": 0}]})
    check("PO qty 0 -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, po = call("POST", "po", {"supplier_id": M["supX"]["id"], "lines": [po_line]})
    check("PO tanpa divisi -> mewarisi divisi RO", sc == 200 and po.get("division_id") == M["div"]["id"], (sc, po))
    call("POST", f"po/{po['id']}/submit", {})
    sc, pd = call("GET", f"po/{po['id']}")
    if pd.get("status") != "Approved":
        call("POST", f"po/{po['id']}/approve", {})
        sc, pd = call("GET", f"po/{po['id']}")
    check("PO approved", pd.get("status") == "Approved", pd.get("status"))

    # ---------- G. DO mewarisi Divisi PO
    db_ = rc.do_body(M, pd, 3, "supX")
    sc, r = call("POST", "do", {**db_, "division_id": divB["id"]})
    check("DO divisi beda dari PO -> 400", sc == 400 and LOCK in detail(r), (sc, r))
    sc, r = call("POST", "do", rc.do_body(M, pd, 0, "supX"))
    check("DO qty 0 -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, do = call("POST", "do", db_)
    check("DO tanpa divisi -> 200 & divisi = divisi PO", sc == 200 and do.get("division_id") == M["div"]["id"], (sc, do.get("division_id") if isinstance(do, dict) else do))

    # ---------- H. MI mewarisi Divisi MRO
    sc, mI = mro(M, qty=3)
    call("POST", f"mro/{mI['id']}/submit", {})
    ml = mI["lines"][0]
    mi_line = {"item_id": ml["item_id"], "qty": 1, "warehouse_id": wh, "mro_id": mI["id"], "mro_line_id": ml["id"],
               "sources": [{"mro_id": mI["id"], "line_id": ml["id"], "qty": 1}]}
    sc, r = call("POST", "mi", {"source_type": "MRO", "division_id": divB["id"], "lines": [mi_line]})
    check("MI divisi beda dari MRO -> 400", sc == 400 and LOCK in detail(r), (sc, r))
    sc, r = call("POST", "mi", {"source_type": "MRO", "lines": [{**mi_line, "qty": 0}]})
    check("MI qty 0 -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, mi = call("POST", "mi", {"source_type": "MRO", "lines": [mi_line]})
    check("MI tanpa divisi -> mewarisi divisi MRO", sc == 200 and mi.get("division_id") == M["div"]["id"], (sc, mi))
    sc, miG = call("GET", f"mi/{mi['id']}")
    check("MI tersimpan: division_id = MRO.division_id (reload)", sc == 200 and miG.get("division_id") == mI.get("division_id") == M["div"]["id"], (sc, miG.get("division_id")))
    sc, r = call("PUT", f"transactions/mi/{mi['id']}", {"source_type": "MRO", "division_id": divB["id"], "lines": [mi_line]})
    check("Edit MI ganti divisi via API -> 400 (terkunci ke MRO)", sc == 400 and LOCK in detail(r), (sc, r))
    sc, mI2 = mro(M, qty=3, div=divB["id"])
    call("POST", f"mro/{mI2['id']}/submit", {})
    ml2 = mI2["lines"][0]
    mi_line2 = {"item_id": ml2["item_id"], "qty": 1, "warehouse_id": wh, "mro_id": mI2["id"], "mro_line_id": ml2["id"],
                "sources": [{"mro_id": mI2["id"], "line_id": ml2["id"], "qty": 1}]}
    sc0, mis0 = call("GET", "mi")
    sc, r = call("POST", "mi", {"source_type": "MRO", "lines": [mi_line, mi_line2]})
    check("MI dari >1 MRO beda Divisi -> 400 (tidak dipilih otomatis)", sc == 400 and "Divisi" in detail(r), (sc, r))
    sc, r = call("POST", "mi", {"source_type": "MRO", "division_id": M["div"]["id"], "lines": [mi_line, mi_line2]})
    check("MI >1 MRO beda Divisi + division_id dipaksa -> 400", sc == 400 and "Divisi" in detail(r), (sc, r))
    sc1, mis1 = call("GET", "mi")
    check("MI tidak tercipta setelah penolakan beda Divisi", len(mis1 or []) == len(mis0 or []), (len(mis0 or []), len(mis1 or [])))
    sc, r = call("POST", "mi", {"source_type": "PO", "division_id": M["div"]["id"],
                                "lines": [{"item_id": ml["item_id"], "qty": 1, "warehouse_id": wh, "sources": [{"po_id": po["id"], "line_id": po["lines"][0]["id"], "qty": 1}]}]})
    check("MI dengan sumber PO -> 400 (MI hanya dari MRO)", sc == 400 and "Sumber MI hanya dari MRO" in detail(r), (sc, r))
    sc, r = call("POST", "mi", {"source_type": "", "division_id": M["div"]["id"], "lines": [{"item_id": ml["item_id"], "qty": 1, "warehouse_id": wh}]})
    check("MI source_type kosong tanpa baris MRO -> 400 (default Dari MRO, tanpa celah)", sc == 400 and "MRO" in detail(r), (sc, r))
    sc, r = call("PUT", f"transactions/mi/{mi['id']}", {"source_type": "PO", "lines": [mi_line]})
    check("Edit MI ubah sumber ke PO via API -> 400", sc == 400 and "Sumber MI" in detail(r), (sc, r))
    sc2, mis2 = call("GET", "mi")
    check("Tidak ada MI tercipta dari sumber non-MRO", len(mis2 or []) == len(mis0 or []), (len(mis0 or []), len(mis2 or [])))

    # ---------- I. Edit MRO: qty 0 tidak lagi dilewati diam-diam; divisi kosong ditolak
    sc, mE = mro(M, qty=2, submitted=False)
    sc, r = call("PUT", f"transactions/mro/{mE['id']}", {"division_id": M["div"]["id"], "lines": [{"item_id": M["item"]["id"], "qty": 0, "warehouse_id": wh}]})
    check("Edit MRO qty 0 -> 400", sc == 400 and detail(r) == QTY, (sc, r))
    sc, r = call("PUT", f"transactions/mro/{mE['id']}", {"division_id": "", "lines": [{"item_id": M["item"]["id"], "qty": 2, "warehouse_id": wh}]})
    check("Edit MRO divisi kosong -> 400", sc == 400 and detail(r) == DIV, (sc, r))

    # ---------- J. Sumber di luar scope Divisi user: otorisasi (403/404) lebih dulu, bukan "Divisi wajib diisi."
    from po_approval2_batch_test import mk_user
    outsider = mk_user("divb", [divB["id"]])
    sc, mJ = mro(M, qty=4)
    call("POST", f"mro/{mJ['id']}/submit", {})
    sc0, ros0 = call("GET", "ro")
    sc, r = outsider("POST", "ro", ro_body(mJ, 2))
    check("RO dari MRO divisi lain (user scope B) -> 403/404, bukan pesan Divisi", sc in (403, 404) and detail(r) != DIV, (sc, r))
    sc1, ros1 = call("GET", "ro")
    check("RO tidak tercipta setelah penolakan scope", len(ros1 or []) == len(ros0 or []), (len(ros0 or []), len(ros1 or [])))
    mlJ = mJ["lines"][0]
    sc, r = outsider("POST", "mi", {"source_type": "MRO", "lines": [{"item_id": mlJ["item_id"], "qty": 1, "warehouse_id": wh, "mro_id": mJ["id"],
                                                                  "mro_line_id": mlJ["id"], "sources": [{"mro_id": mJ["id"], "line_id": mlJ["id"], "qty": 1}]}]})
    check("MI dari MRO divisi lain (user scope B) -> 403/404, bukan pesan Divisi", sc in (403, 404) and detail(r) != DIV, (sc, r))
    sc, r = outsider("POST", "do", rc.do_body(M, pd, 1, "supX"))
    check("DO dari PO divisi lain (user scope B) -> 403/404, bukan pesan Divisi", sc in (403, 404) and detail(r) != DIV, (sc, r))
    sc, r = outsider("POST", "mro", {"no": f"MRO-J-{uuid.uuid4().hex[:5]}", "requester": "x", "lines": [{"item_id": M["item"]["id"], "qty": 1, "warehouse_id": wh}]})
    check("Transaksi non-sumber tanpa divisi tetap -> 400 Divisi wajib diisi.", sc == 400 and detail(r) == DIV, (sc, r))

    passed = sum(1 for _, ok in rc.RESULTS if ok)
    print(f"\n{passed}/{len(rc.RESULTS)} passed")
    sys.exit(0 if passed == len(rc.RESULTS) else 1)


if __name__ == "__main__":
    main()
