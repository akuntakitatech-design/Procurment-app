"""Pusat Laporan — konsolidasi 5 card kategori (P2a).

Setiap card = laporan aktif di REGISTRY (ber-permission) + halaman laporan existing di modul lain yang fungsinya BERBEDA
(bukan duplikat laporan Pusat Laporan; tautan tetap ke halaman aslinya, permission aslinya) + laporan yang belum
tersedia (ditandai jelas "Segera tersedia", tidak dapat diklik). Laporan lama `/reports` (MRO Traceability, Lead Time,
Pemakaian Unit) sudah digantikan penuh oleh versi Pusat Laporan -> tidak didaftarkan ganda; halaman & endpoint lama tetap.
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
    "procurement": [("Outstanding Permintaan/Pembelian (MRO, RO, PO, DO)", "P2b"), ("Rekap Pembelian", "P2b"),
                    ("Rekap Nilai Penerimaan DO", "P2b")],
    "warehouse": [("Transfer Antar Gudang", "P3"), ("Pinjam Barang & Return", "P3"), ("Penyesuaian Stok", "P3"),
                  ("Stock Opname", "P3")],
    "spk": [("Realisasi Anggaran SPK (rekap seluruh SPK)", "P4"), ("Kepatuhan Harga PO terhadap Kontrak", "P4")],
    "hutang": [("Aging Hutang Supplier", "P5"), ("Register Pembayaran", "P5"), ("Kartu Hutang Supplier", "P5")],
}


def card_extras(server, user, group_key) -> dict:
    links = [{"title": t, "description": d, "to": to} for t, d, to, perm in LINKS.get(group_key, []) if server.has_perm(user, perm)]
    planned = [{"title": t, "phase": ph} for t, ph in PLANNED.get(group_key, [])]
    return {"links": links, "planned": planned}
