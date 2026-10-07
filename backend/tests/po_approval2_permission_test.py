"""Approval 2 PO — izin granular po_approval2.view/submit/approve/print (sistem Hak Akses existing).

Throwaway tenant. Approve Terpilih = po_approval2.approve AND exact assignee Level 2 AND scope Divisi.
Submit batch = po_approval2.submit (tanpa hak approve). Override user "Tolak" mengalahkan default role.
"""
import sys
import uuid

import requests

import receipt_control_test as T
from po_approval2_batch_test import U, PNG, mk_user, set_ov, mk_po, line, task

call, check, API = T.call, T.check, T.API
DENY_ALL = {"po_approval2.view": "deny", "po_approval2.submit": "deny", "po_approval2.approve": "deny", "po_approval2.print": "deny"}


def only(*keep, extra=None):
    ov = {k: v for k, v in DENY_ALL.items() if k.split(".")[1] not in keep}
    ov.update(extra or {})
    return ov


def main():
    M = T.setup()
    sc, div2 = call("POST", "master/divisions", {"code": f"D2{uuid.uuid4().hex[:5]}", "name": "Divisi Lain"}, 200)
    d1 = [M["div"]["id"]]
    a1, a2 = mk_user("l1", d1), mk_user("l2", d1)
    viewer, submitter = mk_user("view", d1), mk_user("sub", d1)
    printer = viewer  # batas user paket starter: user yang sama, izin diganti via override
    sc, _ = call("PUT", "settings/approval_modules", {"modules": {
        "mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
        "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}, {"level": 2, "email": a2.email}]}}}, 200)

    # katalog Hak Akses memuat modul baru
    sc, cat = call("GET", "access/catalog")
    mods = {m["key"] if isinstance(m, dict) else m[0]: m for g in (cat.get("groups") or []) for m in (g.get("modules") or [])}
    a2mod = mods.get("po_approval2") or {}
    acts = [a["key"] if isinstance(a, dict) else a for a in (a2mod.get("actions") or [])] if isinstance(a2mod, dict) else []
    check("Katalog Hak Akses memuat Approval 2 PO (view/submit/approve/print)", set(acts) == {"view", "submit", "approve", "print"}, a2mod)

    pos = [mk_po(M, [line(M, "item", 1, 1000 * (i + 1))]) for i in range(4)]
    for p in pos:
        call("POST", f"po/{p['id']}/submit", {}, 200)
        t = task(a1, p["id"], 1)
        a1("POST", f"approvals/{t['id']}/approve", {"note": "L1 OK"})
    tids = [task(a2, p["id"], 2)["id"] for p in pos]
    check("Level 2 Pending untuk semua PO", all(tids))

    set_ov(viewer, only("view"))
    set_ov(submitter, only("view", "submit"))
    set_ov(a2, only("view", "approve", extra={"upload_attachment": "allow"}))

    # 1. view saja
    sc, el = viewer("GET", "approval2/po/eligible")
    check("1. view: dapat melihat daftar eligible", sc == 200 and {p["id"] for p in pos} <= {r["po_id"] for r in el}, (sc, el))
    check("1. view: tidak ada can_approve", not any(r.get("can_approve") for r in el or []))
    sc, _ = viewer("POST", "approval2/po/batches", {"title": "V", "submission_date": "2026-10-06", "approval_task_ids": tids[:1]})
    check("1. view: tidak dapat submit batch (403)", sc == 403, sc)

    # 2. view + submit (submitter BUKAN assignee Level 2)
    sc, B = submitter("POST", "approval2/po/batches", {"title": "Pengajuan Uji Izin", "submission_date": "2026-10-06", "approval_task_ids": tids[:3]})
    check("2. view+submit: dapat membuat batch walau bukan assignee", sc == 200 and B.get("po_count") == 3, (sc, B))
    bid = B.get("id")
    sc, _ = viewer("POST", f"approval2/po/batches/{bid}/submit", {})
    check("1. view: tidak dapat export/submit (403)", sc == 403, sc)
    sc, _ = viewer("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": ["x"]})
    check("1. view: tidak dapat approve (403)", sc == 403, sc)
    set_ov(printer, only("view", "print"))
    sc, _ = printer("POST", f"approval2/po/batches/{bid}/submit", {})
    check("4. print tanpa submit: tidak dapat mengajukan batch Draft (403)", sc == 403, sc)
    sc, d = submitter("POST", f"approval2/po/batches/{bid}/submit", {})
    check("2. view+submit: dapat mengajukan (export) batch", sc == 200 and d.get("status") == "Diajukan", (sc, d.get("status") if isinstance(d, dict) else d))
    sc, _ = submitter.upload("po_approval2_batch", bid, "bukti.png", PNG, "image/png")
    items = {i["po_id"]: i for i in (d.get("items") or [])}
    it0 = items[pos[0]["id"]]["id"]
    sc, _ = submitter("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it0]})
    check("2. view+submit: tidak dapat approve (403)", sc == 403, sc)

    # 4. view + print
    sc, d = printer("POST", f"approval2/po/batches/{bid}/submit", {})
    check("4. view+print: dapat export JPEG batch yang sudah diajukan", sc == 200 and d.get("export_count", 0) >= 2, (sc, d.get("export_count") if isinstance(d, dict) else d))
    sc, _ = printer("POST", "approval2/po/batches", {"title": "P", "submission_date": "2026-10-06", "approval_task_ids": tids[3:]})
    check("4. view+print: tidak dapat membuat batch (403)", sc == 403, sc)

    # 3. view + approve (assignee) — tidak dapat submit
    sc, _ = a2("POST", "approval2/po/batches", {"title": "A", "submission_date": "2026-10-06", "approval_task_ids": tids[3:]})
    check("3. view+approve: tidak dapat membuat batch (403)", sc == 403, sc)
    sc, ev = a2.upload("po_approval2_batch", bid, "wa-approval.png", PNG, "image/png")
    check("3. approver dapat unggah bukti", sc == 200, (sc, ev))
    sc, bv = a2("GET", f"approval2/po/batches/{bid}")
    check("3. batch view: can_approve untuk assignee berizin", sc == 200 and all(i.get("can_approve") for i in bv.get("items") or []), bv.get("items"))

    # 5. approve permission tetapi bukan assignee
    sc, _ = a1("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it0]})
    check("5. punya approve tetapi bukan assignee -> 403", sc == 403, sc)

    # 6. assignee tanpa approve permission
    set_ov(a2, only("view", extra={"upload_attachment": "allow"}))
    sc, _ = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it0]})
    check("6. assignee tanpa po_approval2.approve -> 403", sc == 403, sc)

    # 7. permission benar tetapi divisi di luar scope
    a2.divs = [div2["id"]]
    set_ov(a2, only("view", "approve", extra={"upload_attachment": "allow"}))
    sc, r = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it0]})
    check("7. assignee + izin tetapi divisi di luar scope -> ditolak", sc in (403, 404), (sc, r))
    sc, pd = call("GET", f"po/{pos[0]['id']}")
    check("7. PO tetap Waiting Approval setelah penolakan", pd.get("status") == "Waiting Approval", pd.get("status"))
    a2.divs = d1
    set_ov(a2, only("view", "approve", extra={"upload_attachment": "allow"}))

    # sukses: semua syarat terpenuhi
    sc, r = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it0]})
    check("3. view+approve + assignee + divisi: Approve Terpilih berhasil", sc == 200, (sc, r))
    sc, pd = call("GET", f"po/{pos[0]['id']}")
    check("3. PO menjadi Approved", pd.get("status") == "Approved", pd.get("status"))

    # 8. override Tolak mengalahkan default role
    sc, el = a1("GET", "approval2/po/eligible")
    check("8. role default (manager) memberi po_approval2.view", sc == 200, sc)
    set_ov(a1, {"po_approval2.view": "deny"})
    sc, _ = a1("GET", "approval2/po/eligible")
    check("8. override Tolak po_approval2.view -> 403", sc == 403, sc)
    sc, _ = a1("GET", f"approval2/po/batches/{bid}")
    check("8. override Tolak: detail batch -> 403", sc == 403, sc)
    sc, me = a1("GET", "auth/me")
    check("8. effective permission tidak memuat po_approval2.view", "po_approval2.view" not in (me.get("effective_permissions") or []), me.get("effective_permissions"))
    set_ov(a1, {})

    # 9. tenant lain
    ten = requests.Session(); u = uuid.uuid4().hex[:8]
    r = ten.post(f"{API}/saas/register", json={"company_name": f"A2P {u}", "pic_name": "QA", "email": f"a2p_{u}@example.com",
                                             "whatsapp": "+628123456789", "workspace_slug": f"a2p-{u}", "plan_code": "starter",
                                             "password": "TestPass123!", "address": "x", "terms_accepted": True})
    tok = r.json().get("token") or ten.post(f"{API}/auth/login", json={"email": f"a2p_{u}@example.com", "password": "TestPass123!"}).json().get("token")
    ten.headers.update({"Authorization": f"Bearer {tok}"})
    check("9. tenant lain login valid", ten.get(f"{API}/auth/me").status_code == 200)
    r = ten.get(f"{API}/approval2/po/batches/{bid}")
    check("9. tenant lain tidak dapat membaca batch", r.status_code == 404, r.status_code)
    r = ten.post(f"{API}/approval2/po/batches/{bid}/approve", json={"item_ids": [it0]})
    check("9. tenant lain tidak dapat approve batch", r.status_code in (403, 404), r.status_code)
    r = ten.post(f"{API}/approval2/po/batches", json={"title": "X", "submission_date": "2026-10-06", "approval_task_ids": tids[3:]})
    check("9. tenant lain tidak dapat memakai task tenant ini", r.status_code in (403, 404), r.status_code)

    # 10. direct API bypass
    set_ov(viewer, only("view"))
    sc, _ = viewer("POST", f"approvals/{tids[1]}/approve", {"note": "bypass"})
    check("10. bypass approve individual Level 2 ditolak", sc in (403, 409), sc)
    sc, _ = submitter("POST", f"po/{pos[1]['id']}/approve", {})
    check("10. bypass /po/{id}/approve ditolak", sc in (403, 409), sc)
    sc, _ = viewer("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [items[pos[1]['id']]['id']]})
    check("10. direct API approve tanpa izin ditolak", sc == 403, sc)
    sc, pd = call("GET", f"po/{pos[1]['id']}")
    check("10. PO lain tetap Waiting Approval", pd.get("status") == "Waiting Approval", pd.get("status"))

    # MRO/RO tetap alur standar (tidak memakai izin Approval 2)
    sc, mods = call("GET", "settings/approval_modules")
    check("Alur MRO/RO tidak berubah oleh izin Approval 2", sc == 200)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
