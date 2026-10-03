"""Tahap 3 — Invoice Vendor E2E (throwaway tenants, localhost). DO -> Invoice -> Pembayaran -> Monitoring."""
import sys
import uuid

import requests

import receipt_control_test as T

call, check, API, M = T.call, T.check, T.API, None
PW = "TestPass123!"


class U:
    def __init__(self, email):
        self.S = requests.Session()
        tok = self.S.post(f"{API}/auth/login", json={"email": email, "password": PW}).json().get("token")
        if tok:
            self.S.headers.update({"Authorization": f"Bearer {tok}"})

    def __call__(self, method, path, body=None, **kw):
        r = self.S.request(method, f"{API}/{path}", json=body, **kw)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}


def mk_user(role, overrides=None, divs=None):
    email = f"iv_{role}_{uuid.uuid4().hex[:6]}@example.com"
    sc, u = call("POST", "users", {"email": email, "password": PW, "name": f"QA {role}", "role": role}, 200)
    body = {"overrides": overrides or {}}
    if divs is not None:
        body["division_override"] = {"mode": "selected", "divisions": divs}
    call("PUT", f"access/users/{u['id']}", body, 200)
    return U(email)


def mk_do(supplier, qty):
    po, _, _ = T.make_po(M, supplier, qty)
    sc, d = call("POST", "do", T.do_body(M, po, qty, supplier), 200)
    return po, d


def inv_body(no, supplier, allocs, amount=None, **kw):
    total = sum(a for _, a in allocs)
    return {"supplier_id": M[supplier]["id"], "invoice_no": no, "invoice_date": "2026-06-01", "received_date": "2026-06-02",
            "due_date": kw.pop("due", "2026-07-01"), "amount": total if amount is None else amount, "tax_amount": 0,
            "allocations": [{"do_id": d["id"], "amount": a} for d, a in allocs], **kw}


def billing(do_id, u=None):
    return (u or call)("GET", f"vendor-invoices/do/{do_id}")[1]


def stock_snapshot():
    sc, rows = call("GET", f"item-warehouse?item_id={M['item']['id']}")
    return sorted((r.get("warehouse_id"), r.get("qty"), r.get("avg_cost"), r.get("total_value")) for r in rows or [])


