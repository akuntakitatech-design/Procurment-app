"""Filter/scope resolver + predikat baris yang dipakai bersama Dashboard, Laporan dan drill-down list.

Tenant: otomatis lewat koneksi DB ber-tenant (tenant_isolation_layer).
Divisi: baris diambil lewat engine visibilitas existing (server.ACCESS_FILTER_VISIBLE) — division_id dari
frontend hanya mempersempit, dan ditolak (403) bila di luar cakupan user.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

import report_control_scope_layer as RCS

TZ = ZoneInfo("Asia/Jakarta")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> date:
    return datetime.now(TZ).date()


def month_bounds(d: date):
    first = d.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


def shift_month(d: date, n: int) -> date:
    m = d.year * 12 + (d.month - 1) + n
    return date(m // 12, m % 12 + 1, 1)


@dataclass
class Filters:
    date_from: str | None = None
    date_to: str | None = None
    division_id: str | None = None
    project_id: str | None = None
    supplier_id: str | None = None
    today: str = ""

    def dict(self):
        return asdict(self)


def _iso(v, label):
    v = (v or "").strip()[:10]
    if v and not ISO.match(v):
        raise HTTPException(400, f"Format {label} tidak valid (YYYY-MM-DD).")
    return v or None


def resolve_filters(server, user, date_from=None, date_to=None, division_id=None, project_id=None,
                    supplier_id=None, period=None) -> Filters:
    """Default periode = bulan berjalan. period=all -> tanpa batas tanggal."""
    td = today()
    if period == "all":
        df = dt = None
    elif not date_from and not date_to:
        df, dt = month_bounds(td)
    else:
        df, dt = _iso(date_from, "Tanggal Awal"), _iso(date_to, "Tanggal Akhir")
    if df and dt and df > dt:
        raise HTTPException(400, "Tanggal Awal tidak boleh melebihi Tanggal Akhir.")
    division_id = (division_id or "").strip() or None
    if division_id and not RCS._division_allowed(server, user, division_id):
        raise HTTPException(403, "Divisi yang dipilih berada di luar cakupan Anda.")
    return Filters(df, dt, division_id, (project_id or "").strip() or None, (supplier_id or "").strip() or None, td.isoformat())


def division_scope(server, user):
    """Divisi yang boleh dipilih di filter (None = semua). Sumber: resolver cakupan existing."""
    return None if RCS._global(server, user) else sorted(RCS._divisions(user))


def permissions(server, user) -> dict:
    """Izin existing (tanpa hardcode nama role). Nilai sensitif hanya dihitung/dikirim bila True."""
    eff = set(user.get("effective_permissions") or [])
    admin = user.get("role") == "admin"

    def can(k):
        return admin or k in eff
    return {"po": can("po.view"), "mro": can("mro.view"), "ro": can("ro.view"),
            "price": bool(server.has_perm(user, "view_purchase_price")),
            "invoice": can("invoice.view"), "supplier_dp": can("supplier_dp.view"),
            "approval2": can("po_approval2.view"),
            "spk": bool(server.has_perm(user, "spk:view")),
            "vendor_contract": bool(server.has_perm(user, "vendor_contract:view"))}


# ------------------------------------------------------------------ predikat baris (dipakai dashboard & list)
def day(row, key):
    return str(row.get(key) or "")[:10]


def in_range(row, key, lo, hi):
    d = day(row, key)
    return (not lo or d >= lo) and (not hi or d <= hi)


def in_period(row, key, f: Filters):
    return in_range(row, key, f.date_from, f.date_to)


def division_ids(row):
    out = set(row.get("trace_division_ids") or [])
    if row.get("division_id"):
        out.add(row["division_id"])
    return out


def project_ids(row):
    out = set(row.get("trace_project_ids") or [])
    out |= {row.get(k) for k in ("default_project_id", "project_id") if row.get(k)}
    return out


def match_dims(row, f: Filters, supplier=True):
    """Divisi/Project mengikuti lineage dokumen (PO/DO sumber); Supplier = supplier dokumen."""
    if f.division_id and f.division_id not in division_ids(row):
        return False
    if f.project_id and f.project_id not in project_ids(row):
        return False
    return not (supplier and f.supplier_id and row.get("supplier_id") != f.supplier_id)


async def visible(server, module, rows, user):
    hook = getattr(server, "ACCESS_FILTER_VISIBLE", None)
    return await hook(module, rows, user) if hook else list(rows)


# ---- Semantik waktu Dashboard ------------------------------------------------------------------
# Saldo/outstanding = POSISI s/d tanggal akhir filter (dokumen bertanggal <= tanggal akhir, termasuk bulan-bulan
# sebelumnya); aktivitas = transaksi DI DALAM periode (in_period).
def asof(f: Filters) -> str:
    """Tanggal posisi: tanggal akhir filter bila lampau, selain itu hari ini."""
    return f.date_to if f.date_to and f.date_to < f.today else f.today


def is_historical(f: Filters) -> bool:
    return asof(f) < f.today


def upto(row, key, f: Filters) -> bool:
    return in_range(row, key, None, f.date_to)


def local_day(v) -> str:
    """Timestamp ISO (UTC) -> tanggal WIB 'YYYY-MM-DD'; tanggal murni dikembalikan apa adanya; kosong -> ''."""
    s = str(v or "").strip()
    if len(s) <= 10:
        return s[:10]
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s[:10]
    if dt.tzinfo is None:
        return dt.date().isoformat()
    return dt.astimezone(TZ).date().isoformat()
