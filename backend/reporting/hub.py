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
P4: card SPK & Kontrak Vendor = laporan aktif Realisasi Anggaran SPK (+ detail PO / DO), Daftar Kontrak Harga Vendor (menggantikan
tautan halaman `/vendor-contracts`; halaman operasional tetap untuk input/edit, dibuka dari drill laporan), Kepatuhan Harga PO vs
Kontrak; tautan "Monitoring SPK" -> `/spk` tetap (placeholder P4 dihapus).
P5: card Invoice & Hutang = laporan aktif Register Invoice Vendor (menggantikan tautan `/invoice?tab=invoice`; halaman
operasional Invoice tetap untuk input/pembayaran & dibuka dari drill), Monitoring Pembayaran, Outstanding (+ ringkasan), Aging,
Rekap Hutang per Supplier (+ per bulan); tautan "Status Penagihan DO" & "Outstanding DP Supplier" tetap; seluruh placeholder P5
(termasuk "Kartu Hutang Supplier" — terwakili laporan P5) dihapus.
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
    "spk": [("Monitoring SPK (Commitment & Realisasi)", "Daftar SPK; realisasi & commitment per SPK pada detail SPK.", "/spk", "view")],
    "hutang": [("Status Penagihan DO", "DO yang sudah/belum ditagihkan supplier.", "/invoice?tab=do", "invoice.view"),
               ("Outstanding DP Supplier", "DP supplier menunggu verifikasi & sudah dibayar.", "/dp-supplier", "supplier_dp.view")],
}

# Belum tersedia -> (judul, fase)
PLANNED: dict = {}


def card_extras(server, user, group_key) -> dict:
    links = [{"title": t, "description": d, "to": to} for t, d, to, perm in LINKS.get(group_key, []) if server.has_perm(user, perm)]
    planned = [{"title": t, "phase": ph} for t, ph in PLANNED.get(group_key, [])]
    return {"links": links, "planned": planned}
