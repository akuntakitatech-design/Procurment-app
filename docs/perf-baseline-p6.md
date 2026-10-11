# Baseline Performa P6 — Daftar Transaksi & Export Daftar (sebelum Performance Optimization)

Tujuan: titik pembanding untuk fase Performance Optimization (PR terpisah). **Tidak ada optimasi di P6.**

## Lingkungan & metode
- DB test terisolasi `proc_itest` (MariaDB 10.11, lokal 127.0.0.1), backend test terisolasi port 8013 (`production_bootstrap.py`,
  storage lokal sementara). Bukan preview/sandbox, bukan production.
- Fixture: `backend/tests/report_txn_test.py` (KEEP_DB=1) — 1 tenant uji, data seluruh 14 daftar lewat API existing.
- Skrip: `backend/scripts/perf_baseline_p6.py` (read-only kecuali `--seed`, yang menanam dokumen MRO & PO volume ke tenant uji).
- Pengukuran per daftar: GET daftar halaman 1 (`page=1&page_size=25`; DP Supplier tanpa halaman), JSON Pusat Laporan
  `report-center/txn-*`, `export.xlsx`, `export.pdf`. Median / p95 (ms) dari repetisi R; kolom Query DB = header `Server-Timing` Excel.
- Waktu = klien HTTP lokal (termasuk serialisasi & pembuatan file), satu klien, tanpa beban paralel.

## A. Ukuran fixture (R = 5, tanpa seed)
| Daftar | Endpoint daftar (hal. 1, 25 baris) median / p95 ms | Total daftar | JSON export median / p95 ms | Baris export | Excel median / p95 ms | PDF median / p95 ms | Query DB (Excel) |
|---|---|---|---|---|---|---|---|
| txn-mro | 15 / 15 | 31 | 13 / 13 | 31 | 35 / 39 | 78 / 128 | db;dur=10;desc="25 q max 1ms" |
| txn-ro | 7 / 8 | 3 | 8 / 8 | 3 | 24 / 25 | 33 / 36 | db;dur=8;desc="19 q max 1ms" |
| txn-po | 9 / 10 | 3 | 9 / 10 | 3 | 27 / 29 | 36 / 38 | db;dur=8;desc="23 q max 1ms" |
| txn-do | 8 / 9 | 2 | 8 / 10 | 2 | 25 / 27 | 36 / 38 | db;dur=7;desc="22 q max 1ms" |
| txn-mi | 6 / 7 | 0 | 6 / 6 | 0 | 22 / 24 | 30 / 32 | db;dur=7;desc="13 q max 2ms" |
| txn-transfer | 7 / 7 | 3 | 8 / 10 | 3 | 25 / 27 | 33 / 35 | db;dur=6;desc="16 q max 1ms" |
| txn-loan | 7 / 36 | 2 | 7 / 8 | 2 | 26 / 27 | 34 / 34 | db;dur=7;desc="17 q max 1ms" |
| txn-adjustment | 6 / 7 | 2 | 7 / 8 | 2 | 25 / 26 | 32 / 34 | db;dur=7;desc="17 q max 1ms" |
| txn-opname | 5 / 6 | 0 | 5 / 6 | 0 | 22 / 22 | 29 / 31 | db;dur=3;desc="7 q max 1ms" |
| txn-spk | 5 / 6 | 2 | 6 / 6 | 2 | 24 / 27 | 32 / 33 | db;dur=3;desc="7 q max 1ms" |
| txn-vendor-contract | 5 / 6 | 1 | 6 / 6 | 1 | 24 / 28 | 30 / 31 | db;dur=3;desc="7 q max 1ms" |
| txn-invoice | 8 / 8 | 1 | 8 / 8 | 1 | 28 / 29 | 35 / 37 | db;dur=7;desc="22 q max 1ms" |
| txn-do-billing | 8 / 9 | 2 | 9 / 9 | 2 | 28 / 29 | 35 / 40 | db;dur=8;desc="24 q max 1ms" |
| txn-supplier-dp | 5 / 6 | 1 | 6 / 6 | 1 | 24 / 26 | 33 / 60 | db;dur=4;desc="9 q max 1ms" |

