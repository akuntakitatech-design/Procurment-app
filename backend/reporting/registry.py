"""Registry Pusat Laporan: definisi laporan (kolom, filter, builder) = SATU sumber untuk UI JSON, Excel, dan PDF.

Setiap laporan didaftarkan sebagai ReportSpec. Builder mengembalikan SELURUH baris (sudah ber-scope tenant/divisi/gudang
server-side) sesuai filter; pagination/total/export dikerjakan oleh `reporting.report_center` atas hasil yang sama.
Kolom ber-`price=True` dibuang server-side (JSON maupun file) untuk pengguna tanpa izin `view_purchase_price`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

GROUPS = [
    {"key": "persediaan", "title": "Persediaan & Nilai Persediaan"},
    {"key": "procurement", "title": "Procurement (MRO, RO, PO, DO, MI)"},
    {"key": "warehouse", "title": "Warehouse (Transfer, Loan/Return, Adjustment, Opname)"},
    {"key": "spk", "title": "SPK & Kontrak Harga Vendor"},
    {"key": "hutang", "title": "Invoice, Pembayaran & Outstanding Hutang"},
]
GROUP_KEYS = {g["key"] for g in GROUPS}

# Tipe kolom: text | date | qty | money | int
NUMERIC = {"qty", "money", "int"}
# Tipe filter master (opsi dari lookup ber-scope existing di frontend; nilai divalidasi server-side oleh builder)
MASTER_FILTERS = {"division", "warehouse", "category", "item", "project", "unit", "supplier"}


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    type: str = "text"
    price: bool = False      # kolom harga/nilai -> hanya untuk view_purchase_price
    total: bool = False      # dijumlahkan pada baris TOTAL (seluruh baris sesuai filter)
    width: int = 14          # lebar relatif (Excel: karakter; PDF: proporsional)
    perms: tuple = ()        # izin TAMBAHAN yang wajib dimiliki (semua) agar kolom terlihat (P4: vendor_contract:view)

    def public(self):
        return {"key": self.key, "label": self.label, "type": self.type, "price": self.price, "total": self.total,
                "width": self.width}


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    type: str = "text"      # date | division | warehouse | category | item | project | unit | supplier | select | text
    options: tuple = ()      # untuk select: ((value, label), ...)
    required: bool = False   # wajib diisi sebelum laporan ditampilkan / di-export
    default: str = ""        # nilai bawaan select (dipakai bila kosong)

    def public(self):
        return {"key": self.key, "label": self.label, "type": self.type, "required": self.required,
                "default": self.default, "options": [{"value": v, "label": lb} for v, lb in self.options]}


Builder = Callable[..., Awaitable[list]]


@dataclass(frozen=True)
class ReportSpec:
    key: str
    group: str
    title: str
    description: str
    columns: tuple
    builder: Builder                      # async (server, user, params: dict) -> list[dict] (SELURUH baris)
    filters: tuple = ()
    search_keys: tuple = ()
    permission: str = "view"
    date_basis: str = ""                  # keterangan semantik tanggal (ditampilkan di UI/Excel/PDF)
    drill: Optional[Callable] = None      # row -> {"label", "to"} (tautan dokumen sumber)
    legacy: tuple = field(default=())     # endpoint lama yang tetap dipertahankan (kompatibilitas)

    def visible_columns(self, price_visible: bool, has_perm: Optional[Callable] = None):
        """Kolom harga dibuang tanpa view_purchase_price; kolom ber-`perms` dibuang bila salah satu izin tidak dimiliki."""
        return [c for c in self.columns if (price_visible or not c.price)
                and (not c.perms or (has_perm is not None and all(has_perm(p) for p in c.perms)))]


REGISTRY: dict = {}


def register(spec: ReportSpec) -> ReportSpec:
    if spec.group not in GROUP_KEYS:
        raise ValueError(f"group tidak dikenal: {spec.group}")
    if spec.key in REGISTRY:
        raise ValueError(f"laporan ganda: {spec.key}")
    keys = [c.key for c in spec.columns]
    if len(keys) != len(set(keys)):
        raise ValueError(f"kolom ganda pada {spec.key}")
    REGISTRY[spec.key] = spec
    return spec
