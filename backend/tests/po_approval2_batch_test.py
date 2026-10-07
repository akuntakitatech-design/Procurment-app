"""PO Approval Level 2 via Pengajuan Batch — E2E (throwaway tenants, localhost:8001).

Level 1 tetap individual; Level 2 PO hanya via batch (individual API ditolak); snapshot JPEG (deskripsi, project,
DPP/PPN/Total = compute_po_totals, PIC = pembuat PO); export tidak meng-approve; bukti wajib; exact assignee;
tenant/divisi; partial approval; status batch; sinkron approval_tasks + po_approvals + PO; lampiran referensi
(satu storage object untuk banyak PO); audit; race create/approve.
"""
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

import receipt_control_test as T

call, check, API = T.call, T.check, T.API
PW = "TestPass123!"
MSG = "Approval Level 2 PO diproses melalui Pengajuan Approval 2."
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7V\xbd\xfa\x00\x00\x00\x00IEND\xaeB`\x82")


class U:
    def __init__(self, email, token=None):
        self.email = email
        self.S = requests.Session()
        tok = token or self.S.post(f"{API}/auth/login", json={"email": email, "password": PW}).json().get("token")
        self.S.headers.update({"Authorization": f"Bearer {tok}"})

    def __call__(self, method, path, body=None, **kw):
        r = self.S.request(method, f"{API}/{path}", json=body, **kw)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}

    def upload(self, entity, entity_id, name, data, ct):
        r = self.S.post(f"{API}/attachments", files={"file": (name, data, ct)},
                        data={"entity": entity, "entity_id": entity_id, "category": "Lainnya", "note": ""})
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}


def mk_user(name, divs):
    email = f"a2_{name}_{uuid.uuid4().hex[:6]}@example.com"
    sc, u = call("POST", "users", {"email": email, "password": PW, "name": f"QA {name}", "role": "manager"}, 200)
    call("PUT", f"access/users/{u['id']}", {"overrides": {}, "division_override": {"mode": "selected", "divisions": divs}}, 200)
    o = U(email)
    o.uid = u["id"]
    o.divs = divs
    return o


def set_ov(usr, overrides):
    """Override izin user via sistem Hak Akses existing (Ikuti Role / Izinkan / Tolak)."""
    call("PUT", f"access/users/{usr.uid}", {"overrides": overrides, "division_override": {"mode": "selected", "divisions": usr.divs}}, 200)


def line(M, item, qty, price, tax=11, discount=0, project="pa"):
    return {"item_id": M[item]["id"], "qty": qty, "uom_id": M["uom"]["id"], "price": price, "discount": discount, "tax": tax,
            "warehouse_id": M["wh"]["id"], "project_id": M[project]["id"], "price_change_reason": "uji approval 2"}


def mk_po(M, lines, **hdr):
    body = {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "date": "2026-10-01", "lines": lines, **hdr}
    sc, po = call("POST", "po", body, 200)
    return po


def task(user, po_id, seq, status="Pending"):
    sc, rows = user("GET", "approvals/inbox")
    return next((r for r in rows or [] if r.get("document_id") == po_id and r.get("seq") == seq and r.get("status") == status), None)


def main():
    M = T.setup()
    admin_tok = T.S.headers["Authorization"].split(" ", 1)[1]
    sc, me = call("GET", "auth/me")
    admin = U(me["email"], admin_tok)
    for i in range(3, 6):
        sc, M[f"item{i}"] = call("POST", "master/items", {"code": f"IX{i}{uuid.uuid4().hex[:5]}", "name": ["Grinding Disc", "Cutting Disc", "Kawat Las"][i - 3],
                                                          "unit": "PCS", "is_active": True, **T.item_ref(M)}, 200)
    call("PUT", f"master/items/{M['item']['id']}", {**M["item"], "name": "Masker"})
    call("PUT", f"master/items/{M['item2']['id']}", {**M["item2"], "name": "Safety Helmet"})
    sc, div2 = call("POST", "master/divisions", {"code": f"D2{uuid.uuid4().hex[:5]}", "name": "Divisi Lain"}, 200)
    a1, a2 = mk_user("l1", [M["div"]["id"]]), mk_user("l2", [M["div"]["id"]])
    a3 = mk_user("other", [div2["id"]])
    sc, _ = call("PUT", "settings/approval_modules", {"modules": {
        "mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
        "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}, {"level": 2, "email": a2.email}]}}}, 200)

    # ---------------- PO fixtures
    p1 = mk_po(M, [line(M, "item3", 2, 150000, discount=10000), line(M, "item4", 5, 20000), line(M, "item5", 3, 50000),
                   line(M, "item", 10, 15000), line(M, "item2", 4, 120000)], final_discount_type="percent", final_discount_value=5)
    p2 = mk_po(M, [line(M, "item", 2, 100000, tax=0), line(M, "item2", 1, 300000, tax=0, project="pb")])
    p3 = mk_po(M, [line(M, "item3", 1, 111000, tax=11)], tax_inclusive=True)
    p4 = mk_po(M, [line(M, "item4", 3, 70000)])
    p5 = mk_po(M, [line(M, "item5", 1, 90000)])
    p6 = mk_po(M, [line(M, "item", 1, 1000)])     # Level 1 belum approved
    p7 = mk_po(M, [line(M, "item", 1, 2000)])     # race create batch
    p8 = mk_po(M, [line(M, "item", 1, 3000)])     # reject Level 1 regression
    pos = [p1, p2, p3, p4, p5, p6, p7, p8]
    check("PO menyimpan creator eksplisit (created_by + created_by_name)", p1.get("created_by") == me["email"] and bool(p1.get("created_by_name")), p1.get("created_by_name"))
    for p in pos:
        sc, d = call("POST", f"po/{p['id']}/submit", {}, 200)
    check("Submit PO -> Waiting Approval", d.get("status") == "Waiting Approval", d.get("status"))
    t1 = task(a1, p1["id"], 1)
    check("Submit PO menghasilkan Level 1 Pending", bool(t1))
    check("Level 2 masih Waiting sebelum Level 1", task(a2, p1["id"], 2, "Waiting") is not None)
    for p in [p1, p2, p3, p4, p5, p7]:
        t = task(a1, p["id"], 1)
        sc, d = a1("POST", f"approvals/{t['id']}/approve", {"note": "L1 OK"})
    check("Approval Level 1 individual tetap normal (200, PO Waiting Approval)", sc == 200 and d.get("status") == "Waiting Approval", (sc, d.get("status")))
    t2 = task(a2, p1["id"], 2)
    check("Level 1 Approve mengaktifkan Level 2 (Pending)", bool(t2))
    t8 = task(a1, p8["id"], 1)
    sc, d = a1("POST", f"approvals/{t8['id']}/reject", {"reason": "revisi"})
    check("Reject Level 1 tetap normal", sc == 200 and d.get("status") == "Rejected", (sc, d.get("status")))

    # ---------------- individual Level 2 diblok
    sc, d = a2("POST", f"approvals/{t2['id']}/approve", {"note": "x"})
    check("Level 2 PO tidak bisa approve individual via API (409 + pesan)", sc == 409 and d.get("detail") == MSG, (sc, d))
    sc, d = a2("POST", f"approvals/{t2['id']}/reject", {"reason": "x"})
    check("Level 2 PO tidak bisa reject individual via API", sc == 409 and d.get("detail") == MSG, (sc, d))
    sc, d = a2("POST", f"po/{p1['id']}/approve", {})
    check("Endpoint PO langsung /po/{id}/approve juga diblok untuk Level 2", sc == 409 and d.get("detail") == MSG, (sc, d))

    # ---------------- eligible
    sc, el = a2("GET", "approval2/po/eligible")
    ids = {r["po_id"]: r for r in el or []}
    check("Level 2 PO muncul di Pengajuan Approval 2", all(p["id"] in ids for p in [p1, p2, p3, p4, p5, p7]), sorted(ids))
    check("PO Level 1 belum approved tidak muncul", p6["id"] not in ids)
    check("PO Rejected tidak muncul", p8["id"] not in ids)
    check("Status awal Siap Diajukan", all(ids[p["id"]]["submission_status"] == "Siap Diajukan" for p in [p1, p2]))
    sc, el1 = a1("GET", "approval2/po/eligible")
    check("User bukan assignee (divisi sama, po_approval2.view) melihat task tetapi tidak dapat approve",
          sc == 200 and p1["id"] in {r["po_id"] for r in el1} and not any(r["can_approve"] for r in el1), el1)
    sc, el3 = a3("GET", "approval2/po/eligible")
    check("User divisi lain (bukan assignee) tidak melihat PO", sc == 200 and not el3, el3)
    sc, el_all = admin("GET", "approval2/po/eligible?scope=all")
    check("Admin scope=all melihat Level 2 (mekanisme scope existing)", sc == 200 and p1["id"] in {r["po_id"] for r in el_all})

    # ---------------- snapshot
    def po_detail(p):
        return call("GET", f"po/{p['id']}")[1]
    r1, r2_, r3 = ids[p1["id"]], ids[p2["id"]], ids[p3["id"]]
    d1, d2, d3 = po_detail(p1), po_detail(p2), po_detail(p3)
    names = ["Grinding Disc", "Cutting Disc", "Kawat Las", "Masker", "Safety Helmet"]
    check("Keterangan transaksi berisi seluruh nama item PO (', ')", r1["transaction_description"] == ", ".join(names), r1["transaction_description"])
    check("Grand Total sesuai total PO (diskon item + diskon final + PPN)", abs(r1["grand_total"] - d1["grand_total"]) < 0.01, (r1["grand_total"], d1["grand_total"]))
    check("PPN sesuai total pajak PO", abs(r1["ppn"] - d1["tax_total"]) < 0.01, (r1["ppn"], d1["tax_total"]))
    check("DPP sesuai total DPP PO (grand - pajak)", abs(r1["dpp"] - (d1["grand_total"] - d1["tax_total"])) < 0.01, (r1["dpp"], d1["grand_total"], d1["tax_total"]))
    check("PO pajak inclusive: DPP+PPN = Grand Total", abs(r3["dpp"] + r3["ppn"] - d3["grand_total"]) < 0.01 and abs(r3["grand_total"] - 111000) < 0.01, r3)
    check("PO tanpa pajak: PPN 0 (UI tampil '-')", r2_["ppn"] == 0 and abs(r2_["grand_total"] - d2["grand_total"]) < 0.01, r2_)
    check("Project single tampil benar", r1["project_text"] == "Project A", r1["project_text"])
    check("Multi project tampil seluruh project unik", r2_["project_text"] == "Project A, Project B", r2_["project_text"])
    check("PIC = creator PO (bukan approver/pembuat batch)", r1["pic_name"] == p1.get("created_by_name") and r1["pic_name"] != "QA l2", r1["pic_name"])
    check("Supplier & PO date dari PO", r1["supplier_name"] == "Supplier X" and str(r1["po_date"]).startswith("2026-10-01"), r1)

    # ---------------- create batch validasi
    batch_ids = [ids[p["id"]]["approval_task_id"] for p in [p1, p2, p3, p4, p5]]
    sc, _ = a2("POST", "approval2/po/batches", {"title": "  ", "submission_date": "2026-10-06", "approval_task_ids": batch_ids})
    check("Batch wajib punya title", sc == 400, sc)
    sc, _ = a2("POST", "approval2/po/batches", {"title": "Project PHR Duri", "submission_date": "", "approval_task_ids": batch_ids})
    check("Batch wajib punya submission date", sc == 400, sc)
    sc, _ = a2("POST", "approval2/po/batches", {"title": "Project PHR Duri", "submission_date": "2026-10-06", "approval_task_ids": []})
    check("Batch wajib minimal 1 PO", sc == 400, sc)
    set_ov(a1, {"po_approval2.submit": "deny"})
    sc, _ = a1("POST", "approval2/po/batches", {"title": "X", "submission_date": "2026-10-06", "approval_task_ids": batch_ids[:1]})
    check("User tanpa po_approval2.submit tidak bisa membuat batch", sc == 403, sc)
    set_ov(a1, {})
    sc, _ = a2("POST", "approval2/po/batches", {"title": "X", "submission_date": "2026-10-06", "approval_task_ids": [task(a1, p6["id"], 1)["id"]]})
    check("Task Level 1 tidak dapat masuk batch", sc in (403, 409), sc)
    sc, B = a2("POST", "approval2/po/batches", {"title": "Project PHR Duri", "submission_date": "2026-10-06", "approval_task_ids": batch_ids})
    check("Batch bisa berisi beberapa PO", sc == 200 and B.get("po_count") == 5 and B.get("status") == "Draft", (sc, B.get("po_count"), B.get("status")))
    check("Nomor batch A2/YYYY/MM/SEQ", bool(re.fullmatch(r"A2/\d{4}/\d{2}/\d{4}", B.get("no") or "")), B.get("no"))
    check("Tanggal pengajuan batch tersimpan (tanggal setiap baris JPEG)", B.get("submission_date") == "2026-10-06")
    it1 = next(i for i in B["items"] if i["po_id"] == p1["id"])
    check("1 PO dengan 5 item tetap 1 row", sum(1 for i in B["items"] if i["po_id"] == p1["id"]) == 1 and len(B["items"]) == 5)
    check("Snapshot batch = nilai resmi PO", abs(it1["grand_total"] - d1["grand_total"]) < 0.01 and it1["transaction_description"] == ", ".join(names))
    check("Footer total = jumlah snapshot", abs(B["total_value"] - sum(i["grand_total"] for i in B["items"])) < 0.01)
    sc, _ = a2("POST", "approval2/po/batches", {"title": "Dup", "submission_date": "2026-10-06", "approval_task_ids": batch_ids[:1]})
    check("Satu Level 2 task tidak masuk dua batch aktif", sc == 409, sc)
    sc, el = a2("GET", "approval2/po/eligible")
    st = {r["po_id"]: r for r in el}
    check("Setelah batch: PO Sudah Diajukan (masih Level 2 Pending)", st[p1["id"]]["submission_status"] == "Sudah Diajukan" and st[p1["id"]]["batch_no"] == B["no"])

    t7 = ids[p7["id"]]["approval_task_id"]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: a2("POST", "approval2/po/batches", {"title": "Race", "submission_date": "2026-10-06", "approval_task_ids": [t7]}), range(4)))
    okc = [r for r in res if r[0] == 200]
    check("Race create batch: tepat 1 batch berhasil untuk task yang sama", len(okc) == 1 and all(r[0] == 409 for r in res if r[0] != 200), [r[0] for r in res])
    check("Nomor batch tidak dipakai ulang", okc and okc[0][1]["no"] != B["no"])

    # ---------------- export / submit
    bid = B["id"]
    sc, d = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("Approve pada batch Draft (belum export) ditolak", sc == 409, sc)
    sc, d = a2("POST", f"approval2/po/batches/{bid}/submit", {})
    check("Export -> status Diajukan", sc == 200 and d["status"] == "Diajukan" and d.get("submitted_at"), d.get("status"))
    sc, d = a2("POST", f"approval2/po/batches/{bid}/submit", {})
    sc, bl = a2("GET", "approval2/po/batches")
    check("Export berulang tidak membuat batch baru", sc == 200 and d["status"] == "Diajukan" and sum(1 for x in bl if x["title"] == "Project PHR Duri") == 1)
    check("Export tidak meng-approve (PO tetap Waiting Approval, task Pending)", po_detail(p1)["status"] == "Waiting Approval" and task(a2, p1["id"], 2) is not None)

    # ---------------- security
    sc, _ = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("Approve tanpa attachment bukti ditolak", sc == 400, sc)
    sc, _ = a2.upload("po_approval2_batch", bid, "wa-approval.png", PNG, "image/png")
    check("Upload bukti tanpa izin upload_attachment ditolak", sc == 403, sc)
    sc, a2u = call("GET", "users")
    a2id = next(u["id"] for u in (a2u if isinstance(a2u, list) else a2u.get("items", [])) if u["email"] == a2.email)
    call("PUT", f"access/users/{a2id}", {"overrides": {"upload_attachment": "allow"}, "division_override": {"mode": "selected", "divisions": [M["div"]["id"]]}}, 200)
    sc, _ = a2.upload("po_approval2_batch", bid, "catatan.txt", b"hello", "text/plain")
    check("Bukti format tidak diizinkan ditolak", sc == 400, sc)
    sc, ev = a2.upload("po_approval2_batch", bid, "wa-approval.png", PNG, "image/png")
    check("Upload bukti persetujuan (PNG) berhasil, kategori Bukti Approval 2", sc == 200 and ev.get("category") == "Bukti Approval 2", (sc, ev))
    sc, _ = a3("GET", f"approval2/po/batches/{bid}")
    check("User divisi lain tidak dapat melihat batch", sc == 404, sc)
    sc, _ = a3("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("User divisi lain tidak dapat approve batch", sc in (403, 404), sc)
    sc, _ = a1("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("User bukan assignee ditolak", sc in (403, 404), sc)
    sc, _ = admin("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("Admin (bukan exact assignee) tetap ditolak approve", sc == 403, sc)
    ten = requests.Session(); u = uuid.uuid4().hex[:8]
    r = ten.post(f"{API}/saas/register", json={"company_name": f"A2X {u}", "pic_name": "QA", "email": f"a2x_{u}@example.com", "whatsapp": "+628123456789",
                                               "workspace_slug": f"a2x-{u}", "plan_code": "starter", "password": PW, "address": "x", "terms_accepted": True})
    other = U(f"a2x_{u}@example.com", r.json().get("token"))
    sc, _ = other("GET", f"approval2/po/batches/{bid}")
    check("Tenant lain ditolak (detail batch)", sc == 404, sc)
    sc, _ = other("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("Tenant lain ditolak (approve)", sc in (403, 404), sc)
    sc, lst = other("GET", "approval2/po/batches")
    check("Tenant lain tidak melihat batch", sc == 200 and not lst)
    sc, _ = other.upload("po_approval2_batch", bid, "x.png", PNG, "image/png")
    check("Tenant lain tidak bisa upload bukti ke batch", sc in (403, 404), sc)

    # ---------------- partial approval
    sel = [i["id"] for i in B["items"] if i["po_id"] in (p1["id"], p3["id"], p5["id"])]
    sc, d = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": sel})
    check("Partial approve 3 PO berhasil", sc == 200, (sc, d))
    check("Batch berubah Selesai Sebagian", d.get("status") == "Selesai Sebagian", d.get("status"))
    for p in (p1, p3, p5):
        x = po_detail(p)
        appr = {a["seq"]: a["status"] for a in x.get("approvals") or []}
        check(f"{x['no']}: PO Approved + approval_status Approved", x["status"] == "Approved" and x.get("approval_status") == "Approved", (x["status"], x.get("approval_status")))
        check(f"{x['no']}: po_approvals sinkron (L1+L2 Approved)", appr.get(1) == "Approved" and appr.get(2) == "Approved", appr)
        check(f"{x['no']}: approval_tasks Level 2 Approved", task(a2, p["id"], 2, "Approved") is not None)
    for p in (p2, p4):
        x = po_detail(p)
        check(f"{x['no']}: PO lain di batch tetap Level 2 Pending", x["status"] == "Waiting Approval" and task(a2, p["id"], 2) is not None)
    sc, a_p1 = call("GET", f"attachments?entity=po&entity_id={p1['id']}")
    sc, a_p3 = call("GET", f"attachments?entity=po&entity_id={p3['id']}")
    sc, a_b = call("GET", f"attachments?entity=po_approval2_batch&entity_id={bid}")
    sc, a_p2 = call("GET", f"attachments?entity=po&entity_id={p2['id']}")
    ref1 = next((a for a in a_p1 if a.get("category") == "Bukti Approval 2"), None)
    ref3 = next((a for a in a_p3 if a.get("category") == "Bukti Approval 2"), None)
    src = next((a for a in a_b if a.get("id") == ev.get("id")), None)
    check("Bukti otomatis muncul pada attachment PO approved (note batch)", bool(ref1) and ref1.get("note") == f"Approval 2 Batch {B['no']}", ref1)
    check("Satu storage object direferensikan ke banyak PO (bukan upload ulang)",
          bool(ref1 and ref3 and src) and ref1["storage_path"] == src["storage_path"] == ref3["storage_path"] and len({ref1["id"], ref3["id"], src["id"]}) == 3)
    check("Referensi menyimpan source_attachment_id/source_entity", ref1 and ref1.get("source_attachment_id") == ev["id"] and ref1.get("source_entity") == "po_approval2_batch" and ref1.get("source_entity_id") == bid)
    check("PO yang belum di-approve tidak mendapat lampiran bukti", not any(a.get("category") == "Bukti Approval 2" for a in a_p2))
    r_dl = admin.S.get(f"{API}/attachments/{ref1['id']}/download")
    check("Lampiran referensi PO dapat diunduh", r_dl.status_code == 200 and r_dl.content == PNG, r_dl.status_code)
    sc, _ = call("DELETE", f"attachments/{ref1['id']}")
    r_dl2 = admin.S.get(f"{API}/attachments/{ref3['id']}/download")
    r_dl3 = a2.S.get(f"{API}/attachments/{ev['id']}/download")
    check("Hapus referensi di satu PO tidak menghapus file fisik (PO lain & batch tetap bisa unduh)", r_dl2.status_code == 200 and r_dl3.status_code == 200, (r_dl2.status_code, r_dl3.status_code))

    # ---------------- double / race approve
    sc, _ = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it1["id"]]})
    check("Double approve item yang sudah Approved ditolak", sc == 409, sc)
    it2 = next(i for i in B["items"] if i["po_id"] == p2["id"])
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda _: a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it2["id"]]}), range(4)))
    check("Race approve: tepat 1 berhasil", sum(1 for r in res if r[0] == 200) == 1 and all(r[0] in (200, 409) for r in res), [r[0] for r in res])
    sc, au2 = call("GET", f"audit?entity=po&entity_id={p2['id']}")
    check("Race approve tidak menghasilkan approval ganda", sum(1 for a in au2 if a["action"] == "approve") == 2 and sum(1 for a in au2 if a["action"] == "approval2_batch_approve") == 1,
          [a["action"] for a in au2])
    x2 = po_detail(p2)
    check("PO race -> Approved sekali", x2["status"] == "Approved" and [a["status"] for a in x2["approvals"]].count("Approved") == 2)

    it4 = next(i for i in B["items"] if i["po_id"] == p4["id"])
    sc, d = a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": [it4["id"]]})
    check("Setelah seluruh item approved -> Selesai", sc == 200 and d.get("status") == "Selesai" and d.get("completed_at"), (sc, d.get("status")))

    # ---------------- audit
    sc, ab = a2("GET", f"audit?entity=po_approval2_batch&entity_id={bid}")
    acts = {a["action"] for a in ab or []}
    need = {"create", "add_po", "submit", "export", "upload_approval_evidence", "bulk_approve"}
    check("Audit batch lengkap (create/add_po/submit/export/upload/bulk_approve)", need <= acts, sorted(acts))
    sc, ap = call("GET", f"audit?entity=po&entity_id={p1['id']}")
    rec = next((a for a in ap if a["action"] == "approval2_batch_approve"), {})
    check("Audit per PO: Approval 2 approved via batch + actor/batch/bukti",
          rec.get("reason") == f"Approval 2 approved via batch {B['no']}" and rec.get("user") == a2.email
          and (rec.get("after") or {}).get("batch_no") == B["no"] and (rec.get("after") or {}).get("evidence_attachment_id") == ev["id"], rec)

    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\n{ok}/{len(T.RESULTS)} passed")
    return 0 if ok == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
