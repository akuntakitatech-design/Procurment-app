"""Cetak PO — nomor MRO per baris PO (`mro_refs` di GET /api/po/{id}) — E2E (tenant uji) + unit (fake DB).

mro_refs = MRO yang benar-benar terhubung ke baris PO lewat rantai allocations existing (PO <- RO <- MRO), tanpa duplikasi:
1 MRO, multi-MRO (1 baris RO dari beberapa MRO), sumber spesifik (via_alloc_id), PO tanpa MRO (baris tanpa sumber RO),
allocation lama tanpa via_alloc_id. Read-only: tidak mengubah allocations / po_lines / status / approval.
"""
import asyncio
import sys
import uuid

sys.path.insert(0, "/app/backend/tests")
import po_document_status_test as S
import receipt_control_test as T
from po_ro_split_test import mk_item, mk_ro, po_body, pull_row, rs
from ro_consolidation_test import mro

call, check = T.call, T.check


def refs(po):
    sc, d = call("GET", f"po/{po['id']}")
    return sc, d, [(l.get("item_id"), float(l.get("qty") or 0), l.get("mro_refs")) for l in d.get("lines") or []]


def main():
    M = T.setup()
    T.M = M
    u = uuid.uuid4().hex[:5]
    bolt = mk_item(M, f"BLT{u}", "Baut M10", primary=M["supX"]["id"])
    oli = mk_item(M, f"OLI{u}", "Oli Mesin", primary=M["supX"]["id"])
    M["bolt"], M["oli"] = bolt, oli
    m1, l1 = mro(M, f"MRO-1-{u}", 60, item="bolt", project="pa")
    m2, l2 = mro(M, f"MRO-2-{u}", 40, item="bolt", project="pb")
    m3, l3 = mro(M, f"MRO-3-{u}", 30, item="oli")
    ro1 = mk_ro(M, [(bolt, 100, [(m1, l1, 60), (m2, l2, 40)]), (oli, 30, [(m3, l3, 30)])])
    by_item = {l["item_id"]: l for l in ro1["lines"]}
    RB, RO_ = by_item[bolt["id"]], by_item[oli["id"]]
    via = {s["mro_no"]: s["ro_alloc_id"] for s in pull_row(RB["id"])["sources"]}

    # PO A: Oli dari 1 MRO; Baut 70 dari baris RO yang bersumber 2 MRO (FIFO existing: MRO-1 60 + MRO-2 10)
    body = po_body(M, M["supX"], [(oli, 10, [rs(ro1, RO_, 10)]), (bolt, 70, [rs(ro1, RB, 70)])])
    sc, pa = call("POST", "po", body)
    check("PO A dibuat dari RO (alur existing)", sc == 200 and pa.get("id"), (sc, pa))
    sc, _da, la = refs(pa)
    got = {it: r for it, _, r in la}
    check("1 MRO: baris Oli -> [MRO-3]", got.get(oli["id"]) == [f"MRO-3-{u}"], got.get(oli["id"]))
    check("multi-MRO: baris Baut (via RO dari 2 MRO) -> [MRO-1, MRO-2] tanpa duplikasi", got.get(bolt["id"]) == [f"MRO-1-{u}", f"MRO-2-{u}"], got.get(bolt["id"]))

    # PO B: Baut 5 khusus dari sumber MRO-2 (ro_alloc_id) -> hanya MRO-2 walau baris RO punya 2 MRO
    sc, pb = call("POST", "po", po_body(M, M["supX"], [(bolt, 5, [rs(ro1, RB, 5, via=via[f"MRO-2-{u}"])])]))
    _, _, lb = refs(pb)
    check("sumber spesifik (via_alloc_id): hanya MRO yang dikonsumsi baris PO -> [MRO-2]", sc == 200 and lb and lb[0][2] == [f"MRO-2-{u}"], (sc, lb))

    # PO C: tanpa referensi MRO (baris tanpa sumber RO) -> [] (cetak nama barang seperti biasa)
    import po_approval2_batch_test as A
    pc = A.mk_po(M, [A.line(M, "item", 3, 1500)])
    sc, _dc, lc = refs(pc)
    check("PO tanpa MRO: mro_refs = [] pada setiap baris", sc == 200 and lc and all(r == [] for _, _, r in lc), lc)

    # Campuran dalam satu PO: baris ber-MRO + baris tanpa sumber
    mixed = po_body(M, M["supX"], [(oli, 5, [rs(ro1, RO_, 5)])])
    mixed["lines"].append({"item_id": M["item"]["id"], "qty": 2, "uom_id": M["uom"]["id"], "conversion_factor": 1,
                           "warehouse_id": M["wh"]["id"], "price": 1000})
    sc, pm = call("POST", "po", mixed)
    _, _, lm = refs(pm)
    got = {it: r for it, _, r in lm}
    check("PO campuran: baris RO -> [MRO-3], baris tanpa sumber -> []", sc == 200 and got.get(oli["id"]) == [f"MRO-3-{u}"]
          and got.get(M["item"]["id"]) == [], (sc, lm))

    # Read-only & tidak mengubah alur: GET berulang identik, edit tidak menyimpan mro_refs, status/approval tetap
    before = refs(pa)[2]
    sc, d2 = call("GET", f"po/{pa['id']}")
    lines_put = [{k: v for k, v in l.items()} for l in d2["lines"]]  # klien mengirim balik baris detail apa adanya (termasuk mro_refs)
    sc_put, _ = call("PUT", f"transactions/po/{pa['id']}", {**{k: d2[k] for k in ("supplier_id", "division_id", "date") if k in d2},
                                                            "lines": [{**l, "sources": [rs(ro1, RO_ if l["item_id"] == oli["id"] else RB, l["qty"])]}
                                                                      for l in lines_put]})
    after = refs(pa)[2]
    check("GET detail berulang identik (read-only)", before == refs(pa)[2], before)
    _sc_raw, raw = call("GET", f"po/{pa['id']}")
    check("Status PO tetap Draft (tidak menyentuh approval/workflow)", raw.get("status") == "Draft", raw.get("status"))
    check("Edit PO (klien mengirim balik mro_refs): 200 & mro_refs tetap hasil turunan, tidak tersimpan sebagai data baris",
          sc_put == 200 and after == before, (sc_put, before, after))

    unit_tests()
    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\n{ok}/{len(T.RESULTS)} passed")
    return 0 if ok == len(T.RESULTS) else 1


