"""Status Dokumen PO (derived) sesuai posisi Approval 1 / Approval 2 — E2E (throwaway tenant, localhost:8001).

document_status = tampilan turunan dari PO.status + approval_tasks + po_approval2_batch(_items) + receipt_status.
PO.status internal & receipt_status tidak berubah. List (/api/po, paged & non-paged) dan detail (/api/po/{id}) konsisten.
Bagian akhir: unit test fungsi derivasi (legacy tanpa task, seq>2, rejected task) memakai fake DB.
"""
import asyncio
import sys
import uuid

import po_approval2_batch_test as A
import receipt_control_test as T

call, check = T.call, T.check
WA1, RA2, WA2 = "Waiting Approval 1", "Ready Approval 2", "Waiting Approval 2"


def detail(p):
    return call("GET", f"po/{p['id']}")[1]


def list_map(paged=False):
    if paged:
        sc, d = call("GET", "po?page=1&page_size=100")
        rows = d.get("items", []) if isinstance(d, dict) else []
    else:
        sc, rows = call("GET", "po")
    return {r["id"]: r for r in rows or []}


def expect(label, pos, want):
    """Cek list (array & paged) + detail menghasilkan document_status yang sama = want."""
    lm, pm = list_map(), list_map(paged=True)
    for p in pos:
        d = detail(p)
        got = (lm.get(p["id"], {}).get("document_status"), pm.get(p["id"], {}).get("document_status"), d.get("document_status"))
        check(f"{label}: {d.get('no')} -> {want} (list/paged/detail)", got == (want, want, want), got)


