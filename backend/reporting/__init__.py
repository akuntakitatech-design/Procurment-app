"""Reporting foundation — perhitungan reusable untuk Dashboard & Laporan.

Sumber kebenaran tetap transaksi existing (tanpa summary table/cache):
- scope.py       : resolver filter (periode/divisi/project/supplier) + izin + predikat baris
- procurement.py : KPI procurement (Status Dokumen PO derived, receipt status, MRO/RO outstanding)
- finance.py     : KPI hutang & pembayaran (engine Invoice Vendor + DP Supplier existing)
- charts.py      : tren bulanan, komposisi Status Dokumen, ranking supplier
- attention.py   : daftar PO/Invoice yang perlu ditindaklanjuti
- service.py     : orkestrasi GET /api/dashboard/control-center
"""