class _Db:
    def __init__(self, **c):
        for n in ("allocations", "mro"):
            setattr(self, n, S._Coll(c.get(n, [])))


def unit_tests():
    sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
    import receipt_control_layer as R
    allocs = [
        # RO line r1 <- MRO a (alloc x1) & MRO b (alloc x2); RO line r2 <- MRO c
        {"id": "x1", "target_line_id": "r1", "source_type": "mro", "source_line_id": "ma", "source_doc_id": "A"},
        {"id": "x2", "target_line_id": "r1", "source_type": "mro", "source_line_id": "mb", "source_doc_id": "B"},
        {"id": "x3", "target_line_id": "r2", "source_type": "mro", "source_line_id": "mc", "source_doc_id": "C"},
        # PO lines
        {"id": "p1", "target_line_id": "legacy", "source_type": "ro", "source_line_id": "r1"},                    # lama, tanpa via
        {"id": "p2", "target_line_id": "via", "source_type": "ro", "source_line_id": "r1", "via_alloc_id": "x2"},
        {"id": "p3", "target_line_id": "dup", "source_type": "ro", "source_line_id": "r1", "via_alloc_id": "x1"},
        {"id": "p4", "target_line_id": "dup", "source_type": "ro", "source_line_id": "r1", "via_alloc_id": "x1"},
        {"id": "p5", "target_line_id": "dup", "source_type": "ro", "source_line_id": "r2"},
        {"id": "p6", "target_line_id": "direct", "source_type": "mro", "source_line_id": "mc", "source_doc_id": "C"},
        {"id": "p7", "target_line_id": "gone", "source_type": "ro", "source_line_id": "r9"},                      # RO line tanpa MRO
        {"id": "p8", "target_line_id": "stampfb", "source_type": "ro", "source_line_id": "r1", "via_alloc_id": "hilang", "mro_id": "B"},
    ]
    db = _Db(allocations=allocs, mro=[{"id": "A", "no": "MRO-A"}, {"id": "B", "no": "MRO-B"}, {"id": "C", "no": "MRO-C"}])
    lines = [{"id": i} for i in ("legacy", "via", "dup", "direct", "gone", "none", "stampfb")]
    m = asyncio.run(R.po_line_mro_refs(S._Srv(db), lines))
    check("Unit: allocation lama tanpa via_alloc_id -> semua MRO sumber baris RO", m.get("legacy") == ["MRO-A", "MRO-B"], m.get("legacy"))
    check("Unit: via_alloc_id -> hanya MRO allocation yang dikonsumsi", m.get("via") == ["MRO-B"], m.get("via"))
    check("Unit: beberapa sumber + duplikat -> unik & urut", m.get("dup") == ["MRO-A", "MRO-C"], m.get("dup"))
    check("Unit: allocation PO<-MRO langsung ikut", m.get("direct") == ["MRO-C"], m.get("direct"))
    check("Unit: tanpa referensi MRO -> tidak ada entri", "gone" not in m and "none" not in m)
    check("Unit: via tidak ditemukan -> stempel mro_id allocation PO (data asli), bukan tebakan", m.get("stampfb") == ["MRO-B"], m.get("stampfb"))
    check("Unit: tanpa baris -> {}", asyncio.run(R.po_line_mro_refs(S._Srv(db), [])) == {})


if __name__ == "__main__":
    sys.exit(main())
