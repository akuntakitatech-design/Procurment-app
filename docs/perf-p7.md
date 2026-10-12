# P7 — Performance Optimization Procurement & Warehouse

Branch `feature/p7-performance` (basis `main` `6e27d1d`, setelah PR #65/#66/#67). Dokumen ini berisi hasil benchmark
**aktual** before/after, bukti hasil identik, keputusan index, arsitektur background export, serta target yang **belum**
tercapai beserta penyebabnya. Tidak ada data yang dikurangi dan tidak ada assertion yang dilemahkan.

## 1. Metode

| Hal | Nilai |
|---|---|
| Database | `proc_perf_itest` (MariaDB 10.11, terisolasi; bukan production / bukan `proc_sandbox`) |
| BEFORE | source `main` `6e27d1d` (git archive) — 1 worker uvicorn, port 8032 |
| AFTER | worktree P7 — 1 worker uvicorn, port 8031, konfigurasi identik (`scripts/perf_p7_backend.sh`) |
| Alat | `scripts/perf_bench_p7.py` (latensi end-to-end HTTP, warm-up 1x lalu 5 pengulangan untuk endpoint cepat; endpoint > 20 dtk 1 pengulangan setelah warm-up), header `Server-Timing` (durasi & jumlah query DB), RSS proses server |
| Paralel | 10 user bersamaan (PO hal.1; campuran menu); auth/me & detail PO selama 2 export Excel besar |
| Hasil mentah (final, di Git) | Benchmark: `docs/perf/p7-before-main*.json` (BEFORE, volume 20k), `docs/perf/p7-after.json` (AFTER, volume 20k), **`docs/perf/p7-final-bench-2026-10-12.json`** (benchmark final ABBA §13). Parity: `docs/perf/p7-parity-full-2026-10-12.json` (P7 awal, §11), **`docs/perf/p7-final-parity-2026-10-12.json`** (kode final, §13) |
| Artefak sementara (tidak di-commit) | `$PERF_ARTIFACT_DIR` (default `<tmp>/procureflow-perf`): hasil per-run parity & partial benchmark. Laporan final parity dibuat `scripts/perf_p7_report.py` (gabung per-persona + tolak data sensitif) |
| Buffer pool InnoDB | 256 MB (default lingkungan ini; tidak diubah — lihat §6) |

### Jumlah data uji aktual

| Modul | Header | Baris/turunan | Target 20.000 |
|---|---:|---:|---|
| MRO | 20.012 | 60.012 baris | tercapai |
| RO | 20.000 | 60.000 baris | tercapai |
| PO | 20.000 | 60.000 baris | tercapai |
| SPK | 20.000 | – | tercapai |
| DO | 16.000 | 48.000 baris | **di bawah target** |
| Invoice Vendor | 16.000 | – | **di bawah target** |
| Penyesuaian | 11.360 | 88.480 baris | **di bawah target** |
| MI | 10.640 | 31.920 baris | **di bawah target** |
| Transfer | 8.160 | 24.480 baris | **di bawah target** |
| Pinjam | 5.000 | 10.000 baris | **di bawah target** |
| Kontrak vendor | 2.000 | – | **di bawah target** |
| Barang (master) | 2.000 | – | **di bawah target** |
| Alokasi / stock ledger / valuation ledger | 241.040 / 113.480 / 113.480 | – | – |
| Audit log | ±91.000 | – | – |

Modul di bawah 20.000 diuji pada jumlah di atas (disetujui user); hasilnya **tidak** diklaim berlaku untuk skala 20.000.

> Penting membaca angka BEFORE: daftar paged di `main` hanya memproses **1.000 dokumen terbaru** (kolom "Total baris"
> before = 1000) sehingga total, pencarian, filter dan sorting **salah** untuk data > 1.000. P7 memperbaikinya: total & hasil
> mencakup seluruh data (20.000). Karena itu pencarian/filter/sort lintas seluruh data AFTER memproses ±20x lebih banyak
> dokumen daripada BEFORE dan terlihat "lebih lambat" — perbandingan itu bukan apel-ke-apel.

## 2. Hasil before/after (end-to-end, ms)

| Area | Before p50 / p95 | After p50 / p95 | Perubahan p50 | Query before → after | RSS puncak MB before → after | Total baris before → after |
|---|---|---|---|---|---|---|
| Dashboard | 3.9 s / 5.1 s | 1.8 s / 1.9 s | 2.2x lebih cepat | 2021 → 22 | 291 → 276 | – |
| Dashboard Premium | 1.9 s / 2.8 s | 2.7 s / 2.9 s | 1.4x lebih lambat | 11 → 11 | 488 → 380 | – |
| Control Center (bulan) | ±266 s (baseline P6) | 139.4 s | ±1.9x lebih cepat | – → 87 | – → 3324 | – |
| MRO hal.1 (+hitungan tahap) | 7.5 s / 7.7 s | 26.0 s | 3.5x lebih lambat (*) | 23 → 26 | 369 → 2562 | 1000 → 20012 |
| MRO hal.40 | 7.1 s / 7.2 s | 684 ms / 703 ms | 10.4x lebih cepat | 23 → 24 | 314 → 1240 | 1000 → 20012 |
| MRO cari | 7.2 s / 7.3 s | 33.7 s | 4.7x lebih lambat (*) | 23 → 17 | 313 → 1478 | 1000 → 20012 |
| MRO sort no | 7.3 s / 7.4 s | 705 ms / 742 ms | 10.3x lebih cepat | 23 → 24 | 313 → 1292 | 1000 → 20012 |
| MRO filter periode | 7.1 s / 7.2 s | 1.1 s / 1.1 s | 6.8x lebih cepat | 23 → 12 | 312 → 1075 | 0 → 0 |
| MRO detail | 32 ms / 35 ms | 66 ms / 70 ms | 2.1x lebih lambat (**) | 16 → 16 | 312 → 1069 | – |
| RO hal.1 | 3.7 s / 3.9 s | 694 ms / 705 ms | 5.4x lebih cepat | 17 → 18 | 318 → 1069 | 1000 → 20000 |
| RO cari | 3.6 s / 3.6 s | 44.9 s | 12.5x lebih lambat (*) | 17 → 17 | 317 → 1449 | 1000 → 20000 |
| PO hal.1 | 10.7 s / 12.1 s | 1.1 s / 1.1 s | 9.9x lebih cepat | 23 → 24 | 361 → 1352 | 1000 → 20000 |
| PO hal.100 (size 100) | 10.1 s / 10.8 s | 1.2 s / 1.2 s | 8.7x lebih cepat | 23 → 24 | 364 → 2018 | 1000 → 20000 |
| PO cari | 10.6 s / 10.9 s | 51.8 s | 4.9x lebih lambat (*) | 23 → 23 | 370 → 2078 | 1000 → 20000 |
| PO filter penerimaan | 10.7 s / 11.1 s | 52.5 s | 4.9x lebih lambat (*) | 23 → 23 | 369 → 2102 | 200 → 4000 |
| PO sort nilai | 11.1 s / 12.7 s | 53.8 s | 4.8x lebih lambat (*) | 23 → 23 | 369 → 2168 | 1000 → 20000 |
| PO sort Approval 2 | 10.3 s / 10.4 s | 53.1 s | 5.2x lebih lambat (*) | 23 → 23 | 364 → 2158 | 1000 → 20000 |
| PO detail | 47 ms / 49 ms | 87 ms / 140 ms | 1.9x lebih lambat (**) | 65 → 65 | 363 → 1331 | – |
| DO hal.1 | 4.3 s / 5.3 s | 581 ms / 619 ms | 7.4x lebih cepat | 20 → 21 | 363 → 1323 | 1000 → 16000 |
| DO detail | 42 ms / 97 ms | 75 ms / 116 ms | 1.8x lebih lambat (**) | 33 → 33 | 363 → 1321 | – |
| MI hal.1 | 542 ms / 3.3 s | 381 ms / 430 ms | 1.4x lebih cepat | 16 → 17 | 363 → 1320 | 1000 → 10640 |
| MI detail | 35 ms / 35 ms | 63 ms / 111 ms | 1.8x lebih lambat (**) | 18 → 18 | 363 → 1234 | – |
| Transfer hal.1 | 345 ms / 351 ms | 322 ms / 363 ms | 1.1x lebih cepat | 14 → 15 | 363 → 1233 | 1000 → 8160 |
| Pinjam hal.1 | 402 ms / 440 ms | 210 ms / 255 ms | 1.9x lebih cepat | 1013 → 15 | 363 → 1231 | 1000 → 5000 |
| Penyesuaian hal.1 | 819 ms / 1.0 s | 382 ms / 428 ms | 2.1x lebih cepat | 1013 → 15 | 362 → 1231 | 1000 → 11360 |
| Opname hal.1 | 7 ms / 67 ms | 10 ms / 17 ms | ≈ | 5 → 6 | – | 0 → 0 |
| Inventory item-stock | 49 ms / 54 ms | 52 ms / 54 ms | ≈ | 10 → 10 | – | 2000 → 2000 |
| Inventory ledger | 1.7 s / 1.7 s | 2.0 s / 2.0 s | 1.2x lebih lambat | 6 → 6 | – | 500 → 500 |
| Gudang item-warehouse | 46 ms / 47 ms | 86 ms / 87 ms | 1.9x lebih lambat (**) | 6 → 6 | – | 1106 → 1106 |
| Master barang hal.1 | 37 ms / 37 ms | 74 ms / 120 ms | 2.0x lebih lambat (**) | 7 → 7 | – | 2000 → 2000 |
| SPK hal.1 / cari | 265 / 269 ms | 304 / 301 ms | ≈ | 5 → 5 | – | 20000 / 488 |
| Kontrak Vendor hal.1 | 33 ms | 35 ms | ≈ | 5 → 5 | – | 2000 |
| Invoice Vendor hal.1 | 54.8 s | 37.2 s | 1.5x lebih cepat | 20 → 20 | 1092 → 1795 | 16000 → 16000 |
| Tagihan DO hal.1 | 66.4 s | 50.7 s | 1.3x lebih cepat | 22 → 22 | 1056 → 1871 | 16000 → 16000 |
| Approval inbox / lookup / katalog laporan | 8 / 97 / 6 ms | 10 / 99 / 7 ms | ≈ | sama | – | – |
| Lap. Register PO | 95.1 s | 57.6 s | 1.7x lebih cepat | 24 → 24 | 1432 → 2160 | – |
| Lap. posisi stok | 20.3 s | 11.2 s / 11.6 s | 1.8x lebih cepat | 13 → 13 | 1236 → 2126 | – |
| Lap. AP outstanding | 56.3 s | 38.3 s | 1.5x lebih cepat | 21 → 21 | 1106 → 2089 | – |
| Lap. MRO traceability (bulan) | tidak diukur di main | 131.9 s | – | – → 89 | – → 2704 | – |
| Export daftar PO Excel 20k | 103.4 s | 56.7 s | 1.8x lebih cepat | 25 → 25 | 1448 → 2397 | 20000 |
| Export daftar MRO Excel 20k | 131.5 s | 49.7 s | 2.6x lebih cepat | 25 → 19 | 1212 → 1901 | 20012 |
| Export daftar PO PDF (periode) | 98.3 s | 55.8 s | 1.8x lebih cepat | 25 → 25 | 1448 → 2403 | 1000 |
| Export Register PO Excel 20k | 100.8 s | 58.8 s | 1.7x lebih cepat | 25 → 25 | 1451 → 2405 | 20000 |

(*) BEFORE hanya mencari/menyortir dalam 1.000 dokumen terbaru (hasil salah untuk data > 1.000); AFTER lintas 20.000 (benar).
Dibanding run AFTER pertama sesi ini (sebelum optimasi lanjutan): MRO cari 116.8 → 33.7 s, MRO hitungan 58.7 → 26.0 s,
PO cari 73.5 → 51.8 s, Invoice 58.2 → 37.2 s, Tagihan DO 71.6 → 50.7 s, Register PO 79.3 → 57.6 s, export MRO 105.5 → 49.7 s.

(**) Endpoint kecil (≤ 140 ms). Proses AFTER memegang heap Python jauh lebih besar setelah memproses 20.000 dokumen
(RSS ±1,2 GB vs ±0,36 GB), sehingga GC menambah puluhan ms. Detail PO/DO/MI p95 111–140 ms **melewati target < 100 ms**.

### Uji paralel (1 worker uvicorn)

| Uji | Before | After |
|---|---|---|
| 10 user paralel — PO hal.1 | p50 19.1 s / p95 19.5 s / 0.4 req/s | p50 7.6 s / p95 8.9 s / 1.1 req/s |
| 10 user paralel — campuran menu (termasuk Invoice/laporan) | p50 32.7 s / p95 92.6 s / 0.2 req/s | p50 7.3 s / p95 59.1 s / 0.4 req/s |
| auth/me & PO detail saat 2 export Excel besar berjalan | p50 1.0 s / p95 1.4 s | p50 1.1 s / p95 1.6 s |
| Error HTTP / timeout | 0 | 0 |

## 3. Status target user

| Target | Hasil AFTER | Status |
|---|---|---|
| Daftar hal.1 / paging / sort / filter periode p95 ≤ 1,5 dtk | MRO/RO/PO/DO/MI/Transfer/Pinjam/Penyesuaian 0,25–1,2 dtk | **Tercapai** (user global) |
| Pencarian / filter turunan lintas seluruh data p95 ≤ 1,5 dtk | MRO 33,7 / RO 44,9 / PO 51,8–53,8 dtk | **Belum** |
| Detail < 100 ms | MRO 70 ms; PO/DO/MI p95 111–140 ms | **Sebagian** |
| Dashboard ≤ 1,5 dtk | p95 1,9 dtk; Premium 2,9 dtk | **Belum** (Dashboard 2,7x lebih cepat) |
| Vendor Invoice & Tagihan DO ≤ 3 dtk | 37,2 / 50,7 dtk | **Belum** |
| Laporan ≤ 10–15 dtk | posisi stok 11,2 dtk; Register PO 57,6; AP 38,3; traceability 131,9 | **Sebagian** |
| Control Center ≤ 15 dtk | 139 dtk | **Belum** |
| Export Excel 20k ≤ 45 dtk | 49,7–58,8 dtk (export besar kini job background, UI tidak menunggu) | **Belum** (dekat) |
| 10 user paralel p95 ≤ 3 dtk, 0 error | p95 8,9 dtk (PO hal.1), 0 error | **Belum** (0 error tercapai) |

## 4. Penyebab utama yang tersisa (terukur)

1. **I/O MariaDB pada `IN` raksasa.** Pencarian/filter lintas data, Invoice, Tagihan DO, laporan dan export harus memperkaya
   seluruh dokumen (lineage MRO→RO→PO→DO, penerimaan, approval). Query `allocations WHERE target_line_id IN (±60.000)`
   dipilih optimizer sebagai **full table scan** (EXPLAIN `type=ALL`) dan butuh 12–13 dtk per scan karena tabel (±345 MB data +
   ±400 MB index) jauh lebih besar dari buffer pool 256 MB. Projection kolom (JSON_EXTRACT) tidak mengubah waktu (diukur:
   13,3 vs 13,5 dtk) — dibatasi baca halaman disk, bukan transfer.
2. **Satu worker Python** untuk semua request: CPU per request (filter/sort/serialisasi 20.000 baris) mengantre saat paralel.
3. **Control Center / MRO traceability** memuat dan mengagregasi seluruh data di Python (RSS 2,7–3,3 GB).
4. **Hitungan per tahap MRO & pencarian** memerlukan lifecycle seluruh MRO (tidak bisa dihitung hanya dari header tanpa
   mengubah hasil).

## 5. Optimasi P7 (semuanya jalur BACA; tulis/posting/MWA/HPP/ledger/approval tidak diubah)

| Optimasi | File | Bukti identik |
|---|---|---|
| Paging server-side: header minimal → urutan & total dihitung di DB/Python ringan, hanya baris halaman yang diperkaya (user global tanpa cari/filter turunan); selain itu jalur lengkap tanpa batas 1.000 | `txn_list_paging_layer.py`, `list_cap.py`, `doc_*` | `p7_list_paging_test` 10/10 (jalur cepat == jalur lengkap: total, urutan, facets, >1.000 dokumen, tenant/scope) |
| Pushdown filter + verifikasi Python, top-k, projection tanpa deep-copy, baca massal di thread | `mariadb_motor.py` | `p7_adapter_equivalence_test` 13/13 |
| Urutan dasar `created_at, pk` dihitung di Python bila SQL perlu filesort (collation `utf8mb4_unicode_ci` dibuktikan; fallback ORDER BY SQL) | `mariadb_motor.py` (`_py_order`, `_pk_pair_safe`) | T8/T9/T11 (dibandingkan dengan collation MariaDB nyata) |
| Memo baca per request GET (SQL+param identik dibaca sekali, query bersamaan dibagi; invalidasi saat tulis/transaksi; anggaran global 256 MB) | `mariadb_motor.py` | T10/T12 |
| N+1 dihapus: Dashboard 2.021 → 22 query, Pinjam/Penyesuaian 1.013 → 15 query | `doc_reports.py`, `doc_warehouse.py` | regresi + parity Dashboard/Pinjam/Penyesuaian identik |
| Lifecycle/monitor MRO & lineage upstream: 1 scan alokasi bertipe (dibagi via memo) menggantikan 4–5 full scan | `txn_list_paging_layer.py`, `doc_procurement.py`, `receipt_control_layer.py` | `p7_lifecycle_scan_test` 4/4 (kasus tepi array/kosong/None; semantik kolom generated) |
| Batch traceability MRO (tanpa query per dokumen), redaksi harga dipertahankan | `report_trace_detail.py` | `p7_trace_batch_test` 9/9 |
| Invoice/Tagihan DO: trace DO tanpa membangun daftar item yang tidak dipakai | `vendor_invoice_layer.py` | parity Invoice/Tagihan DO identik |
| Frontend: route lazy-loading (bundle awal −337 kB gzip), debounce + abaikan respons lama (daftar & hitungan tahap MRO) | `App.js`, `serverList.js`, `Mro.jsx` | build + 23 file test frontend PASS |
| Export besar sebagai job background | `reporting/export_jobs.py`, `lib/exportJob.js`, `lib/backgroundExport.js` | `p7_export_jobs_test` 21/21 |

## 6. Index

Tidak ada index baru. Bukti: query detail/IN kecil (≤ 5.000 nilai) sudah memakai index existing (`type=range`,
`idx_allocations_target_line_id`, ±30 ms untuk 900 nilai); query lambat adalah `IN` raksasa yang secara rasional dipilih
optimizer sebagai full scan — index tambahan tidak mengubah rencana. Filesort `ORDER BY created_at, pk` pada hasil besar
dihilangkan lewat urutan Python (bukan index). Sesuai arahan, index tanpa manfaat terukur tidak dipasang; tidak ada DDL.

**Rekomendasi (butuh persetujuan; konfigurasi server, bukan kode):** naikkan `innodb_buffer_pool_size` ke ≥ ukuran working
set (±1–2 GB untuk volume uji ini). Diperkirakan paling berdampak untuk pencarian lintas data, Invoice, Tagihan DO, laporan,
export dan Control Center. Belum diuji karena server MariaDB dipakai bersama preview.

## 7. Background export

- Excel > 5.000 baris (daftar transaksi & Pusat Laporan) → `POST /api/report-center/{key}/export-jobs?fmt=` ; kecil tetap unduh langsung.
- Status `queued → running → done | failed | expired`, toast notifikasi di aplikasi (tetap berjalan saat pindah menu), tombol Unduh / Ulangi.
- Keamanan: job terikat tenant + user pembuat + key + filter/sort; user lain → 404; izin `export` diperiksa saat buat **dan**
  saat unduh; file berharga ditolak (403) bila izin harga dicabut; redaksi harga server-side (engine export yang sama).
  File di direktori privat 0700 dengan nama acak (`EXPORT_JOB_DIR`, default `/tmp/procureflow-export-jobs`), unduh lewat endpoint
  terotentikasi — tanpa URL publik; job tidak menyimpan token/password.
- Integritas: engine & batas sama dengan export langsung (Excel 100.000 / PDF 5.000 → gagal 422 tanpa file); `data_as_of` =
  cut-off saat job mulai; file ditulis atomik (`.part` → final) sehingga job gagal tidak pernah menghasilkan file.
- Retry: hanya kegagalan sementara, maks 3 percobaan; kegagalan permanen (400/403/422) → 409. Idempoten: permintaan identik
  selagi berjalan mengembalikan job yang sama. Restart/crash: heartbeat 15 dtk; job aktif tanpa heartbeat > 120 dtk
  (`EXPORT_JOB_STALE_SECONDS`) → `failed` dan dapat diulang (aman untuk beberapa worker pada host yang sama; file lokal per host — deployment multi-host butuh storage bersama).
- Cleanup: file > TTL 1 jam (`EXPORT_JOB_TTL_SECONDS`, default 3600) dihapus saat startup dan berkala (tiap ≤ 5 menit saat ada aktivitas
  job); job kedaluwarsa ditandai `expired`; tidak menyentuh lampiran/dokumen transaksi.
- Concurrency: maks job berjalan per proses (`EXPORT_JOB_MAX_RUNNING`, default 2) + maks 3 job aktif per user; rendering Excel/PDF di
  thread. Selama 2 export besar berjalan, auth/me + detail PO p95 1,6 dtk.

## 8. Bukti hasil identik (parity BEFORE `main` vs AFTER P7, DB & parameter sama)

Lihat `docs/perf/p7-parity-full-2026-10-12.json` (3 user: global, terbatas 1 divisi, tanpa `view_purchase_price`; dihasilkan
`scripts/perf_p7_parity.py` per persona lalu digabung `scripts/perf_p7_report.py`). Ringkasan di §8.1. Hasil parity
parsial awal (42 baris, 2 user) telah digantikan file lengkap tersebut dan tidak lagi disimpan di Git.

## 9. Insiden & catatan lingkungan

- Kontainer sempat restart 1x saat profiling in-process endpoint Invoice (memori). Setelahnya MariaDB tidak otomatis start
  (supervisor FATAL "can't find command" walau binari ada) → di-start manual; backend preview di-restart. Skrip jejak kini
  memiliki pengaman RSS; server benchmark dijaga watchdog RSS.
- Temuan keamanan **pre-existing (bukan dari P7)**: user tanpa `view_purchase_price` masih menerima sebagian nilai harga PO
  (`gross_total`, `subtotal_after_*`, `dp_amount`/`dp_value`, `lines[].dpp`, `display_price`) di daftar & detail PO karena
  layer diskon/DPP/UoM menambah field setelah redaksi. Sama persis di `main` (tidak diubah P7). Dilaporkan terpisah.

## 10. Rekomendasi berikutnya

1. Buffer pool MariaDB sesuai working set (§6) — lalu ulangi benchmark ini.
2. Worker uvicorn > 1 (atau worker terpisah untuk export/laporan berat) agar request ringan tidak mengantre.
3. Agregasi SQL untuk Control Center & MRO traceability (perlu desain + parity khusus per KPI).
4. Indeks pencarian ter-materialisasi (search text per dokumen) dengan invalidasi saat tulis — untuk cari lintas data < 1,5 dtk.
5. Perbaiki kebocoran harga pre-existing (§9) di PR terpisah.

## 11. Verifikasi ulang terisolasi — 2026-10-12 (agent baru, kontainer baru)

Lingkungan: MariaDB **11.8.9** lokal (sama dengan production), DB `*_itest` terpisah, storage lokal. Preview Emergent memakai `proc_sandbox` + S3 lokal (SeaweedFS). **Tidak ada koneksi ke production.**

| Gate | Hasil |
|---|---|
| Regresi `run_regression_itest.sh` (P7) | **38/38 file, 1.756/1.756 check PASS** |
| Integrity `run_integrity_tests_mariadb.sh` (P7) | **13/13 PASS** |
| Parity `main`(6e27d1d) vs P7, 3 user (global, terbatas divisi, tanpa izin harga), ±117 endpoint | **321/339 identik**. 18 sisanya dijelaskan di bawah. File: `docs/perf/p7-parity-full-2026-10-12.json` |
| UAT otomatis (testing agent) di sandbox | backend 29/29, frontend semua halaman kritis tanpa error/ChunkLoadError |

Dataset parity (`proc_perf_itest`): seed API nyata `scripts/perf_p7_seed.py` (60 alur MRO→RO→PO→DO→MI), lalu `perf_p7_dataset.py clone 25` + `extra 1500`. Hasilnya MRO 1.560, RO 1.560, PO 1.404, DO 1.248, MI 416, SPK 3.000, Invoice 1.248, Pinjam 375. MRO/RO/PO/DO sengaja di atas batas lama 1.000.

Cakupan parity tambahan sesi ini: **Control Center** (bulan/tahun/default), **MRO Traceability** (laporan, periode, export Excel, detail traceability), lifecycle MRO/RO/PO/DO, detail MRO/RO/PO/DO/MI/Pinjam, drill price-control/SPK, lead-time, unit usage, approval inbox, cari global, Pull (RO→PO, PO→DO, MRO→RO), paging hal.1, dan **seluruh 48 key Pusat Laporan** (periode 1 tahun), untuk ketiga user.

Penjelasan 18 baris non-identik:
- 9× **Control Center**: hanya `timing_ms` (durasi eksekusi). Setelah `timing_ms` dinormalisasi (VOLATILE), hasil **identik 9/9**.
- 9× **paging hal.1** MRO/PO/DO: hanya `total` (main 1.000 karena cap, P7 = jumlah sebenarnya). Ini **sesuai desain P7**. Isi `items` halaman 1 dan 2 (urutan default) **identik** untuk ketiga user. Sort `no asc` berbeda karena main hanya mengurutkan 1.000 dokumen terbaru. Hasil P7 diverifikasi sama dengan 25 nomor terkecil di seluruh DB (MRO/PO/DO).
- Status non-200 identik di kedua server: 403 laporan nilai untuk user tanpa izin harga, 404 key grup katalog.

### Regresi performa yang DITEMUKAN (belum diperbaiki — butuh persetujuan)
Endpoint pola N+1 **lebih lambat di P7**, padahal hasilnya identik dan jumlah query sama:

| Endpoint (global, median 3×) | main | P7 | P7 + `MARIADB_SYNC_READS=0` | Query |
|---|---|---|---|---|
| `pull/ro-for-po` | 1.255 ms | 3.586 ms | 1.383 ms | 6.569 |
| `pull/mro-for-ro` | 860 ms | 2.839 ms | 1.047 ms | 4.691 |
| `pull/po-for-do` | 553 ms | 1.205 ms | – | 2.206 |
| `reports/lead-time` | 737 ms | 1.623 ms | 772 ms | 3.824 |

Penyebab: P7 mengarahkan **semua** baca (termasuk `find_one`/query titik) lewat pymysql sinkron di `ThreadPoolExecutor` (`_fetchall_bulk`, `MARIADB_SYNC_READS=1` default). Untuk ribuan query kecil berurutan, overhead thread hop ±0,3 ms per query mendominasi.
Usulan: jalur sinkron hanya untuk baca massal, sedangkan query titik/kecil (`limit(1)`, filter `id`) tetap async. Setelah itu regresi + parity diulang. Merge #69 **tidak** disarankan sebelum ini diputuskan.

## 12. Perbaikan regresi `MARIADB_SYNC_READS` — 2026-10-12

**Perubahan** (`mariadb_motor.py`): jalur baca **adaptif per bentuk SQL**. Kuncinya teks SQL dengan placeholder, tanpa parameter. Rata-rata jumlah baris per bentuk dicatat (EWMA, maks 8.192 bentuk).
- Bentuk yang terbukti kecil (≤ `MARIADB_SYNC_MIN_ROWS`, default 64): dibaca lewat aiomysql langsung (`_small_fetchall`, tanpa thread hop), dan `_select_topk` tidak memakai snapshot 2 tahap (4 statement + thread hop), melainkan jalur penuh 1 query yang hasilnya identik.
- Bentuk besar tetap memakai PyMySQL di thread pool. Memo per request tetap berlaku di kedua jalur.
- Yang berubah hanya **pemilihan jalur**. SQL, konverter, dan hasil tetap identik.

**Verifikasi (lingkungan terisolasi):**
| Gate | Hasil |
|---|---|
| `p7_adapter_equivalence_test` pada 3 mode ambang (64 / semua kecil / 0) | 13/13 di setiap mode. Test memo kini juga menghitung query jalur kecil. |
| Regresi `run_regression_itest.sh` | **38/38 file, 1.756/1.756** |
| Integrity | **13/13** |
| Parity main(85831df) vs P7-fix, 3 user | **321/330 identik**. 9 sisanya hanya `total` paging (by design). Control Center identik. (Artefak per-run sementara; digantikan hasil final §13.) |

**Benchmark** (dataset parity, median 3× bergantian, 1 request; artefak sementara — digantikan benchmark final §13):
| Endpoint | main | P7 lama | P7-fix |
|---|---|---|---|
| `pull/ro-for-po` | 1.125 | 3.027 | 1.341 |
| `pull/mro-for-ro` | 812 | 2.484 | 1.142 |
| `pull/po-for-do` | 518 | 1.182 | 807 |
| `reports/lead-time` | 886 | 1.543 | **696** |
| MRO/PO/DO paging hal.1 | 200–249 | 55–86 | 51–81 |
| `reports/mro-traceability` | 4.260 | 496 | 498 |
| Dashboard | 146 | 115 | 114 |

10 request paralel (p95, ms): PO hal.1 main 2.283 / P7 lama 602 / **P7-fix 588**. Dashboard 1.015 / 884 / **837**. `pull/po-for-do` 3.199 / 8.805 / **4.262**.

**Sisa yang belum tertutup:** endpoint Pull masih ±10–40% di atas main. Jumlah query sama (contoh: 6.569 untuk `pull/ro-for-po`). Sisa ini bukan dari thread hop, memo, ataupun `_py_order` (diuji dengan mematikan masing-masing), dan sebagian adalah noise karena 4 backend berjalan di 2 vCPU. Penyelesaian tuntas adalah menghapus pola N+1 di endpoint Pull (batch lookup), sebagai pekerjaan terpisah.

## 13. Final P7 — benchmark ABBA terkontrol, akar regresi daftar, Quality Gates (2026-10-12)

Kode final = `afdc940` + perubahan worktree yang di-commit bersama dokumen ini. Basis pembanding: `main` `85831df`
(tidak berubah di `origin` saat diverifikasi). **Tidak ada koneksi ke production** (DB/storage/Coolify).

### 13.1 Gate numerik (dari user)
- Semua endpoint **Pull**: p50 **dan** p95 P7 ≤ `main` (sampel gabungan benchmark berulang).
- Endpoint non-Pull: regresi maks **10%**, hanya bila repeatable, tanpa dampak UX/timeout dan tanpa regresi fungsional/security,
  serta terdokumentasi di sini.
- Beda `total` paging karena batas lama 1.000 dokumen dihapus diterima **by design** bila kebenaran terbukti (§13.5).

### 13.2 Metode (harness `scripts/perf_p7_bench_final.py`)
- Dua backend terisolasi, 1 worker, entrypoint production (`scripts/perf_p7_backend.sh`): `main` port 8032 (worktree `main`
  `85831df`), P7 port 8034 (worktree final). Proses, port & log terpisah; DB **sama** `proc_perf_itest` (MariaDB 11.8 lokal),
  storage lokal; env benchmark identik (tanpa flag P7 khusus). Hanya GET (read-only) → tidak ada perubahan data selama benchmark.
- Per endpoint: pemanasan (2 + tambahan hingga 10 untuk endpoint ringan) per backend, lalu putaran berpasangan urutan **ABBA**
  (main,P7 | P7,main | P7,main | main,P7) agar bias cache/urutan/drift seimbang. Endpoint berat 9 putaran, ringan (< 100 ms)
  150 putaran per run; **3 run** berurutan → n = 27 / 450 sampel per backend per endpoint. 1 request pada satu waktu.
- Dicatat: p50, p95, jumlah query SQL & durasi DB (header `Server-Timing`), status HTTP, ukuran respons.
- 3 persona: global (Admin), `tanpa_harga` (Purchasing tanpa `view_purchase_price`), `terbatas_divisi` (Warehouse 1 divisi).
- Endpoint: seluruh Pull (MRO→RO, RO→PO, PO→DO, PO→DO per supplier, MRO→MI, price-insight, price-history) + Dashboard,
  Control Center, daftar MRO/RO/PO/DO/MI (hal.1, dan hal.2 sort `no` untuk user divisi), Invoice Vendor, ringkasan Invoice,
  **Tagihan DO** (`vendor-invoices/do-billing`), Supplier DP, Register PO.

### 13.3 Riwayat yang tetap dicatat (tidak dihapus)
- Run `bf3` (harness lama, urutan tidak seimbang): **FAIL 5/29** — Pull terburuk 1,558, non-Pull 1,131. Memicu stabilisasi
  harness (ABBA + pemanasan konsisten + sampel gabungan) dan perbaikan N+1 Pull (batch `alloc_out_many`, batch UoM, matcher).
- Run `bx1` (harness ABBA): PASS 0/29 — tetapi **belum** mencakup daftar ber-halaman user terbatas divisi.
- Benchmark daftar user terbatas divisi berikutnya menemukan regresi P7 yang tidak stabil (contoh MRO 1,57/1,39; RO 1,80/1,61;
  PO 1,26/1,20; DO 1,11/1,07). Akar masalahnya di §13.4.

### 13.4 Akar regresi daftar user terbatas divisi & perbaikan
Profil (`txn_list_paging_layer.listing` → `source_rows` → filter cakupan `access_control_layer`) dan perbandingan per jalur
(backend P7 identik, hanya beda jalur) menunjukkan:
1. Jalur lengkap P7 memuat **seluruh** dokumen (tanpa batas 1.000, demi total benar) lalu memperkaya semuanya sebelum filter
   cakupan membuang dokumen divisi lain → kerja ekstra dibanding `main` yang hanya memuat 1.000 terbaru.
   **Perbaikan:** pra-saring cakupan (`scope_prefilter`) di query daftar paling dalam: dokumen yang **pasti** tidak terlihat
   (division_id tersimpan di luar divisi user **dan** bukan penugasan approver) tidak dimuat/diperkaya. Dokumen lain (termasuk
   division_id kosong/aneh) tetap melewati filter cakupan existing apa adanya → hasil & urutan identik.
2. Jalur cepat ber-halaman untuk user divisi (`visible_doc_ids` + pipeline halaman) di RO/PO/DO/MI harus memperkaya **seluruh**
   kandidat demi `trace_division_ids`, lalu memperkaya lagi baris halaman → kerja ganda. Diukur (P7 default vs jalur cepat
   semua modul, ABBA): RO 1,21/1,25, PO 1,57/1,20, DO 1,36/1,59, MI 1,48/1,35 (lebih lambat). Untuk MRO jalur cepat tetap
   lebih murah (0,68x `main`). **Perbaikan:** `SCOPED_FAST = {"mro"}` (konstanta, bukan flag eksperimen); RO/PO/DO/MI memakai
   jalur lengkap + pra-saring. `P7_SCOPED_FAST=0` / `P7_SCOPE_PREFILTER=0` hanya untuk backend referensi uji ekuivalensi.
- `visible_doc_ids` = versi batch `require_doc` (semantik per dokumen identik: divisi + jejak divisi + gudang, atau penugasan
  approver). Filter cakupan daftar existing tetap diterapkan pada baris halaman.
- Tidak ada perubahan pada tenant isolation, permission, redaksi harga, approval, MWA, HPP, valuation, stock ledger.

### 13.5 Hasil benchmark final (`docs/perf/p7-final-bench-2026-10-12.json`, 3 run × ABBA, ms)

| Persona | Endpoint | Jenis | n/backend | main p50 / p95 | P7 p50 / p95 | Rasio p50 / p95 | Query main → P7 | Gate |
|---|---|---|---:|---|---|---|---|---|
| global | `pull/mro-for-ro` | Pull | 27 | 1065.4 / 1127.2 | 133.0 / 163.3 | 0.125 / 0.145 | 4691 → 14 | PASS |
| global | `pull/ro-for-po` | Pull | 27 | 1502.0 / 1558.5 | 502.2 / 528.4 | 0.334 / 0.339 | 6569 → 1428 | PASS |
| global | `pull/po-for-do` | Pull | 27 | 645.8 / 688.5 | 205.4 / 240.4 | 0.318 / 0.349 | 2206 → 27 | PASS |
| global | `pull/mro-for-mi` | Pull | 27 | 1813.2 / 1927.2 | 309.9 / 343.8 | 0.171 / 0.178 | 8227 → 1576 | PASS |
| global | `pull/po-for-do?supplier_id=<id>` | Pull | 27 | 228.1 / 267.1 | 84.9 / 117.3 | 0.372 / 0.439 | 750 → 27 | PASS |
| global | `pull/ro-for-po/price-insight?ro_line_id=<id>&date=2026-10-12` | Pull | 450 | 28.0 / 29.8 | 26.6 / 28.1 | 0.952 / 0.944 | 19 → 19 | PASS |
| global | `pull/ro-for-po/price-history?ro_line_id=<id>&supplier_id=<id>&limit=10` | Pull | 450 | 25.9 / 27.4 | 24.4 / 25.8 | 0.94 / 0.944 | 11 → 11 | PASS |
| global | `dashboard` | non-Pull | 27 | 164.2 / 196.0 | 108.9 / 120.3 | 0.663 / 0.614 | 396 → 22 | PASS |
| global | `dashboard/control-center` | non-Pull | 27 | 1172.8 / 1207.8 | 990.7 / 1036.6 | 0.845 / 0.858 | 78 → 85 | PASS |
| global | `mro?page=1&page_size=25` | non-Pull | 27 | 236.4 / 270.1 | 59.5 / 80.2 | 0.252 / 0.297 | 23 → 24 | PASS |
| global | `ro?page=1&page_size=25` | non-Pull | 27 | 145.6 / 183.6 | 53.7 / 55.6 | 0.369 / 0.303 | 17 → 18 | PASS |
| global | `po?page=1&page_size=25` | non-Pull | 27 | 255.4 / 291.0 | 85.3 / 117.7 | 0.334 / 0.405 | 23 → 24 | PASS |
| global | `do?page=1&page_size=25` | non-Pull | 27 | 195.3 / 232.9 | 51.3 / 53.1 | 0.263 / 0.228 | 20 → 21 | PASS |
| global | `mi?page=1&page_size=25` | non-Pull | 450 | 55.5 / 88.1 | 23.9 / 25.7 | 0.43 / 0.291 | 16 → 17 | PASS |
| global | `vendor-invoices?page=1&page_size=25` | non-Pull | 27 | 275.1 / 285.8 | 246.3 / 257.4 | 0.895 / 0.901 | 20 → 20 | PASS |
| global | `supplier-dp?page=1&page_size=25` | non-Pull | 450 | 28.2 / 29.0 | 25.9 / 26.9 | 0.919 / 0.927 | 5 → 5 | PASS |
| global | `report-center/register-po?page=1&page_size=50` | non-Pull | 27 | 371.7 / 379.8 | 317.1 / 326.1 | 0.853 / 0.859 | 24 → 24 | PASS |
| global | `vendor-invoices/do-billing?page=1&page_size=25` | non-Pull | 27 | 325.8 / 333.3 | 329.3 / 344.5 | 1.011 / 1.033 | 22 → 22 | PASS |
| global | `vendor-invoices/summary` | non-Pull | 27 | 565.6 / 593.7 | 481.5 / 510.6 | 0.851 / 0.86 | 32 → 32 | PASS |
| tanpa_harga | `pull/mro-for-ro` | Pull | 27 | 1053.9 / 1111.7 | 133.1 / 161.7 | 0.126 / 0.145 | 4691 → 14 | PASS |
| tanpa_harga | `pull/ro-for-po` | Pull | 27 | 1503.7 / 1568.2 | 496.9 / 535.3 | 0.33 / 0.341 | 6569 → 1428 | PASS |
| tanpa_harga | `pull/po-for-do` | Pull | 27 | 646.3 / 690.7 | 207.3 / 239.8 | 0.321 / 0.347 | 2206 → 27 | PASS |
| tanpa_harga | `pull/mro-for-mi` | Pull | 27 | 1832.4 / 1885.3 | 308.8 / 344.3 | 0.169 / 0.183 | 8227 → 1576 | PASS |
| tanpa_harga | `pull/po-for-do?supplier_id=<id>` | Pull | 27 | 233.1 / 286.5 | 84.0 / 86.0 | 0.361 / 0.3 | 750 → 27 | PASS |
| tanpa_harga | `pull/ro-for-po/price-insight?ro_line_id=<id>&date=2026-10-12` | Pull | 450 | 7.8 / 8.6 | 7.7 / 8.6 | 0.994 / 0.997 | 15 → 15 | PASS |
| tanpa_harga | `pull/ro-for-po/price-history?ro_line_id=<id>&supplier_id=<id>&limit=10` | Pull | 450 | 5.4 / 6.0 | 5.2 / 5.7 | 0.948 / 0.95 | 5 → 5 | PASS |
| terbatas_divisi | `pull/mro-for-ro` | Pull | 27 | 1062.3 / 1106.1 | 133.0 / 165.7 | 0.125 / 0.15 | 4691 → 14 | PASS |
| terbatas_divisi | `pull/ro-for-po` | Pull | 27 | 1189.5 / 1244.5 | 191.9 / 225.1 | 0.161 / 0.181 | 5160 → 19 | PASS |
| terbatas_divisi | `pull/po-for-do` | Pull | 27 | 1389.2 / 2868.9 | 234.8 / 309.1 | 0.169 / 0.108 | 5795 → 40 | PASS |
| terbatas_divisi | `pull/mro-for-mi` | Pull | 27 | 2346.0 / 3922.3 | 328.0 / 360.1 | 0.14 / 0.092 | 10568 → 1580 | PASS |
| terbatas_divisi | `pull/po-for-do?supplier_id=<id>` | Pull | 27 | 478.1 / 766.9 | 93.8 / 118.7 | 0.196 / 0.155 | 1947 → 40 | PASS |
| terbatas_divisi | `dashboard` | non-Pull | 27 | 1086.8 / 1117.4 | 812.0 / 854.9 | 0.747 / 0.765 | 1063 → 64 | PASS |
| terbatas_divisi | `mro?page=1&page_size=25` | non-Pull | 27 | 182.2 / 219.6 | 125.2 / 132.0 | 0.687 / 0.601 | 25 → 31 | PASS |
| terbatas_divisi | `ro?page=1&page_size=25` | non-Pull | 27 | 113.0 / 146.7 | 115.7 / 146.8 | 1.024 / 1.001 | 19 → 20 | PASS |
| terbatas_divisi | `po?page=1&page_size=25` | non-Pull | 27 | 177.9 / 215.1 | 190.6 / 223.9 | 1.071 / 1.041 | 25 → 26 | PASS |
| terbatas_divisi | `do?page=1&page_size=25` | non-Pull | 27 | 129.0 / 164.1 | 129.8 / 163.2 | 1.006 / 0.995 | 20 → 20 | PASS |
| terbatas_divisi | `mi?page=1&page_size=25` | non-Pull | 450 | 56.5 / 89.1 | 34.7 / 37.2 | 0.614 / 0.418 | 16 → 16 | PASS |
| terbatas_divisi | `mro?page=2&page_size=50&sort=no&dir=asc` | non-Pull | 27 | 186.1 / 220.9 | 137.5 / 158.3 | 0.739 / 0.717 | 25 → 31 | PASS |

**Ringkasan:** Pull terburuk **0,997** (gate ≤ 1,0), non-Pull terburuk **1,071** (gate ≤ 1,10), **FAIL 0/38**. Status HTTP
identik di semua baris (37× 200, 1× 403 = price-history untuk user tanpa izin harga, sama di `main`).

Margin tipis yang dilaporkan transparan:
- `tanpa_harga` price-insight 0,994 / 0,997 (±7,8 ms; query sama 15 → 15). Per-run p95 run-1 = 1,034. Diverifikasi ulang
  terpisah 3 × 800 putaran ABBA: p50 0,987–0,989, p95 0,950–0,992 (selalu ≤ 1). price-history `tanpa_harga` 0,940–0,964.
- Regresi non-Pull ≤ 10% yang repeatable: `terbatas_divisi` PO hal.1 **+7,1% p50 / +4,1% p95** (per run 1,046 / 1,073 / 1,093;
  ±13 ms absolut, 191 vs 178 ms), RO hal.1 +2,4% / +0,1% (±3 ms), Tagihan DO global +1,1% / +3,3% (±3–11 ms). Penyebab: P7
  menghitung total dari **seluruh** dokumen (main hanya 1.000 terbaru) — biaya kebenaran total. Tanpa timeout, tanpa error,
  tanpa dampak UX material (< 15 ms), hasil fungsional/security identik (parity §13.6). Penyebab paling mungkin (bukan diukur per fungsi): P7 memproses seluruh dokumen dalam cakupan (PO 1.404 > 1.000), bukan hanya 1.000 terbaru.
- Beda ukuran respons yang ditemukan dan diperiksa: Control Center hanya `timing_ms`/`generated_at`; `terbatas_divisi`
  `mro?page=2&sort=no&dir=asc` total 500 (main, dari 1.000 terbaru) vs 780 (P7, seluruh data) → isi halaman 2 urut `no`
  berbeda karena `main` hanya mengurutkan 1.000 dokumen terbaru (by design; kebenaran P7 dibuktikan paging completeness).

### 13.6 Quality Gates (berurutan, DB `*_itest` terisolasi)

| Gate | Hasil |
|---|---|
| Regresi `run_regression_itest.sh` | **40/40 file, 1.769/1.769 cek PASS** (termasuk `p7_adapter_equivalence` 13/13, `p7_alloc_out_many_equivalence` 8/8, `p7_matcher_equivalence` 5/5, `p7_list_paging` 10/10, `p7_export_jobs` 21/21, `p7_trace_batch` 9/9, `p7_lifecycle_scan` 4/4) |
| Integrity `run_integrity_tests_mariadb.sh` | **13/13 PASS** |
| Multiprocess RO (`run_ro_multiprocess_test.sh`) | **9/9 PASS** |
| Ekuivalensi pra-saring cakupan + jalur cepat (`p7_scope_prefilter_equivalence_test`, vs backend referensi tanpa pra-saring) | **166/166 PASS** (byte-per-byte, 2 persona × 5 daftar × variasi halaman/ukuran/sort/cari/periode/tahap) |
| Paging completeness (`p7_paging_completeness_test`, 3 persona) | **108/108 PASS**: total == hitungan DB seluruh dataset, tanpa hilang/duplikat lintas halaman, sort monoton, filter periode, ukuran 25/50/100, cakupan role/divisi |
| Parity `main` vs P7 final, 3 persona | **327/336 identik**; status beda 0; 9 beda hanya `$.total` paging (by design, cap 1.000); beda tak terjelaskan 0. File `docs/perf/p7-final-parity-2026-10-12.json` |
| Frontend test (`node src/**/*.test.mjs`) | P7 **21/21 file PASS**, `main` **20/20 file PASS** (lihat catatan axios) |
| Frontend build (`CI=true yarn build`, sama dengan Dockerfile) | **Compiled successfully**, exit 0 |
| Browser UAT + `testing_agent_v3` (preview sandbox `proc_sandbox`) | iteration_5: frontend 100%, satu temuan backend → diverifikasi **bukan bug** (halaman di luar rentang di-clamp ke halaman terakhir, perilaku `main` yang sama; skrip UAT memperbaikinya). iteration_6: backend 19/19, frontend 100%, **0 open findings** |
| UAT alur tulis (API, sandbox) | RO dari MRO (outstanding 5 → 3, RO tampil teratas hal.1), DO dari PO (outstanding 2 → 1, DO teratas hal.1) |
| Secret scan + audit Git | Tidak ada kredensial/token/URL koneksi di diff & file baru (satu-satunya kecocokan = regex sanitasi di `perf_p7_report.py`); artefak `/root/perf` tidak di-commit; skrip UAT berisi kredensial sandbox tidak di-commit |

**Catatan frontend axios (`ERR_MODULE_NOT_FOUND`):** akar masalah = worktree tanpa `node_modules` (dependency belum di-install),
bukan kode/lockfile. Diperbaiki di environment saja: `yarn install --frozen-lockfile` (Node 20.20.2, Yarn 1.22.22,
`axios` 1.18.0 sesuai `package.json`/`yarn.lock`, lockfile tidak berubah). Setelah itu `main` & P7 lulus tanpa test di-skip.
Tidak perlu perubahan dependency repository.

**Tidak dijalankan / keterbatasan:** Ruff tidak tersedia di lingkungan; profiler `py-spy` ditolak izin (dipakai cProfile in-process).
Hasil benchmark berlaku untuk dataset `proc_perf_itest` (MRO 1.560, RO 1.560, PO 1.404, DO 1.248, MI 416) pada mesin ini.
