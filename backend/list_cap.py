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
ALL = 10_000_000  # P7: daftar ber-halaman (?page=) memuat SELURUH dokumen (tanpa batas muat 1.000) — total = total export
_CAP: contextvars.ContextVar = contextvars.ContextVar("txn_list_cap", default=None)
_ONLY: contextvars.ContextVar = contextvars.ContextVar("txn_list_only_ids", default=None)


def cap() -> int:
    return _CAP.get() or DEFAULT_CAP


@contextmanager
def raised(n: int):
    tok = _CAP.set(max(int(n), DEFAULT_CAP))
    try:
        yield
    finally:
        _CAP.reset(tok)


_SCOPE: contextvars.ContextVar = contextvars.ContextVar("txn_list_scope_prefilter", default=None)


def base_filter(module: str) -> dict:
    """Filter dokumen endpoint daftar paling dalam: {} (semua, perilaku lama) atau {"id": {"$in": ids}} saat jalur cepat
    daftar ber-halaman P7 meminta baris halaman aktif saja, dan/atau pra-saring cakupan P7 (`scoped`) untuk user terbatas
    divisi (modul yang sama; query lain tidak terpengaruh)."""
    parts = []
    cur = _ONLY.get()
    if cur is not None and cur[0] == module:
        parts.append({"id": {"$in": list(cur[1])}})
    sc = _SCOPE.get()
    if sc is not None and sc[0] == module:
        parts.append(sc[1])
    if not parts:
        return {}
    return parts[0] if len(parts) == 1 else {"$and": parts}


@contextmanager
def scoped(module: str, flt: dict):
    tok = _SCOPE.set((module, flt))
    try:
        yield
    finally:
        _SCOPE.reset(tok)


@contextmanager
def only(module: str, ids):
    tok = _ONLY.set((module, list(ids)))
    try:
        yield
    finally:
        _ONLY.reset(tok)