## B. Volume (R = 3, `--seed 5100`: +5.100 MRO & +5.100 PO)
| Daftar | Endpoint daftar (hal. 1, 25 baris) median / p95 ms | Total daftar | JSON export median / p95 ms | Baris export | Excel median / p95 ms | PDF median / p95 ms | Query DB (Excel) |
|---|---|---|---|---|---|---|---|
| txn-mro | 134 / 136 | 1000 | 525 / 544 | 5131 | 1403 / 1446 | 422 (batas PDF 5.000) 493 / 520 | db;dur=206;desc="25 q max 36ms" |
| txn-ro | 7 / 9 | 3 | 8 / 9 | 3 | 25 / 25 | 34 / 35 | db;dur=7;desc="19 q max 1ms" |
| txn-po | 137 / 171 | 1000 | 485 / 507 | 5103 | 1309 / 1334 | 422 (batas PDF 5.000) 481 / 485 | db;dur=178;desc="23 q max 35ms" |
| txn-do | 9 / 10 | 2 | 11 / 11 | 2 | 26 / 27 | 36 / 38 | db;dur=8;desc="22 q max 1ms" |
| txn-mi | 6 / 6 | 0 | 6 / 9 | 0 | 25 / 25 | 30 / 31 | db;dur=7;desc="13 q max 2ms" |
| txn-transfer | 7 / 7 | 3 | 7 / 7 | 3 | 25 / 28 | 34 / 36 | db;dur=6;desc="16 q max 1ms" |
| txn-loan | 7 / 8 | 2 | 7 / 7 | 2 | 27 / 27 | 34 / 38 | db;dur=7;desc="17 q max 1ms" |
| txn-adjustment | 7 / 8 | 2 | 7 / 8 | 2 | 25 / 26 | 34 / 41 | db;dur=8;desc="17 q max 3ms" |
| txn-opname | 6 / 7 | 0 | 7 / 8 | 0 | 25 / 28 | 32 / 35 | db;dur=4;desc="7 q max 1ms" |
| txn-spk | 5 / 6 | 2 | 6 / 6 | 2 | 26 / 29 | 35 / 41 | db;dur=4;desc="7 q max 1ms" |
| txn-vendor-contract | 5 / 5 | 1 | 6 / 6 | 1 | 25 / 26 | 31 / 31 | db;dur=3;desc="7 q max 1ms" |
| txn-invoice | 8 / 8 | 1 | 8 / 9 | 1 | 30 / 31 | 36 / 38 | db;dur=8;desc="22 q max 1ms" |
| txn-do-billing | 9 / 10 | 2 | 9 / 9 | 2 | 29 / 30 | 36 / 40 | db;dur=9;desc="24 q max 2ms" |
| txn-supplier-dp | 46 / 47 | 1 | 47 / 48 | 1 | 65 / 67 | 73 / 74 | db;dur=25;desc="9 q max 21ms" |

## Catatan / temuan untuk fase Performance Optimization
1. **Batas muat daftar 1.000 dokumen (perilaku existing, tidak diubah P6).** Endpoint daftar MRO/RO/PO/DO/MI/Transfer/Pinjam/
   Penyesuaian/Opname memuat maksimal 1.000 dokumen terbaru (`list_cap.DEFAULT_CAP`, sama dengan `to_list(1000)` sebelum P6). Pada
   volume B, daftar MRO/PO menampilkan total 1.000, sedangkan export memuat SELURUH hasil (5.131 / 5.103 baris) sesuai syarat P6.
   Rekomendasi: query daftar ber-halaman di DB (filter/sort/limit server-side) agar total daftar = total export tanpa batas muat.
2. **Batas PDF 5.000 ditegakkan** (HTTP 422, pesan jelas, tanpa pemotongan diam-diam) — MRO 5.131 & PO 5.103 baris.
3. Export Excel 5.1k baris ≈ 1,3–1,4 s (DB ≈ 0,2 s; sisanya enrichment Python + penulisan XLSX). Kandidat: enrichment batch & streaming.
4. Daftar halaman 1 pada volume B ≈ 135 ms karena seluruh dokumen (≤ 1.000) dimuat & di-enrich sebelum dipotong per halaman.
