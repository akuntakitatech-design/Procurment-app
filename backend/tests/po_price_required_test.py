"""Harga Satuan PO wajib diisi (> 0) — E2E (throwaway tenant, localhost:8001).

Simpan PO baru / edit / submit / approve (individual, inbox, Pengajuan Approval 2) ditolak bila ada baris
Harga Satuan kosong atau 0. PO lama yang terlanjur Rp 0 disimulasikan dengan mengubah baris di DB tenant uji.
"""
import sys
from urllib.parse import unquote, urlparse

import pymysql

import receipt_control_test as T
import po_approval2_batch_test as A

call, check = T.call, T.check
MSG = "Harga Satuan wajib diisi (lebih dari 0)"


def zero_price_in_db(po_id):
    # DB = DB backend yang diuji (TEST_DATABASE_URL runner terisolasi, konsisten T.test_env()); hanya DB test terisolasi.
    u = urlparse(T.test_env()["DATABASE_URL"].strip().strip('"').replace("mariadb://", "mysql://"))
    dbn = u.path.strip("/")
    if "itest" not in dbn and not dbn.endswith("_test"):
        sys.exit(f"STOP: helper DB menolak database '{dbn}' (bukan DB test terisolasi *itest* / *_test)")
    c = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""),
                        database=u.path.strip("/"), autocommit=True)
    with c.cursor() as cur:
        cur.execute("UPDATE po_lines SET doc = JSON_SET(doc, '$.price', 0) WHERE po_id = %s", (po_id,))
    c.close()


