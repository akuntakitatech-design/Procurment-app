"""Kelompok status daftar transaksi (tab) — SATU definisi untuk filter & hitungan.

Dipakai `txn_list_paging_layer` (param `status_group` + `counts=status_group`) dan diekspos ke frontend
lewat GET /api/txn-status-groups agar label/urutan tab tidak diduplikasi di dua tempat.

Grup `overflow=True` ditampilkan di menu "Lainnya" pada UI (status yang jarang dipakai).
Grup yang tidak relevan untuk suatu modul tidak didaftarkan (mis. DO/MI tidak punya alur persetujuan).
"""
from __future__ import annotations

from fastapi import Depends


def _low(v) -> str:
    return str(v or "").strip().lower()


def _eq(field, *values):
    vals = {str(v).strip().lower() for v in values}
    return lambda r: _low(r.get(field)) in vals


def _po_doc(r):
    return _low(r.get("document_status") or r.get("status"))


def _po_receipt(r):
    return _low(r.get("receipt_status"))


ALL = ("all", "Semua", False, lambda r: True)

_RO_MRO = (("draft", "Draft", False, _eq("status", "Draft")),
           ("open", "Terbuka", True, _eq("status", "Open")),
           ("cancelled", "Dibatalkan", True, _eq("status", "Cancelled")))

GROUPS = {
    # MRO: status = Draft | Open | Partial (sebagian keluar MI) | Completed | Cancelled
    "mro": (ALL,
            _RO_MRO[0],
            ("partial", "Dikirim Sebagian", False, _eq("status", "Partial")),
            ("done", "Selesai", False, _eq("status", "Completed")),
            _RO_MRO[1], _RO_MRO[2]),
    # RO: status = Draft | Open | Partial Ordered | Fully Ordered | Cancelled
    "ro": (ALL,
           _RO_MRO[0],
           ("partial", "Dikirim Sebagian", False, _eq("status", "Partial Ordered")),
           ("done", "Selesai", False, _eq("status", "Fully Ordered")),
           _RO_MRO[1], _RO_MRO[2]),
    # PO: document_status (posisi approval/penerimaan) + receipt_status
    "po": (ALL,
           ("draft", "Draft", False, _eq("document_status", "Draft")),
           ("waiting", "Menunggu Persetujuan", False,
            lambda r: _po_doc(r) in ("waiting approval", "waiting approval 1", "ready approval 2", "waiting approval 2")),
           # Hasil "Minta Revisi": PO dikembalikan ke purchasing (bukan lagi menunggu approver).
           ("revision", "Perlu Revisi", False, _eq("document_status", "Revision")),
           ("approved", "Disetujui", False, _eq("document_status", "Approved")),
           ("rejected", "Ditolak", False, _eq("document_status", "Rejected")),
           ("partial", "Diterima Sebagian", False, lambda r: _po_receipt(r) == "diterima sebagian"),
           ("done", "Selesai", False, lambda r: _po_doc(r) == "closed"),
           ("cancelled", "Dibatalkan", True, _eq("document_status", "Cancelled"))),
    # DO & MI: status = Draft | Posted | Cancelled
    "do": (ALL, _RO_MRO[0], ("done", "Selesai", False, _eq("status", "Posted")), _RO_MRO[2]),
    "mi": (ALL, _RO_MRO[0], ("done", "Selesai", False, _eq("status", "Posted")), _RO_MRO[2]),
    # Invoice supplier: payment_status (Belum Dibayar | Dibayar Sebagian | Lunas)
    "invoice": (ALL,
                _RO_MRO[0],
                ("partial", "Dibayar Sebagian", False, _eq("payment_status", "Dibayar Sebagian")),
                ("done", "Lunas", False, _eq("payment_status", "Lunas")),
                ("unpaid", "Belum Dibayar", True, _eq("payment_status", "Belum Dibayar")),
                _RO_MRO[2]),
}


def has_groups(module: str) -> bool:
    return module in GROUPS


def group_of(module: str, row: dict) -> str:
    """Nama grup pertama yang cocok (fallback "all" bila tak ada yang cocok)."""
    for key, _label, _overflow, match in GROUPS.get(module, ()):
        if key != "all" and match(row):
            return key
    return "all"


def count_groups(module: str, rows) -> dict:
    out = {key: 0 for key, _l, _o, _m in GROUPS.get(module, ())}
    if not out:
        return out
    for r in rows or []:
        k = group_of(module, r)
        out[k] = out.get(k, 0) + 1
    out["all"] = len(rows or [])
    return out


def catalog() -> dict:
    """{module: [{key, label, overflow}]} — dikirim ke frontend sekali (cache di klien)."""
    return {m: [{"key": k, "label": lb, "overflow": ov} for k, lb, ov, _m in items] for m, items in GROUPS.items()}


def install(server):
    @server.app.get("/api/txn-status-groups", tags=["list-paging"])
    async def txn_status_groups(user=Depends(server.current_user)):
        server.require(user, "view")
        return catalog()
