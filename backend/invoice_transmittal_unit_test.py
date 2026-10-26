"""Unit test tanpa database: aturan checklist invoice + state machine transmittal + permission.

Tidak menyentuh database production. Jalankan: python invoice_transmittal_unit_test.py
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "mysql://u:p@127.0.0.1:3306/unit_test")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-0123456789abcdef")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import access_control_layer as ACL  # noqa: E402
import server as _app_server  # noqa: E402,F401  (memuat production_bootstrap + seluruh layer sekali, tanpa koneksi DB)
import invoice_transmittal_layer as TRN  # noqa: E402
import vendor_invoice_layer as VIL  # noqa: E402

PASS = 0
FAIL = 0


def check(ok, msg, info=None):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"PASS: {msg}")
    else:
        FAIL += 1
        print(f"FAIL: {msg} {info if info is not None else ''}")


# ---------------------------------------------------------------- checklist invoice (Tahap 1)
check(VIL.CHECK_KEYS == ("invoice", "faktur_pajak", "po", "do", "bukti_penerimaan", "kwitansi", "bast", "kontrak"),
      "8 jenis dokumen checklist sesuai permintaan")
check(VIL.CHECK_VALUES == ("Lengkap", "Belum Lengkap", "Tidak Berlaku"), "3 nilai status checklist")

norm = VIL.norm_checklist({"invoice": "Lengkap", "kwitansi": "Ngawur", "kontrak": "Tidak Berlaku"})
check(norm["invoice"] == "Lengkap" and norm["kontrak"] == "Tidak Berlaku", "Nilai valid dipertahankan")
check(norm["kwitansi"] == "Belum Lengkap" and norm["po"] == "Belum Lengkap", "Nilai kosong/tidak dikenal -> Belum Lengkap")
check(len(norm) == 8, "Checklist selalu berisi 8 kunci (aman untuk data lama)")

doc = VIL.doc_fields({"tax_invoice_no": " 010.000-26.00000001 ", "tax_invoice_date": "2026-10-23"}, {})
check(doc["tax_invoice_no"] == "010.000-26.00000001", "Nomor Faktur Pajak di-trim & disimpan")
check(doc["tax_invoice_date"] == "2026-10-23", "Tanggal Faktur Pajak diterima format ISO")
try:
    VIL.doc_fields({"tax_invoice_date": "23-10-2026"}, {})
    check(False, "Tanggal Faktur Pajak invalid harus ditolak")
except Exception as exc:  # HTTPException
    check(getattr(exc, "status_code", None) == 400, "Tanggal Faktur Pajak invalid ditolak 400")

keep_from_empty = VIL.doc_fields({}, {"tax_invoice_no": "LAMA", "doc_checklist": {"bast": "Lengkap"}})
check(keep_from_empty["tax_invoice_no"] == "LAMA" and keep_from_empty["doc_checklist"]["bast"] == "Lengkap",
      "Body tanpa field dokumen tidak menghapus nilai lama")

# ---------------------------------------------------------------- state machine transmittal (Tahap 2)
check(TRN.STATUSES == ("Draft", "Dikirim", "Diterima", "Dikembalikan"), "4 status transmittal sesuai permintaan")
check(TRN.ACTIVE == {"Draft", "Dikirim"}, "Transmittal aktif = Draft & Dikirim (guard duplikat)")
check(TRN.TRANSITIONS["Draft"] == {"Dikirim"}, "Draft hanya bisa -> Dikirim")
check(TRN.TRANSITIONS["Dikirim"] == {"Diterima", "Dikembalikan"}, "Dikirim -> Diterima / Dikembalikan")
check(TRN.TRANSITIONS["Dikembalikan"] == set(), "Dikembalikan bersifat final (kirim ulang = transmittal baru)")
check(TRN.req_date("2026-10-23", "Tanggal") == "2026-10-23", "Tanggal transmittal valid diterima")
try:
    TRN.req_date("", "Tanggal Pengiriman")
    check(False, "Tanggal kosong harus ditolak")
except Exception as exc:
    check(getattr(exc, "status_code", None) == 400, "Tanggal pengiriman kosong ditolak 400")
check(TRN.checklist_of({})["invoice"] == "Belum Lengkap", "Invoice tanpa checklist -> semua Belum Lengkap")

# ---------------------------------------------------------------- permission (backend)
for key in ("transmittal.view", "transmittal.create", "transmittal.edit", "transmittal.delete", "transmittal.print", "transmittal.receive"):
    check(key in ACL.ALL_KEYS, f"Permission {key} terdaftar di ALL_KEYS")
check("transmittal" in ACL.MODULES and ACL.MODULES["transmittal"][0] == "Transmittal Invoice", "Modul Transmittal muncul di Hak Akses")
check({"transmittal.view", "transmittal.create", "transmittal.edit", "transmittal.print", "transmittal.receive"} <= set(ACL.FINANCE_DEFAULT),
      "Default role Finance mendapat izin transmittal (tanpa delete)")
purch = ACL.legacy_to_granular(["view", "create", "edit", "print"], "purchasing")
check({"transmittal.view", "transmittal.create", "transmittal.edit", "transmittal.print"} <= purch, "Role Purchasing mewarisi izin transmittal")
mgr = ACL.legacy_to_granular(["view"], "manager")
check("transmittal.view" in mgr and "transmittal.create" not in mgr, "Manager hanya transmittal.view (read-only)")

# ---------------------------------------------------------------- route registration (tanpa DB)
from fastapi import FastAPI  # noqa: E402


class _FakeServer:
    def __init__(self):
        self.app = FastAPI()
        self.db = None

    async def current_user(self):  # pragma: no cover - hanya dipakai sebagai dependency
        return {}

    def require(self, *a, **k):
        return None

    async def audit(self, *a, **k):
        return None

    def now_iso(self):
        return "2026-10-23T00:00:00+00:00"

    def gid(self):
        return "x"

    async def next_number(self, doc_type):
        return f"{doc_type}/2026/10/00001"

    def is_global(self, user):
        return True

    async def ACCESS_DOC_VISIBLE(self, *a, **k):
        return True


# ---------------------------------------------------------------- export daftar (Excel) Transmittal
import asyncio  # noqa: E402

import reporting.reports_txn as RTX  # noqa: E402,F401  (mendaftarkan ReportSpec export daftar transaksi)
from reporting.registry import REGISTRY  # noqa: E402

_spec = REGISTRY.get("txn-transmittal")
check(_spec is not None, "Laporan export txn-transmittal terdaftar")
check(_spec is not None and _spec.permission == "transmittal.view", "Export transmittal memakai izin transmittal.view")
check(_spec is not None and _spec.catalog is False, "Laporan export tidak tampil di katalog Pusat Laporan")
check(_spec is not None and "ids" in {f.key for f in _spec.filters}, "Filter ids (export baris terpilih) tersedia")
check(_spec is not None and {c.key for c in _spec.columns} == {"no", "date", "destination", "sender_name", "receiver_name",
                                                              "suppliers", "invoice_count", "total_amount", "status"},
      "Kolom export sama dengan daftar transmittal")


class _TxnServer:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def TXN_LIST_ROWS(self, module, user, p):
        self.calls.append((module, p.get("ids")))
        return [dict(r) for r in self.rows]


_tsrv = _TxnServer([{"id": "t1", "no": "TRN/1"}, {"id": "t2", "no": "TRN/2"}])
_all = asyncio.run(_spec.builder(_tsrv, {"email": "x"}, {"ids": ""}))
check([r["id"] for r in _all] == ["t1", "t2"], "Tanpa ids -> seluruh baris transmittal")
_pick = asyncio.run(_spec.builder(_tsrv, {"email": "x"}, {"ids": "t2"}))
check([r["id"] for r in _pick] == ["t2"], "ids -> hanya baris terpilih (export 1 transaksi)")
check(_tsrv.calls[0][0] == "transmittal", "Export memakai jalur daftar transmittal (cakupan & izin sama)")

srv = _FakeServer()
TRN.install(srv)
routes = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", []) or []))) for r in srv.app.routes}
expected = [
    ("/api/invoice-transmittals", ("GET",)),
    ("/api/invoice-transmittals", ("POST",)),
    ("/api/invoice-transmittals/eligible-invoices", ("GET",)),
    ("/api/invoice-transmittals/by-invoice/{iid}", ("GET",)),
    ("/api/invoice-transmittals/{tid}", ("GET",)),
    ("/api/invoice-transmittals/{tid}", ("PUT",)),
    ("/api/invoice-transmittals/{tid}", ("DELETE",)),
    ("/api/invoice-transmittals/{tid}/send", ("POST",)),
    ("/api/invoice-transmittals/{tid}/receive", ("POST",)),
    ("/api/invoice-transmittals/{tid}/return", ("POST",)),
    ("/api/invoice-transmittals/{tid}/print", ("GET",)),
]
for path, methods in expected:
    check((path, methods) in routes, f"Route terdaftar: {methods[0]} {path}")

print(f"\n{PASS}/{PASS + FAIL} passed")
sys.exit(1 if FAIL else 0)
