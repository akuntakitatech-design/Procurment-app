"""Batas jumlah dokumen yang dimuat endpoint daftar transaksi (GET /api/mro, /ro, /po, /do, /mi, /transfers, /loans,
/adjustments, /opname).

Default TETAP 1000 dokumen terbaru (perilaku daftar existing tidak berubah). Export daftar transaksi (P6) memanggil
logika daftar yang SAMA (scope tenant/divisi/gudang + enrichment) dengan batas dinaikkan sementara melalui
ContextVar per-request, sehingga export memuat SELURUH hasil filter (dibatasi batas export Excel/PDF, tanpa potong diam-diam).
`LIST_DEFAULT_CAP` (env) hanya untuk pengujian terisolasi.
"""
import contextvars
import os
from contextlib import contextmanager

DEFAULT_CAP = int(os.environ.get("LIST_DEFAULT_CAP") or 1000)
_CAP: contextvars.ContextVar = contextvars.ContextVar("txn_list_cap", default=None)


def cap() -> int:
    return _CAP.get() or DEFAULT_CAP


@contextmanager
def raised(n: int):
    tok = _CAP.set(max(int(n), DEFAULT_CAP))
    try:
        yield
    finally:
        _CAP.reset(tok)
