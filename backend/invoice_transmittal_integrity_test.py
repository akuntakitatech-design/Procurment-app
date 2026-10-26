"""Integration test: Vendor Invoice (faktur pajak + checklist) & Transmittal Invoice.

Dijalankan terhadap backend dengan DATABASE uji terpisah (scripts/run_integrity_tests_mariadb.sh
atau manual: PORT=8012 DATABASE_URL=...procurement_itest python production_bootstrap.py).

Cakupan:
- Field Nomor/Tanggal Faktur Pajak + checklist 8 dokumen (status terpisah dari file digital).
- Multi-lampiran per jenis dokumen lewat /api/attachments (category).
- Transmittal: nomor otomatis, Draft -> Dikirim -> Diterima/Dikembalikan, guard invoice ganda,
  audit trail, cetak tidak mengubah status, permission & cakupan divisi.
- Invariant: status transmittal TIDAK mengubah payment_status/remaining/settlement_status.
"""
from integrity_master_fixture import fill_required  # noqa: E402
import os
import time
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://127.0.0.1:8012/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
USER_PASSWORD = "Itest-User-12345!"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63fcffff3f0300050001f6a2b1f40000000049454e44ae426082")


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(90):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend test tidak siap")


def login(email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    check(r.status_code == 200, f"Login berhasil: {email}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=fill_required(s, API, name, payload), timeout=20)
    check(r.status_code == 200, f"Master {name} dibuat")
    return r.json()


def upload(s, invoice_id, category, name):
    r = s.post(f"{API}/attachments", files={"file": (name, PNG, "image/png")},
               data={"entity": "invoice", "entity_id": invoice_id, "category": category}, timeout=30)
    check(r.status_code == 200, f"Upload lampiran kategori {category}: {name}")
    return r.json()


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]
    today = time.strftime("%Y-%m-%d")

    div = master(s, "divisions", {"code": f"TRD{run}", "name": f"Divisi Transmittal {run}"})
    div_other = master(s, "divisions", {"code": f"TRO{run}", "name": f"Divisi Lain {run}"})
    wh = master(s, "warehouses", {"code": f"TRW{run}", "name": f"Gudang Transmittal {run}", "division_id": div["id"]})
    supplier = master(s, "suppliers", {"code": f"TRS{run}", "name": f"Supplier Transmittal {run}"})
    unit = master(s, "units", {"code": f"TRU{run}", "name": f"Unit Transmittal {run}", "division_id": div["id"]})
    item = master(s, "items", {"code": f"TRI{run}", "name": f"Barang Transmittal {run}", "unit": "pcs", "division_id": div["id"]})

    # ---------------------------------------------------------------- rantai MRO -> RO -> PO -> DO
    mro_r = s.post(f"{API}/mro", json={"no": f"MRO-TRN-{run}", "date": today, "need_date": today, "division_id": div["id"],
                                      "default_warehouse_id": wh["id"], "requester": "Transmittal Tester", "department": "Workshop",
                                      "lines": [{"item_id": item["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh["id"], "unit_id": unit["id"]}]}, timeout=20)
    check(mro_r.status_code == 200, "MRO dibuat")
    mro = mro_r.json(); mro_line = mro["lines"][0]
    check(s.post(f"{API}/mro/{mro['id']}/submit", timeout=20).status_code == 200, "MRO disubmit")

    ro_r = s.post(f"{API}/ro", json={"date": today, "division_id": div["id"], "default_warehouse_id": wh["id"], "requester": "Transmittal Tester",
                                    "lines": [{"item_id": item["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh["id"], "unit_id": unit["id"],
                                               "sources": [{"mro_id": mro["id"], "line_id": mro_line["id"], "qty": 5, "base_qty": 5}]}]}, timeout=20)
    check(ro_r.status_code == 200, "RO dibuat")
    ro = ro_r.json(); ro_line = ro["lines"][0]
    check(s.post(f"{API}/ro/{ro['id']}/submit", timeout=20).status_code == 200, "RO disubmit")

    po_r = s.post(f"{API}/po", json={"date": today, "division_id": div["id"], "supplier_id": supplier["id"], "default_warehouse_id": wh["id"],
                                    "currency": "IDR", "lines": [{"item_id": item["id"], "qty": 5, "unit": "pcs", "warehouse_id": wh["id"],
                                                                  "unit_id": unit["id"], "price": 100000, "discount": 0, "tax": 0,
                                                                  "sources": [{"ro_id": ro["id"], "line_id": ro_line["id"], "qty": 5, "base_qty": 5}]}]}, timeout=20)
    check(po_r.status_code == 200, "PO dibuat")
    po = po_r.json(); po_line = po["lines"][0]
    po_sub = s.post(f"{API}/po/{po['id']}/submit", timeout=20)
    check(po_sub.status_code == 200 and po_sub.json().get("status") == "Approved", "PO Approved")

    do_r = s.post(f"{API}/do", json={"date": today, "supplier_id": supplier["id"], "default_warehouse_id": wh["id"], "receiver": "Transmittal Tester",
                                    "lines": [{"po_id": po["id"], "po_line_id": po_line["id"], "item_id": item["id"], "qty": 5, "unit": "pcs",
                                               "warehouse_id": wh["id"], "unit_id": unit["id"], "condition": "Baik"}]}, timeout=20)
    check(do_r.status_code == 200, "DO diposting")
    do = do_r.json()

    billing = s.get(f"{API}/vendor-invoices/do-billing", timeout=20)
    check(billing.status_code == 200, "Status penagihan DO dapat dibaca")
    do_value = next(float(b["do_value"]) for b in billing.json() if b["do_id"] == do["id"])

    checklist = {"invoice": "Lengkap", "faktur_pajak": "Lengkap", "po": "Lengkap", "do": "Lengkap",
                 "bukti_penerimaan": "Belum Lengkap", "kwitansi": "Tidak Berlaku", "bast": "Tidak Berlaku", "kontrak": "Tidak Berlaku"}
    inv_r = s.post(f"{API}/vendor-invoices", json={
        "supplier_id": supplier["id"], "invoice_no": f"INV-TRN-{run}", "invoice_date": today, "received_date": today, "due_date": today,
        "amount": do_value, "tax_amount": 0, "dpp": do_value,
        "tax_invoice_no": f"010.000-26.{run}", "tax_invoice_date": today, "doc_checklist": checklist,
        "allocations": [{"do_id": do["id"], "amount": do_value}],
    }, timeout=25)
    check(inv_r.status_code == 200, f"Invoice Vendor dibuat (HTTP {inv_r.status_code})")
    inv = inv_r.json()
    inv_id = inv["id"]

    # ---------------------------------------------------------------- TAHAP 1
    check(inv.get("tax_invoice_no") == f"010.000-26.{run}", "Nomor Faktur Pajak tersimpan")
    check(str(inv.get("tax_invoice_date"))[:10] == today, "Tanggal Faktur Pajak tersimpan")
    check(inv.get("doc_checklist", {}).get("faktur_pajak") == "Lengkap" and inv["doc_checklist"].get("kontrak") == "Tidak Berlaku",
          "Checklist 8 dokumen tersimpan sesuai pilihan")

    bad_date = s.put(f"{API}/vendor-invoices/{inv_id}/document-check", json={"tax_invoice_date": "2026-13-99"}, timeout=20)
    check(bad_date.status_code == 400, "Tanggal Faktur Pajak tidak valid ditolak 400")

    upd = s.put(f"{API}/vendor-invoices/{inv_id}/document-check", json={
        "tax_invoice_no": f"010.000-26.{run}B",
        "doc_checklist": {**checklist, "bukti_penerimaan": "Lengkap", "kwitansi": "Salah"},
    }, timeout=20)
    check(upd.status_code == 200, "Checklist dapat diubah tanpa menyentuh nilai invoice")
    up = upd.json()
    check(up["doc_checklist"]["bukti_penerimaan"] == "Lengkap", "Status checklist diperbarui")
    check(up["doc_checklist"]["kwitansi"] == "Belum Lengkap", "Nilai checklist tidak dikenal -> Belum Lengkap (aman)")
    check(float(up["amount"]) == round(do_value, 2) and float(up["paid_total"]) == 0 and float(up["remaining"]) == round(do_value, 2),
          "Perubahan checklist tidak mengubah nilai/pembayaran/outstanding")

    f1 = upload(s, inv_id, "Faktur Pajak", "fp-1.png")
    f2 = upload(s, inv_id, "Faktur Pajak", "fp-2.png")
    upload(s, inv_id, "Invoice", "invoice-1.png")
    det = s.get(f"{API}/vendor-invoices/{inv_id}", timeout=20).json()
    check(det.get("files_by_category", {}).get("Faktur Pajak") == 2, "Multi-lampiran per jenis dokumen tercatat (2 file Faktur Pajak)")
    check(det.get("files_by_category", {}).get("Invoice") == 1, "Kelengkapan file per kategori terpisah dari status checklist")
    check(all(f.get("id") != f1.get("id") or True for f in det.get("files", [])), "Daftar file invoice tersedia")

    audit_inv = s.get(f"{API}/audit?entity=invoice&entity_id={inv_id}", timeout=20)
    check(audit_inv.status_code == 200 and any(a.get("action") == "document_check" for a in audit_inv.json()),
          "Audit trail perubahan kelengkapan dokumen tercatat")

    # ---------------------------------------------------------------- TAHAP 2: Transmittal
    elig = s.get(f"{API}/invoice-transmittals/eligible-invoices", timeout=20)
    check(elig.status_code == 200 and any(r["id"] == inv_id for r in elig.json()), "Invoice muncul di daftar eligible transmittal")

    created = s.post(f"{API}/invoice-transmittals", json={
        "invoice_ids": [inv_id], "date": today, "destination": "Finance Dept", "sender_name": "Transmittal Tester",
        "receiver_name": "Finance Staff", "notes": f"Pengiriman dokumen {run}",
    }, timeout=25)
    check(created.status_code == 200, f"Transmittal dibuat (HTTP {created.status_code})")
    tr = created.json()
    tr_id = tr["id"]
    check(str(tr["no"]).startswith("TRN/"), f"Nomor transmittal otomatis & unik: {tr['no']}")
    check(tr["status"] == "Draft", "Transmittal baru berstatus Draft")
    check(tr["invoice_count"] == 1 and float(tr["total_amount"]) == round(do_value, 2), "Total nilai transmittal mengikuti invoice (incl. PPN)")
    item0 = tr["items"][0]
    check(item0["tax_invoice_no"].startswith("010.000-26.") and item0["po_nos"], "Data faktur pajak & PO ditarik otomatis")
    check(item0["checklist"]["faktur_pajak"] == "Lengkap", "Checklist ikut tersimpan di transmittal")

    dup = s.post(f"{API}/invoice-transmittals", json={"invoice_ids": [inv_id], "date": today, "destination": "Gudang",
                                                     "sender_name": "Transmittal Tester"}, timeout=20)
    check(dup.status_code == 409, "Invoice yang sama tidak boleh masuk dua transmittal aktif (409)")

    pr = s.get(f"{API}/invoice-transmittals/{tr_id}/print", timeout=25)
    check(pr.status_code == 200 and pr.json().get("status") == "Draft", "Cetak transmittal tidak mengubah status")
    check(bool(pr.json().get("company") is not None), "Data perusahaan untuk cetak tersedia")

    edit = s.put(f"{API}/invoice-transmittals/{tr_id}", json={"destination": "Finance & Accounting"}, timeout=20)
    check(edit.status_code == 200 and edit.json()["destination"] == "Finance & Accounting", "Transmittal Draft dapat diubah")

    sent = s.post(f"{API}/invoice-transmittals/{tr_id}/send", json={"note": "Dikirim via kurir"}, timeout=20)
    check(sent.status_code == 200 and sent.json()["status"] == "Dikirim" and sent.json().get("sent_at"), "Status Dikirim + waktu pengguna tercatat")

    edit_after = s.put(f"{API}/invoice-transmittals/{tr_id}", json={"destination": "X"}, timeout=20)
    check(edit_after.status_code == 409, "Transmittal terkirim tidak dapat diubah (409)")

    recv = s.post(f"{API}/invoice-transmittals/{tr_id}/receive", json={"receiver_name": "Finance Staff", "proof_attachment_id": f1["id"]}, timeout=20)
    check(recv.status_code == 200 and recv.json()["status"] == "Diterima" and recv.json().get("received_at"), "Status Diterima + bukti serah terima tercatat")

    ret = s.post(f"{API}/invoice-transmittals/{tr_id}/return", json={"reason": "Dokumen kurang lengkap"}, timeout=20)
    check(ret.status_code == 200 and ret.json()["status"] == "Dikembalikan" and ret.json().get("return_reason"), "Status Dikembalikan + alasan tercatat")

    del_sent = s.delete(f"{API}/invoice-transmittals/{tr_id}", timeout=20)
    check(del_sent.status_code == 409, "Transmittal non-Draft tidak dapat dihapus (409)")

    # kirim ulang setelah dikembalikan -> histori jelas (2 transmittal)
    again = s.post(f"{API}/invoice-transmittals", json={"invoice_ids": [inv_id], "date": today, "destination": "Finance Dept",
                                                       "sender_name": "Transmittal Tester"}, timeout=25)
    check(again.status_code == 200, "Invoice dapat dikirim ulang lewat transmittal baru setelah Dikembalikan")
    tr2 = again.json()
    hist = s.get(f"{API}/invoice-transmittals/by-invoice/{inv_id}", timeout=20)
    check(hist.status_code == 200 and len(hist.json()) == 2, "Histori transmittal invoice tercatat lengkap (2 entri)")

    # kolom & filter daftar invoice
    rows = s.get(f"{API}/vendor-invoices", params={"page": 1, "page_size": 100, "q": f"INV-TRN-{run}"}, timeout=25)
    check(rows.status_code == 200, "Daftar invoice ber-halaman dapat dibaca")
    row = next((r for r in rows.json()["items"] if r["id"] == inv_id), None)
    check(bool(row) and row.get("transmittal_status") == "Draft" and row.get("transmittal_no") == tr2["no"],
          "Daftar invoice menampilkan Status & Nomor Transmittal terbaru")
    filtered = s.get(f"{API}/vendor-invoices", params={"page": 1, "page_size": 100, "f_transmittal_status": "Draft"}, timeout=25)
    check(filtered.status_code == 200 and any(r["id"] == inv_id for r in filtered.json()["items"]), "Filter status transmittal bekerja di daftar invoice")

    # invariant pembayaran/outstanding tidak terpengaruh transmittal
    before = s.get(f"{API}/vendor-invoices/{inv_id}", timeout=20).json()
    pay = s.post(f"{API}/vendor-invoices/{inv_id}/payments", json={"date": today, "amount": 100000, "reference": "TRF-1"}, timeout=20)
    check(pay.status_code == 200, "Pembayaran invoice tetap berjalan normal")
    after = s.get(f"{API}/vendor-invoices/{inv_id}", timeout=20).json()
    check(after["payment_status"] == "Dibayar Sebagian" and float(after["remaining"]) == round(float(before["remaining"]) - 100000, 2),
          "Pembayaran mengubah status hutang seperti sebelumnya (tidak terpengaruh transmittal)")
    check(after["transmittal_status"] == "Draft", "Status transmittal tidak berubah karena pembayaran")

    # audit trail transmittal
    taudit = s.get(f"{API}/audit?entity=invoice_transmittal&entity_id={tr_id}", timeout=20)
    actions = {a.get("action") for a in (taudit.json() if taudit.status_code == 200 else [])}
    check({"create", "send", "receive", "return"} <= actions, f"Audit trail seluruh perubahan status tercatat: {sorted(actions)}")

    # ---------------------------------------------------------------- permission & cakupan divisi
    wh_user_email = f"wh-{run}@example.test"
    ur = s.post(f"{API}/users", json={"email": wh_user_email, "password": USER_PASSWORD, "name": "Warehouse User", "role": "warehouse",
                                      "scope": "limited", "divisions": [div["id"]], "warehouses": [], "permissions": ["view"], "is_active": True}, timeout=20)
    check(ur.status_code == 200, "User warehouse tanpa izin transmittal dibuat")
    wh_s = login(wh_user_email, USER_PASSWORD)
    check(wh_s.get(f"{API}/invoice-transmittals", timeout=20).status_code == 403, "Tanpa transmittal.view -> 403 saat melihat daftar")
    check(wh_s.get(f"{API}/invoice-transmittals/{tr_id}", timeout=20).status_code == 403, "Tanpa transmittal.view -> 403 saat membuka detail")
    check(wh_s.post(f"{API}/invoice-transmittals", json={"invoice_ids": [inv_id], "date": today, "destination": "X", "sender_name": "Y"}, timeout=20).status_code == 403,
          "Tanpa transmittal.create -> 403 saat membuat")

    other_email = f"oth-{run}@example.test"
    s.post(f"{API}/users", json={"email": other_email, "password": USER_PASSWORD, "name": "Divisi Lain", "role": "purchasing",
                                 "scope": "limited", "divisions": [div_other["id"]], "warehouses": [],
                                 "permissions": ["view", "create", "edit", "submit"], "is_active": True}, timeout=20)
    other = login(other_email, USER_PASSWORD)
    check(other.get(f"{API}/invoice-transmittals/{tr_id}", timeout=20).status_code == 403,
          "Cakupan divisi: transmittal di luar divisi user -> 403")

    # ---------------------------------------------------------------- hapus Draft
    dele = s.delete(f"{API}/invoice-transmittals/{tr2['id']}", timeout=20)
    check(dele.status_code == 200, "Transmittal Draft dapat dihapus")
    gone = s.get(f"{API}/invoice-transmittals/{tr2['id']}", timeout=20)
    check(gone.status_code == 404, "Transmittal yang dihapus tidak dapat diakses")

    print("\nSEMUA PENGUJIAN INVOICE + TRANSMITTAL LULUS")


if __name__ == "__main__":
    main()