def main():
    M = T.setup()
    sc, me = call("GET", "auth/me")
    a1, a2 = A.mk_user("l1", [M["div"]["id"]]), A.mk_user("l2", [M["div"]["id"]])
    A.set_ov(a2, {"upload_attachment": "allow"})
    call("PUT", "settings/approval_modules", {"modules": {
        "mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
        "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}, {"level": 2, "email": a2.email}]}}}, 200)

    pA, pB, pC, pD, pE, pF = (A.mk_po(M, [A.line(M, "item", 10, 1000 + i)]) for i in range(6))
    allp = [pA, pB, pC, pD, pE, pF]
    expect("Draft", allp, "Draft")
    check("PO.status internal Draft tetap", all(detail(p)["status"] == "Draft" for p in allp))

    for p in allp:
        call("POST", f"po/{p['id']}/submit", {}, 200)
    expect("Submit", allp, WA1)
    check("PO.status internal tetap 'Waiting Approval'", all(detail(p)["status"] == "Waiting Approval" for p in allp))

    for p in [pA, pB, pC, pD]:
        t = A.task(a1, p["id"], 1)
        a1("POST", f"approvals/{t['id']}/approve", {"note": "L1 OK"})
    expect("Level 1 Approved", [pA, pB, pC, pD], RA2)
    expect("Level 1 belum di-approve", [pF], WA1)
    check("Setelah L1: PO.status internal tetap 'Waiting Approval'", detail(pA)["status"] == "Waiting Approval")

    # Rejected di Level 1
    t = A.task(a1, pE["id"], 1)
    a1("POST", f"approvals/{t['id']}/reject", {"reason": "revisi"})
    expect("Rejected", [pE], "Rejected")

    # Batch Draft -> tetap Siap Diajukan Approval 2
    sc, el = a2("GET", "approval2/po/eligible")
    tid = {r["po_id"]: r["approval_task_id"] for r in el or []}
    sc, B = a2("POST", "approval2/po/batches", {"title": "Uji Status", "submission_date": "2026-10-06",
                                                "approval_task_ids": [tid[p["id"]] for p in (pA, pB, pC)]})
    check("Batch dibuat (Draft)", sc == 200 and B.get("status") == "Draft", (sc, B.get("status")))
    expect("Batch Draft", [pA, pB, pC, pD], RA2)

    # Batch Diajukan -> Menunggu Approval 2 (hanya PO di batch)
    sc, d = a2("POST", f"approval2/po/batches/{B['id']}/submit", {})
    check("Batch Diajukan", sc == 200 and d.get("status") == "Diajukan", d.get("status"))
    expect("Batch Diajukan", [pA, pB, pC], WA2)
    expect("PO di luar batch", [pD], RA2)

    # Partial batch: hanya pA di-approve
    sc, ev = a2.upload("po_approval2_batch", B["id"], "bukti.png", A.PNG, "image/png")
    check("Upload bukti batch", sc == 200, sc)
    it = {i["po_id"]: i["id"] for i in B["items"]}
    sc, d = a2("POST", f"approval2/po/batches/{B['id']}/approve", {"item_ids": [it[pA["id"]]]})
    check("Approve Terpilih -> batch Selesai Sebagian", sc == 200 and d.get("status") == "Selesai Sebagian", (sc, d.get("status")))
    expect("Approval 2 Approved", [pA], "Approved")
    expect("Partial batch: PO pending", [pB, pC], WA2)
    x = detail(pA)
    check("PO.status internal 'Approved' + receipt Belum Diterima", x["status"] == "Approved" and x.get("receipt_status") == "Belum Diterima",
          (x["status"], x.get("receipt_status")))

    # Source picker PO -> DO tetap bekerja
    sc, pull = call("GET", f"pull/po-for-do?supplier_id={M['supX']['id']}")
    pulled = {r["po_id"] for r in pull or []}
    check("Source picker PO->DO memuat PO Approved", pA["id"] in pulled, sorted(pulled))
    check("Source picker tidak memuat PO menunggu approval", not ({pB["id"], pC["id"], pD["id"], pF["id"]} & pulled))

    # Penerimaan: sebagian -> tetap Disetujui; penuh -> Ditutup
    xa = detail(pA)
    call("POST", "do", T.do_body(M, xa, 4, "supX"), 200)
    expect("Approved + Diterima Sebagian", [pA], "Approved")
    check("receipt_status Diterima Sebagian", detail(pA).get("receipt_status") == "Diterima Sebagian")
    call("POST", "do", T.do_body(M, xa, 6, "supX"), 200)
    expect("Approved + Diterima Penuh", [pA], "Closed")
    x = detail(pA)
    # PO.status internal tetap dikelola workflow existing (receipt engine set 'Fully Received'); tidak diganti teks UI.
    check("receipt_status Diterima Penuh; PO.status internal tetap nilai workflow existing",
          x.get("receipt_status") == "Diterima Penuh" and x["status"] in ("Approved", "Fully Received"), (x.get("receipt_status"), x["status"]))
    check("PO Ditutup keluar dari source picker",
          pA["id"] not in {r["po_id"] for r in call("GET", "pull/po-for-do")[1] or []})

    # Over receipt -> Ditutup
    sc, d = a2("POST", f"approval2/po/batches/{B['id']}/approve", {"item_ids": [it[pB["id"]]]})
    expect("Approve pB", [pB], "Approved")
    expect("Partial batch: PO pending (pC)", [pC], WA2)
    xb = detail(pB)
    call("POST", "do", T.do_body(M, xb, 11, "supX", reason="Bonus supplier"), 200)
    expect("Approved + Over Receipt", [pB], "Closed")
    check("receipt_status Over Receipt", detail(pB).get("receipt_status") == "Over Receipt")

    # Cancelled
    call("POST", f"po/{pF['id']}/cancel", {"reason": "batal"}, 200)
    expect("Cancelled", [pF], "Cancelled")

    # Workflow 1 level (tanpa Approval 2) -> tidak pernah Siap Diajukan Approval 2
    call("PUT", "settings/approval_modules", {"modules": {
        "mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
        "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}]}}}, 200)
    pG = A.mk_po(M, [A.line(M, "item", 2, 5000)])
    call("POST", f"po/{pG['id']}/submit", {}, 200)
    expect("1 level: submit", [pG], WA1)
    t = A.task(a1, pG["id"], 1)
    a1("POST", f"approvals/{t['id']}/approve", {"note": "ok"})
    expect("1 level: approved", [pG], "Approved")

    # Approval nonaktif -> langsung Disetujui
    call("PUT", "settings/approval_modules", {"modules": {
        "mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
        "po": {"enabled": False, "levels": []}}}, 200)
    pH = A.mk_po(M, [A.line(M, "item", 2, 5000)])
    call("POST", f"po/{pH['id']}/submit", {}, 200)
    expect("Approval nonaktif: submit", [pH], "Approved")

    unit_tests()
    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\n{ok}/{len(T.RESULTS)} passed")
    return 0 if ok == len(T.RESULTS) else 1


# ------------------------------------------------------------------ unit (fake DB, tanpa server)
class _Cur:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return list(self.rows)


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, q, proj=None):
        def ok(r):
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if r.get(k) not in v["$in"]:
                        return False
                elif r.get(k) != v:
                    return False
            return True
        return _Cur([r for r in self.rows if ok(r)])


class _Db:
    def __init__(self, **c):
        for n in ("approval_tasks", "po_approvals", "po_approval2_batch_items", "po_approval2_batches"):
            setattr(self, n, _Coll(c.get(n, [])))


class _Srv:
    def __init__(self, db):
        self.db = db


def unit_tests():
    sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
    import receipt_control_layer as R
    W = {"status": "Waiting Approval"}
    pos = [{"id": i, **W} for i in ("legacy", "mirror", "seq3", "rej", "a2draft", "a2sub", "a2part")]
    db = _Db(
        approval_tasks=[
            {"id": "t3", "module": "po", "document_id": "seq3", "seq": 3, "status": "Pending"},
            {"id": "tr", "module": "po", "document_id": "rej", "seq": 1, "status": "Rejected"},
            {"id": "d2", "module": "po", "document_id": "a2draft", "seq": 2, "status": "Pending"},
            {"id": "s2", "module": "po", "document_id": "a2sub", "seq": 2, "status": "Pending"},
            {"id": "p2", "module": "po", "document_id": "a2part", "seq": 2, "status": "Pending"},
        ],
        po_approvals=[{"id": "m1", "po_id": "mirror", "seq": 1, "status": "Pending"}],
        po_approval2_batch_items=[
            {"approval_task_id": "d2", "batch_id": "bD", "status": "Pending"},
            {"approval_task_id": "s2", "batch_id": "bS", "status": "Pending"},
            {"approval_task_id": "p2", "batch_id": "bP", "status": "Pending"},
        ],
        po_approval2_batches=[{"id": "bD", "status": "Draft"}, {"id": "bS", "status": "Diajukan"}, {"id": "bP", "status": "Selesai Sebagian"}],
    )
    st = asyncio.run(R.po_approval_stage_map(_Srv(db), pos))
    disp = {p["id"]: R.display_document_status(p, R.document_status(p, "Belum Diterima"), st.get(p["id"])) for p in pos}
    check("Unit: legacy Waiting Approval tanpa task -> fallback state existing", disp["legacy"] == "Waiting Approval", disp["legacy"])
    check("Unit: legacy hanya mirror po_approvals seq1 -> Menunggu Approval 1", disp["mirror"] == WA1, disp["mirror"])
    check("Unit: tahap > 2 -> fallback state existing (tidak dipaksa Approval 2)", disp["seq3"] == "Waiting Approval", disp["seq3"])
    check("Unit: task Rejected -> Ditolak", disp["rej"] == "Rejected", disp["rej"])
    check("Unit: batch Draft -> Siap Diajukan Approval 2", disp["a2draft"] == RA2, disp["a2draft"])
    check("Unit: batch Diajukan -> Menunggu Approval 2", disp["a2sub"] == WA2, disp["a2sub"])
    check("Unit: batch Selesai Sebagian + item Pending -> Menunggu Approval 2", disp["a2part"] == WA2, disp["a2part"])
    base = {"Draft": {"status": "Draft"}, "Cancelled": {"status": "Approved", "cancelled": True},
            "Rejected": {"status": "Rejected"}}
    for want, p in base.items():
        got = R.display_document_status(p, R.document_status(p, "Belum Diterima"), "Waiting Approval 2")
        check(f"Unit: prioritas {want} tidak tertimpa tahap approval", got == want, got)
    ap = {"status": "Approved"}
    check("Unit: Approved + Belum/Sebagian -> Approved; Penuh/Over -> Closed",
          [R.display_document_status(ap, R.document_status(ap, rs), None) for rs in ("Belum Diterima", "Diterima Sebagian", "Diterima Penuh", "Over Receipt")]
          == ["Approved", "Approved", "Closed", "Closed"])
    check("Unit: document_status() existing (dipakai picker/persist) tidak berubah",
          R.document_status(W, "Belum Diterima") == "Waiting Approval")


if __name__ == "__main__":
    sys.exit(main())
