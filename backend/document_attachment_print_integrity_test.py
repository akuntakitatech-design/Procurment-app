"""Disposable integration test for transaction attachments and print settings."""
import os
import sys
import time
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://document-print-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)
    print(f"PASS: {msg}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend test tidak siap")


def login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    check(r.status_code == 200, "Login admin berhasil")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def master(s, name, payload):
    r = s.post(f"{API}/master/{name}", json=payload, timeout=15)
    check(r.status_code == 200, f"Master {name} berhasil dibuat")
    return r.json()


def main():
    wait_api()
    s = login()
    run = uuid.uuid4().hex[:8]

    div = master(s, "divisions", {"code": f"DOC{run}", "name": f"Dokumen {run}"})
    wh = master(s, "warehouses", {"code": f"DOW{run}", "name": f"Gudang Dokumen {run}", "division_id": div["id"]})
    item = master(s, "items", {"code": f"DOI{run}", "name": f"Item Dokumen {run}", "unit": "pcs", "division_id": div["id"]})

    mro = s.post(f"{API}/mro", json={
        "date": "2026-09-20", "need_date": "2026-09-21", "division_id": div["id"],
        "requester": "Document Tester", "department": "Workshop",
        "default_warehouse_id": wh["id"], "submitted": False, "notes": "DOCUMENT TEST",
        "lines": [{"item_id": item["id"], "qty": 2, "unit": "pcs", "warehouse_id": wh["id"]}],
    }, timeout=15)
    check(mro.status_code == 200, "MRO tujuan lampiran berhasil dibuat")
    mro_id = mro.json()["id"]

    # Orphan and unsupported uploads must fail before storage/database writes.
    orphan = s.post(f"{API}/attachments", data={"entity": "mro", "entity_id": "does-not-exist", "category": "Tes"},
                    files={"file": ("orphan.pdf", b"%PDF-1.4 orphan", "application/pdf")}, timeout=15)
    check(orphan.status_code == 404, "Lampiran orphan ditolak")

    unknown = s.post(f"{API}/attachments", data={"entity": "unknown", "entity_id": mro_id, "category": "Tes"},
                     files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}, timeout=15)
    check(unknown.status_code == 400, "Jenis entity lampiran tidak dikenal ditolak")

    unsupported = s.post(f"{API}/attachments", data={"entity": "mro", "entity_id": mro_id, "category": "Tes"},
                         files={"file": ("script.html", b"<script>alert(1)</script>", "text/html")}, timeout=15)
    check(unsupported.status_code == 400, "File HTML executable ditolak")

    too_big = s.post(f"{API}/attachments", data={"entity": "mro", "entity_id": mro_id, "category": "Tes"},
                     files={"file": ("besar.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")}, timeout=30)
    check(too_big.status_code == 400, "Batas ukuran MAX_UPLOAD_MB ditegakkan")

    payload = b"%PDF-1.4\nPT REAL DOCUMENT TEST\n%%EOF"
    uploaded = s.post(f"{API}/attachments",
                      data={"entity": "mro", "entity_id": mro_id, "category": "Dokumen Pendukung", "note": "Lampiran test"},
                      files={"file": ("bukti.pdf", payload, "application/pdf")}, timeout=15)
    check(uploaded.status_code == 200, "Lampiran PDF valid berhasil diupload")
    att = uploaded.json()
    aid = att["id"]
    check(att.get("entity") == "mro" and att.get("entity_id") == mro_id, "Metadata lampiran menunjuk transaksi benar")
    check(str(att.get("storage_path") or "").startswith("procureflow/tenants/tenant-document-test/"), "Storage lampiran memiliki prefix tenant")

    listed = s.get(f"{API}/attachments", params={"entity": "mro", "entity_id": mro_id}, timeout=15)
    check(listed.status_code == 200 and len(listed.json()) == 1, "Lampiran muncul pada daftar transaksi")

    anonymous = requests.get(f"{API}/attachments/{aid}/download", timeout=15)
    check(anonymous.status_code == 401, "Download lampiran tanpa autentikasi ditolak")
    downloaded = s.get(f"{API}/attachments/{aid}/download", timeout=15)
    check(downloaded.status_code == 200 and downloaded.content == payload, "Download lampiran terautentikasi mengembalikan file benar")

    deleted = s.delete(f"{API}/attachments/{aid}", timeout=15)
    check(deleted.status_code == 200, "Lampiran dapat dihapus secara soft-delete")
    listed2 = s.get(f"{API}/attachments", params={"entity": "mro", "entity_id": mro_id}, timeout=15)
    check(listed2.status_code == 200 and len(listed2.json()) == 0, "Lampiran terhapus tidak muncul lagi")
    gone = s.get(f"{API}/attachments/{aid}/download", timeout=15)
    check(gone.status_code == 404, "Lampiran terhapus tidak dapat didownload")

    # Print layout defaults and normalization for all operational modules.
    layouts = s.get(f"{API}/settings/print_layouts", timeout=15)
    check(layouts.status_code == 200, "Pengaturan layout dokumen dapat dibaca")
    modules = layouts.json().get("modules") or {}
    expected = {"mro", "ro", "po", "do", "mi", "transfer", "loan", "adjustment", "opname"}
    check(set(modules.keys()) == expected, "Layout tersedia untuk semua modul transaksi")
    check(modules["po"].get("template_style") == "real_reference", "PO default memakai template REAL reference")

    changed = s.put(f"{API}/settings/print_layouts", json={"modules": {"po": {
        "title": "PURCHASE ORDER TEST", "paper_size": "INVALID", "orientation": "diagonal",
        "font_size": 99, "margin_mm": 1, "logo_width_mm": 999,
        "sections": ["header", "items", "signatures", "footer"],
        "columns": ["item", "qty", "unit", "price", "total"],
        "signature_labels": ["Approved by,", "Signed by,"],
        "po_bill_company_name": "PT REAL TEST",
    }}}, timeout=15)
    check(changed.status_code == 200, "Layout dokumen dapat diedit")
    po_layout = changed.json()["modules"]["po"]
    check(po_layout["paper_size"] == "A4" and po_layout["orientation"] == "portrait", "Nilai paper/orientation invalid dinormalisasi")
    check(float(po_layout["font_size"]) == 16 and float(po_layout["margin_mm"]) == 5 and float(po_layout["logo_width_mm"]) == 60,
          "Batas ukuran font/margin/logo diterapkan")
    check(po_layout["po_bill_company_name"] == "PT REAL TEST", "Field desain PO tersimpan")

    # PO signature accepts image only and remains independent from layout saves.
    bad_sig = s.post(f"{API}/settings/print_layouts/po/signature",
                     files={"file": ("ttd.txt", b"not an image", "text/plain")}, timeout=15)
    check(bad_sig.status_code == 400, "Signature non-image ditolak")

    png = b"\x89PNG\r\n\x1a\n" + b"PTREAL-SIGNATURE"
    sig = s.post(f"{API}/settings/print_layouts/po/signature",
                 files={"file": ("ttd.png", png, "image/png")}, timeout=15)
    check(sig.status_code == 200, "Signature PNG berhasil diupload")
    status = s.get(f"{API}/settings/print_layouts/po/signature-status", timeout=15)
    check(status.status_code == 200 and status.json().get("available") is True, "Signature PO terdeteksi tersedia")
    sig_get = s.get(f"{API}/settings/print_layouts/po/signature", timeout=15)
    check(sig_get.status_code == 200 and sig_get.content == png, "File signature PO dapat dibaca kembali")

    # Saving layout again may not erase signature setting.
    saved_again = s.put(f"{API}/settings/print_layouts", json={"modules": {"po": {"title": "PURCHASE ORDER FINAL"}}}, timeout=15)
    check(saved_again.status_code == 200, "Layout PO dapat disimpan ulang setelah upload signature")
    status2 = s.get(f"{API}/settings/print_layouts/po/signature-status", timeout=15)
    check(status2.status_code == 200 and status2.json().get("available") is True, "Save layout tidak menghapus signature PO")

    sig_del = s.delete(f"{API}/settings/print_layouts/po/signature", timeout=15)
    check(sig_del.status_code == 200, "Signature PO dapat dihapus")
    status3 = s.get(f"{API}/settings/print_layouts/po/signature-status", timeout=15)
    check(status3.status_code == 200 and status3.json().get("available") is False, "Status signature kosong setelah delete")

    print("\nRESULT: PASS - attachment, storage auth, print layout, dan signature PO konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