def main():
    global M
    M = T.setup()
    T.M = M
    po1, d1 = mk_do("supX", 10000)
    po2, d2 = mk_do("supX", 15000)
    po3, d3 = mk_do("supX", 5000)
    sc, el = call("GET", f"vendor-invoices/eligible-dos?supplier_id={M['supX']['id']}")
    vals = {r["do_no"]: r["do_value"] for r in el or []}
    check("eligible DO values = qty x harga netto PO", vals.get(d1["no"]) == 10_000_000 and vals.get(d3["no"]) == 5_000_000, vals)
    po_before = call("GET", f"po/{po1['id']}")[1]

    # 1. 3 DO supplier sama -> 1 invoice
    sc, inv1 = call("POST", "vendor-invoices", inv_body("INV-001", "supX", [(d1, 10_000_000), (d2, 15_000_000), (d3, 5_000_000)]))
    check("1. 3 DO supplier sama -> 1 invoice Rp30jt", sc == 200 and inv1.get("amount") == 30_000_000 and len(inv1.get("allocations") or []) == 3, (sc, inv1))
    check("1b. ketiga DO Sudah Ditagihkan Penuh", all(billing(d["id"])["billing_status"] == "Sudah Ditagihkan Penuh" for d in (d1, d2, d3)))
    check("1c. status invoice Diterima + Belum Dibayar", inv1.get("status") == "Diterima" and inv1.get("payment_status") == "Belum Dibayar")

    # 2. DO supplier berbeda -> BLOCK (API dipaksa)
    _, dY = mk_do("supY", 1000)
    _, d6 = mk_do("supX", 1000)
    _, d7 = mk_do("supX", 1000)
    sc, r = call("POST", "vendor-invoices", inv_body("INV-MIX", "supX", [(d6, 1_000_000), (dY, 1_000_000)]))
    check("2. DO supplier berbeda dalam 1 invoice -> BLOCK", sc == 400 and "Supplier lain" in str(r), (sc, r))

    # 3/4/5. 1 DO ditagihkan bertahap
    po5, d5 = mk_do("supX", 20000)
    sc, inv2 = call("POST", "vendor-invoices", inv_body("INV-002", "supX", [(d5, 12_000_000)]))
    b = billing(d5["id"])
    check("3. DO Rp20jt -> invoice Rp12jt -> Ditagihkan Sebagian, sisa Rp8jt", sc == 200 and b["billing_status"] == "Ditagihkan Sebagian" and b["remaining"] == 8_000_000, b)
    sc, r = call("POST", "vendor-invoices", inv_body("INV-002B", "supX", [(d5, 8_000_001)]))
    check("4a. alokasi melebihi sisa Rp8jt -> BLOCK", sc == 409, (sc, r))
    sc, inv3 = call("POST", "vendor-invoices", inv_body("INV-003", "supX", [(d5, 8_000_000)]))
    b = billing(d5["id"])
    check("4. invoice kedua Rp8jt -> Sudah Ditagihkan Penuh", sc == 200 and b["billing_status"] == "Sudah Ditagihkan Penuh" and b["remaining"] == 0, b)
    sc, r = call("POST", "vendor-invoices", inv_body("INV-004", "supX", [(d5, 1)]))
    check("5. setelah penuh, alokasi tambahan Rp1 -> BLOCK", sc == 409, (sc, r))

    # 6. selisih wajib alasan
    sc, r = call("POST", "vendor-invoices", inv_body("INV-006", "supX", [(d6, 1_000_000)], amount=1_050_000))
    check("6a. total alokasi != nilai invoice tanpa alasan -> 400", sc == 400 and "Alasan Selisih" in str(r), (sc, r))
    sc, inv6 = call("POST", "vendor-invoices", inv_body("INV-006", "supX", [(d6, 1_000_000)], amount=1_050_000, diff_reason="Ongkos kirim ditagihkan vendor"))
    check("6b. dengan alasan -> tersimpan, status Ada Selisih", sc == 200 and inv6.get("diff_status") == "Ada Selisih" and inv6.get("diff") == 50_000, (sc, inv6))

    # duplicate Supplier + No Invoice
    for variant in ("INV-001", " inv-001 "):
        sc, r = call("POST", "vendor-invoices", inv_body(variant, "supX", [(d7, 1)]))
        check(f"duplicate Supplier+No Invoice '{variant}' -> 409", sc == 409, (sc, r))
    sc, invY = call("POST", "vendor-invoices", inv_body("INV-001", "supY", [(dY, 1_000_000)]))
    check("No Invoice sama untuk Supplier lain diizinkan", sc == 200, (sc, invY))

    # 7. histori invoice per DO
    b = billing(d5["id"])
    check("7. histori invoice per DO (2 invoice, total Rp20jt)", sorted(i["invoice_no"] for i in b["invoices"]) == ["INV-002", "INV-003"] and b["billed"] == 20_000_000, b)

    # 8. traceability Invoice -> DO -> PO -> RO -> MRO
    a = next((x for x in inv1.get("allocations") or [] if x["do_id"] == d1["id"]), {})
    check("8. traceability Invoice -> DO -> PO -> RO -> MRO", a.get("do_no") == d1["no"] and po1["no"] in str(a.get("trace_po")) and a.get("trace_ro") and a.get("trace_mro"), a)

    # pembayaran
    stock_before = stock_snapshot()
    iid = inv2["id"]
    sc, r = call("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-10", "amount": 5_000_000, "reference": "TRF-1"})
    check("pembayaran sebagian -> Dibayar Sebagian, sisa Rp7jt", sc == 200 and r["payment_status"] == "Dibayar Sebagian" and r["remaining"] == 7_000_000, (sc, r.get("payment_status"), r.get("remaining")))
    sc, r = call("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-11", "amount": 7_000_001})
    check("pembayaran melebihi sisa -> BLOCK", sc == 409, (sc, r))
    sc, r = call("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-12", "amount": 7_000_000, "reference": "TRF-2"})
    check("pembayaran penuh -> Lunas, sisa 0", sc == 200 and r["payment_status"] == "Lunas" and r["remaining"] == 0, (sc, r.get("payment_status")))
    check("histori pembayaran tidak ditimpa (2 baris)", len(r.get("payments") or []) == 2)
    p2 = r["payments"][1]["id"]
    sc, r = call("POST", f"vendor-invoices/{iid}/payments/{p2}/cancel", {})
    check("batalkan pembayaran tanpa alasan -> 400", sc == 400)
    sc, r = call("POST", f"vendor-invoices/{iid}/payments/{p2}/cancel", {"reason": "Salah input nominal"})
    check("batalkan pembayaran -> Dibayar Sebagian, riwayat tetap ada", sc == 200 and r["payment_status"] == "Dibayar Sebagian" and len(r["payments"]) == 2 and r["payments"][1]["status"] == "Dibatalkan", (sc, r.get("payment_status")))
    sc, r = call("DELETE", f"vendor-invoices/{iid}")
    check("hapus invoice dengan pembayaran aktif -> BLOCK", sc == 409, (sc, r))
    sc, r = call("DELETE", f"vendor-invoices/{inv3['id']}")
    check("hapus invoice tanpa pembayaran -> DO kembali Ditagihkan Sebagian", sc == 200 and billing(d5["id"])["billing_status"] == "Ditagihkan Sebagian")
    sc, r = call("PUT", f"vendor-invoices/{inv1['id']}", {"notes": "Revisi catatan", "edit_reason": "Koreksi"})
    check("edit invoice (catatan) tersimpan", sc == 200 and r.get("notes") == "Revisi catatan", (sc, r))
    sc, r = call("PUT", f"vendor-invoices/{iid}", {"amount": 1_000_000, "allocations": [{"do_id": d5["id"], "amount": 1_000_000}]})
    check("edit nilai invoice di bawah total dibayar -> BLOCK", sc == 409, (sc, r))

    # audit
    sc, logs = call("GET", f"audit?entity=invoice&entity_id={iid}")
    acts = {x.get("action") for x in logs or []}
    check("audit: create + payment + payment_cancel tercatat", {"create", "payment", "payment_cancel"} <= acts, acts)
    check("audit pembatalan menyimpan alasan", any(x.get("action") == "payment_cancel" and x.get("reason") == "Salah input nominal" for x in logs or []))

    # business rule: tidak mengubah PO / DO / stok / Moving Average
    po_after = call("GET", f"po/{po1['id']}")[1]
    check("PO tidak berubah (grand total + qty)", po_after.get("grand_total") == po_before.get("grand_total") and [x["qty"] for x in po_after["lines"]] == [x["qty"] for x in po_before["lines"]])
    check("stok & Moving Average tidak berubah karena invoice/pembayaran", stock_snapshot() == stock_before, (stock_before, stock_snapshot()))
    sc, rec = call("GET", "reports/valuation-reconcile")
    check("valuation reconcile tetap ok", sc == 200 and rec.get("ok") is True, str(rec)[:200])
    sc, r = call("DELETE", f"transactions/do/{d1['id']}")
    check("DO yang sudah ditagihkan tidak bisa dihapus", sc == 409 and "INVOICE" in str(r).upper(), (sc, r))
    sc, cap = call("GET", f"transactions/do/{d1['id']}/capability")
    check("capability DO menunjukkan blocker invoice", sc == 200 and not cap.get("can_delete"), cap)

    # monitoring + summary
    sc, rows = call("GET", "vendor-invoices")
    r1 = next((x for x in rows if x["id"] == inv1["id"]), {})
    check("monitoring: kolom PO/DO/SPK/Proyek/Divisi/Sisa terisi", r1.get("trace_po") and d1["no"] in r1.get("do_nos", "") and r1.get("trace_project") and r1.get("trace_division") and r1.get("remaining") == 30_000_000, r1)
    sc, s = call("GET", "vendor-invoices/summary")
    check("summary: hutang vendor = total sisa invoice", sc == 200 and s["total_payable"] == round(sum(x["remaining"] for x in rows), 2) and s["invoice_received"] == len(rows), s)
    call("POST", "vendor-invoices", inv_body("INV-OVD", "supX", [(d7, 0.01)], amount=0.01, due="2026-01-31", invoice_date="2026-01-01", received_date="2026-01-02"))
    sc, s2 = call("GET", "vendor-invoices/summary")
    check("summary: Invoice Lewat Jatuh Tempo terhitung", s2.get("overdue", 0) >= 1, s2)

    # multi lampiran invoice
    def up(sess, entity, eid, name, body=None):
        r = sess.post(f"{API}/attachments", files={"file": (name, body or f"%PDF-1.4 {name}".encode(), "application/pdf")}, data={"entity": entity, "entity_id": eid})
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})

    def files_of(iid):
        return call("GET", f"vendor-invoices/{iid}")[1]

    ups = [up(T.S, "invoice", inv1["id"], n) for n in ("invoice.pdf", "faktur-pajak.pdf", "rekap-tagihan.pdf")]
    check("lampiran: 1 invoice dengan 3 lampiran", all(sc == 200 for sc, _ in ups) and len(files_of(inv1["id"])["files"]) == 3, ups)
    sc, extra = up(T.S, "invoice", inv1["id"], "surat-jalan.pdf")
    check("lampiran: tambah lampiran setelah invoice tersimpan", sc == 200 and len(files_of(inv1["id"])["files"]) == 4)
    sc, _ = call("DELETE", f"attachments/{ups[1][1]['id']}")
    left = files_of(inv1["id"])["files"]
    okdl = all(T.S.get(f"{API}/attachments/{f['id']}/download").content == f"%PDF-1.4 {f['original_filename']}".encode() for f in left)
    check("lampiran: hapus 1 lampiran -> lampiran lain tetap utuh", sc == 200 and sorted(f["original_filename"] for f in left) == ["invoice.pdf", "rekap-tagihan.pdf", "surat-jalan.pdf"] and okdl, left)
    fid = ups[0][1]["id"]
    pays = call("GET", f"vendor-invoices/{iid}")[1]["payments"]
    p1 = pays[0]["id"]
    a1 = [up(T.S, "invoice_payment", p1, n) for n in ("bukti-transfer-1.pdf", "advice-bank-1.pdf")]
    sc, r = call("POST", f"vendor-invoices/{iid}/payments", {"date": "2026-06-13", "amount": 1000, "reference": "TRF-3"})
    p3 = next(x["id"] for x in r["payments"] if x["id"] not in {y["id"] for y in pays})
    a2 = [up(T.S, "invoice_payment", p3, n) for n in ("bukti-transfer-2.pdf", "bukti-potong-2.pdf")]
    det = call("GET", f"vendor-invoices/{iid}")[1]
    att = {p["id"]: sorted(a["original_filename"] for a in p["attachments"]) for p in det["payments"]}
    check("lampiran: 1 pembayaran dengan 2 lampiran", all(x[0] == 200 for x in a1) and att[p1] == ["advice-bank-1.pdf", "bukti-transfer-1.pdf"], att)
    check("lampiran: pembayaran kedua dengan lampiran berbeda", all(x[0] == 200 for x in a2) and att[p3] == ["bukti-potong-2.pdf", "bukti-transfer-2.pdf"], att)
    check("lampiran: lampiran pembayaran pertama tetap utuh", all(T.S.get(f"{API}/attachments/{x[1]['id']}/download").content == f"%PDF-1.4 {x[1]['original_filename']}".encode() for x in a1))
    cancelled = next(p["id"] for p in det["payments"] if p["status"] == "Dibatalkan")
    check("lampiran: pembayaran dibatalkan tidak bisa ditambah lampiran", up(T.S, "invoice_payment", cancelled, "x.pdf")[0] == 409)
    n_before = len(call("GET", f"attachments?entity=invoice&entity_id={inv1['id']}")[1])
    sc_missing, _ = up(T.S, "invoice", "tidak-ada", "orphan.pdf")
    sc_bad, _ = up(T.S, "invoice", inv1["id"], "virus.exe", b"MZ")
    check("lampiran: penyimpanan gagal -> tidak ada record/file yatim", sc_missing == 404 and sc_bad == 400 and len(call("GET", f"attachments?entity=invoice&entity_id={inv1['id']}")[1]) == n_before, (sc_missing, sc_bad))
    sc, logs = call("GET", f"audit?entity=invoice&entity_id={inv1['id']}")
    ups_log = [x for x in logs if x.get("action") == "upload_file"]
    dels_log = [x for x in logs if x.get("action") == "delete_file"]
    check("audit lampiran: unggah & hapus tercatat dengan jenis induk, tanpa isi file", len(ups_log) == 4 and len(dels_log) == 1 and all(x.get("user") and x.get("at") and (x.get("after") or {}).get("induk") == "Invoice" for x in ups_log) and "PDF-1.4" not in str(logs), (len(ups_log), len(dels_log)))
    sc, plog = call("GET", f"audit?entity=invoice&entity_id={iid}")
    check("audit lampiran pembayaran: induk Pembayaran", sum(1 for x in plog if x.get("action") == "upload_file" and (x.get("after") or {}).get("induk") == "Pembayaran") == 4)

    # permission
    wh = mk_user("warehouse")
    check("permission: role Gudang tanpa izin -> list 403", wh("GET", "vendor-invoices")[0] == 403)
    check("permission: role Gudang tanpa izin -> tambah 403", wh("POST", "vendor-invoices", inv_body("X-1", "supX", [(d7, 1)]))[0] == 403)
    mg = mk_user("manager", divs=[M["div"]["id"]])
    check("permission: Manajer (Lihat) -> list 200", mg("GET", "vendor-invoices")[0] == 200)
    check("permission: Manajer tanpa Tambah -> 403", mg("POST", "vendor-invoices", inv_body("X-2", "supX", [(d7, 1)]))[0] == 403)
    check("permission: Manajer tanpa Catat Pembayaran -> 403", mg("POST", f"vendor-invoices/{inv1['id']}/payments", {"date": "2026-06-10", "amount": 1})[0] == 403)
    check("permission: Manajer tanpa Edit/Hapus -> 403", mg("PUT", f"vendor-invoices/{inv1['id']}", {"notes": "x"})[0] == 403 and mg("DELETE", f"vendor-invoices/{inv6['id']}")[0] == 403)
    wh2 = mk_user("warehouse", overrides={"invoice.view": "allow", "invoice.pay": "allow"}, divs=[M["div"]["id"]])
    sc, r = wh2("POST", f"vendor-invoices/{inv1['id']}/payments", {"date": "2026-06-10", "amount": 1000, "reference": "OV"})
    check("permission: override user Izinkan Catat Pembayaran -> 200", sc == 200, (sc, r))
    check("lampiran: user tanpa izin Invoice -> unduh 403", wh("GET", f"attachments/{fid}/download")[0] == 403)
    check("lampiran: user tanpa izin Invoice -> daftar lampiran 403", wh("GET", f"attachments?entity=invoice&entity_id={inv1['id']}")[0] == 403)
    check("lampiran: Manajer (Lihat) bisa unduh", mg("GET", f"attachments/{fid}/download")[0] == 200)
    check("lampiran: Manajer tanpa Edit -> unggah lampiran invoice 403", up(mg.S, "invoice", inv1["id"], "m.pdf")[0] == 403)
    check("lampiran: Manajer tanpa Catat Pembayaran -> unggah/hapus lampiran pembayaran 403", up(mg.S, "invoice_payment", p1, "m.pdf")[0] == 403 and mg("DELETE", f"attachments/{a1[0][1]['id']}")[0] == 403)
    check("lampiran: hak Catat Pembayaran tanpa Edit -> lampiran invoice 403, lampiran pembayaran 200", up(wh2.S, "invoice", inv1["id"], "w.pdf")[0] == 403 and up(wh2.S, "invoice_payment", p1, "w.pdf")[0] == 200)
    check("permission: override tanpa Tambah tetap 403 pada eligible-dos", wh2("GET", f"vendor-invoices/eligible-dos?supplier_id={M['supX']['id']}")[0] == 403)

    # cakupan divisi
    sc, dB = call("POST", "master/divisions", {"code": f"DB{uuid.uuid4().hex[:4]}", "name": "Divisi B"}, 200)
    divA = M["div"]
    M["div"] = dB
    _, dB1 = mk_do("supX", 2000)
    M["div"] = divA
    sc, invB = call("POST", "vendor-invoices", inv_body("INV-B", "supX", [(dB1, 1_000_000)]))
    sc, invAB = call("POST", "vendor-invoices", inv_body("INV-AB", "supX", [(dB1, 500_000), (d7, 0.01)], amount=500_000.01))
    ids = {x["id"] for x in mg("GET", "vendor-invoices")[1]}
    check("divisi: user Divisi A melihat invoice A", inv1["id"] in ids)
    check("divisi: invoice Divisi B tersembunyi dari user Divisi A", invB["id"] not in ids)
    check("divisi: invoice multi-divisi A+B tersembunyi (all-or-nothing)", invAB["id"] not in ids)
    check("divisi: detail invoice B -> 403", mg("GET", f"vendor-invoices/{invB['id']}")[0] == 403)
    check("divisi: cetak invoice B -> 403", mg("GET", f"vendor-invoices/{invB['id']}/print")[0] == 403)
    check("divisi: histori DO B -> 403", mg("GET", f"vendor-invoices/do/{dB1['id']}")[0] == 403)
    check("divisi: Status Penagihan DO tanpa DO Divisi B", dB1["id"] not in {x["do_id"] for x in mg("GET", "vendor-invoices/do-billing")[1]})
    sm = mg("GET", "vendor-invoices/summary")[1]
    check("divisi: dashboard ringkas hanya hitung invoice dalam cakupan", sm.get("invoice_received") == len(ids), (sm, len(ids)))
    sc, fb = up(T.S, "invoice", invB["id"], "rahasia-b.pdf")
    check("divisi: unduh lampiran invoice Divisi B -> 403", sc == 200 and mg("GET", f"attachments/{fb['id']}/download")[0] == 403)
    check("divisi: daftar lampiran invoice Divisi B -> 403", mg("GET", f"attachments?entity=invoice&entity_id={invB['id']}")[0] == 403)
    check("divisi: audit invoice B tersembunyi", not [x for x in mg("GET", f"audit?entity=invoice&entity_id={invB['id']}")[1] or []])
    cr = mk_user("purchasing", divs=[divA["id"]])
    elig = {x["do_id"] for x in cr("GET", f"vendor-invoices/eligible-dos?supplier_id={M['supX']['id']}")[1]}
    check("divisi: pemilihan DO hanya DO dalam cakupan", dB1["id"] not in elig and d7["id"] in elig, elig)
    sc, r = cr("POST", "vendor-invoices", inv_body("INV-FORCE", "supX", [(dB1, 1)]))
    check("divisi: DO Divisi B dipaksa lewat API -> 403", sc == 403, (sc, r))

    # tenant isolation
    other = requests.Session()
    u = uuid.uuid4().hex[:8]
    res = other.post(f"{API}/saas/register", json={"company_name": f"IV {u}", "pic_name": "QA", "email": f"iv_{u}@example.com", "whatsapp": "+628123456789",
                                                   "workspace_slug": f"iv-{u}", "plan_code": "starter", "password": PW, "address": "x", "terms_accepted": True}).json()
    if res.get("token"):
        other.headers.update({"Authorization": f"Bearer {res['token']}"})
    else:
        other.post(f"{API}/auth/login", json={"email": f"iv_{u}@example.com", "password": PW})
    check("tenant: tenant lain tidak melihat invoice", other.get(f"{API}/vendor-invoices").json() == [])
    check("tenant: detail invoice tenant lain -> 404", other.get(f"{API}/vendor-invoices/{inv1['id']}").status_code == 404)
    check("tenant: bayar invoice tenant lain -> 404", other.post(f"{API}/vendor-invoices/{inv1['id']}/payments", json={"date": "2026-06-10", "amount": 1}).status_code == 404)
    check("tenant: unduh lampiran tenant lain -> 404", other.get(f"{API}/attachments/{fid}/download").status_code == 404)
    r = other.post(f"{API}/attachments", files={"file": ("t.pdf", b"%PDF-1.4 t", "application/pdf")}, data={"entity": "invoice_payment", "entity_id": p1})
    check("tenant: unggah lampiran ke pembayaran tenant lain -> 404", r.status_code == 404, r.status_code)
    r = other.post(f"{API}/vendor-invoices", json=inv_body("INV-T", "supX", [(d7, 1)]))
    check("tenant: pakai Supplier/DO tenant lain -> ditolak", r.status_code in (400, 404), (r.status_code, r.text[:200]))
    check("tenant: summary tenant lain kosong", other.get(f"{API}/vendor-invoices/summary").json().get("invoice_received") == 0)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
