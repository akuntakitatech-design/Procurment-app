"""Pusat Laporan — konsolidasi 5 card kategori (P2a).

Setiap card = laporan aktif di REGISTRY (ber-permission) + halaman laporan existing di modul lain yang fungsinya BERBEDA
(bukan duplikat laporan Pusat Laporan; tautan tetap ke halaman aslinya, permission aslinya) + laporan yang belum
tersedia (ditandai jelas "Segera tersedia", tidak dapat diklik). Laporan lama `/reports` (MRO Traceability, Lead Time,
Pemakaian Unit) sudah digantikan penuh oleh versi Pusat Laporan -> tidak didaftarkan ganda; endpoint lama tetap.
P2b: navigasi Laporan = 2 card (Pusat Laporan, Traceability). URL `/reports` di-redirect ke laporan padanan. Fungsi
laporan halaman Inventory tersedia di Pusat Laporan (Posisi Stok, Min/Max & Reorder, Kartu Stok Qty, dan "Riwayat
Pergerakan Stok" sebagai padanan tab Kartu Stok (Ledger)); halaman operasional `/inventory` tetap (menu Persediaan + drill
Dashboard), endpoint tidak berubah.
P3: card Warehouse = laporan aktif Transfer, Pinjam & Pengembalian, Penyesuaian Stok, Stock Opname (placeholder dihapus).
"""
from __future__ import annotations

CARD_TITLES = {
    "persediaan": "Persediaan & Nilai Persediaan",
    "procurement": "Procurement",
    "warehouse": "Warehouse",
    "spk": "SPK & Kontrak Vendor",
    "hutang": "Invoice & Hutang",
}

# Halaman existing (fungsi berbeda) -> (judul, keterangan, path, permission)
LINKS = {
    "procurement": [("Traceability per Dokumen MRO", "Telusur satu MRO beserta seluruh dokumen turunannya.", "/traceability", "view")],
    "spk": [("Monitoring SPK (Commitment & Realisasi)", "Daftar SPK; realisasi & commitment per SPK pada detail SPK.", "/spk", "view"),
            ("Daftar Kontrak Harga Vendor", "Kontrak harga vendor, masa berlaku, dan addendum.", "/vendor-contracts", "view")],
    "hutang": [("Register Invoice Vendor", "Invoice vendor beserta status verifikasi & pembayaran.", "/invoice?tab=invoice", "invoice.view"),
               ("Status Penagihan DO", "DO yang sudah/belum ditagihkan supplier.", "/invoice?tab=do", "invoice.view"),
               ("Outstanding DP Supplier", "DP supplier menunggu verifikasi & sudah dibayar.", "/dp-supplier", "supplier_dp.view")],
}

# Belum tersedia -> (judul, fase)
PLANNED = {
    "spk": [("Realisasi Anggaran SPK (rekap seluruh SPK)", "P4"), ("Kepatuhan Harga PO terhadap Kontrak", "P4")],
    "hutang": [("Aging Hutang Supplier", "P5"), ("Register Pembayaran", "P5"), ("Kartu Hutang Supplier", "P5")],
}


def card_extras(server, user, group_key) -> dict:
    links = [{"title": t, "description": d, "to": to} for t, d, to, perm in LINKS.get(group_key, []) if server.has_perm(user, perm)]
    planned = [{"title": t, "phase": ph} for t, ph in PLANNED.get(group_key, [])]
    return {"links": links, "planned": planned}