def main():
    M = T.setup()
    body = lambda lines: {"supplier_id": M["supX"]["id"], "division_id": M["div"]["id"], "date": "2026-10-06", "lines": lines}  # noqa: E731
    good = A.line(M, "item", 2, 15000)
    for label, price in (("0", 0), ("kosong ''", ""), ("null", None)):
        sc, d = call("POST", "po", body([good, {**A.line(M, "item2", 1, 1), "price": price}]))
        check(f"Simpan PO baru dengan Harga Satuan {label} ditolak", sc == 400 and MSG in str(d.get("detail")) and "baris 2" in str(d.get("detail")), (sc, d))
    ln = A.line(M, "item2", 1, 1); ln.pop("price")
    sc, d = call("POST", "po", body([ln]))
    check("Simpan PO tanpa field Harga Satuan ditolak", sc == 400 and MSG in str(d.get("detail")), (sc, d))
    sc, d = call("POST", "po", body([{**A.line(M, "item2", 1, 1), "price": -5}]))
    check("Harga Satuan negatif ditolak", sc == 400, sc)
    sc, po = call("POST", "po", body([good, A.line(M, "item2", 1, 120000)]))
    check("PO dengan semua Harga Satuan terisi tersimpan", sc == 200 and po.get("status") == "Draft", sc)

    sc, d = call("PUT", f"transactions/po/{po['id']}", {**body([good, {**A.line(M, "item2", 1, 1), "price": 0}])})
    check("Edit PO menjadi Harga Satuan 0 ditolak", sc == 400 and MSG in str(d.get("detail")), (sc, d))
    sc, d = call("PUT", f"transactions/po/{po['id']}", body([good, A.line(M, "item2", 3, 125000)]))
    check("Edit PO dengan harga valid tetap normal", sc == 200, (sc, d))

    # PO lama terlanjur Rp 0 -> tidak bisa submit
    sc, legacy = call("POST", "po", body([A.line(M, "item", 1, 1000)]))
    zero_price_in_db(legacy["id"])
    sc, d = call("POST", f"po/{legacy['id']}/submit", {})
    check("Submit PO lama dengan Harga Satuan Rp 0 ditolak", sc == 400 and MSG in str(d.get("detail")) and legacy["no"] in str(d.get("detail")), (sc, d))
    check("PO tetap Draft setelah submit ditolak", call("GET", f"po/{legacy['id']}")[1].get("status") == "Draft")

    # Approval: PO terlanjur Waiting Approval dengan harga 0 tidak bisa di-approve (L1 inbox, L2 batch); reject tetap bisa
    a1, a2 = A.mk_user("p1", [M["div"]["id"]]), A.mk_user("p2", [M["div"]["id"]])
    call("PUT", "settings/approval_modules", {"modules": {"mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
                                                           "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}, {"level": 2, "email": a2.email}]}}}, 200)
    pa = A.mk_po(M, [A.line(M, "item", 1, 5000)])
    pb = A.mk_po(M, [A.line(M, "item", 1, 6000)])
    pc = A.mk_po(M, [A.line(M, "item", 1, 7000)])
    for p in (pa, pb, pc):
        call("POST", f"po/{p['id']}/submit", {}, 200)
    zero_price_in_db(pa["id"])
    ta = A.task(a1, pa["id"], 1)
    sc, d = a1("POST", f"approvals/{ta['id']}/approve", {"note": "x"})
    check("Approve Level 1 PO dengan Harga Satuan 0 ditolak", sc == 400 and MSG in str(d.get("detail")), (sc, d))
    sc, d = a1("POST", f"po/{pa['id']}/approve", {})
    check("Endpoint /po/{id}/approve (assignee) juga menolak Harga Satuan 0", sc == 400 and MSG in str(d.get("detail")), (sc, d))
    sc, d = call("POST", f"po/{pa['id']}/approve", {})
    check("Bukan assignee tetap ditolak lebih dulu oleh cek assignment (403)", sc == 403, (sc, d))
    sc, d = a1("POST", f"approvals/{ta['id']}/reject", {"reason": "harga belum diisi"})
    check("Reject PO Harga Satuan 0 tetap diizinkan", sc == 200 and d.get("status") == "Rejected", (sc, d.get("status")))
    for p in (pb, pc):
        t = A.task(a1, p["id"], 1)
        sc, d = a1("POST", f"approvals/{t['id']}/approve", {"note": "ok"})
    check("Approve Level 1 PO dengan harga valid tetap normal", sc == 200 and d.get("status") == "Waiting Approval", (sc, d.get("status")))
    zero_price_in_db(pb["id"])
    tb, tc = A.task(a2, pb["id"], 2), A.task(a2, pc["id"], 2)
    sc, d = a2("POST", "approval2/po/batches", {"title": "Uji Harga", "submission_date": "2026-10-06", "approval_task_ids": [tb["id"], tc["id"]]})
    check("Buat Pengajuan Approval 2 berisi PO Harga Satuan 0 ditolak", sc == 400 and MSG in str(d.get("detail")) and pb["no"] in str(d.get("detail")), (sc, d))
    sc, B = a2("POST", "approval2/po/batches", {"title": "Uji Harga", "submission_date": "2026-10-06", "approval_task_ids": [tc["id"]]})
    check("Pengajuan Approval 2 PO harga valid tetap normal", sc == 200, sc)
    a2("POST", f"approval2/po/batches/{B['id']}/submit", {})
    sc, us = call("GET", "users")
    uid = next(u["id"] for u in (us if isinstance(us, list) else us.get("items", [])) if u["email"] == a2.email)
    call("PUT", f"access/users/{uid}", {"overrides": {"upload_attachment": "allow"}, "division_override": {"mode": "selected", "divisions": [M["div"]["id"]]}}, 200)
    a2.upload("po_approval2_batch", B["id"], "wa.png", A.PNG, "image/png")
    zero_price_in_db(pc["id"])
    sc, d = a2("POST", f"approval2/po/batches/{B['id']}/approve", {"item_ids": [B["items"][0]["id"]]})
    check("Approve Terpilih PO Harga Satuan 0 ditolak", sc == 400 and MSG in str(d.get("detail")), (sc, d))
    check("PO tetap Waiting Approval (tidak ter-approve sebagian)", call("GET", f"po/{pc['id']}")[1].get("status") == "Waiting Approval")

    ok = sum(1 for _, c in T.RESULTS if c)
    print(f"\n{ok}/{len(T.RESULTS)} passed")
    return 0 if ok == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
