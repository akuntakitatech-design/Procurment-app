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
| Hasil mentah | `docs/perf/p7-before-main*.json`, `docs/perf/p7-after.json`, `docs/perf/p7-parity.json` |
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

Lihat `docs/perf/p7-parity.json` (diisi oleh `scripts/perf_p7_parity.py`; user global + user terbatas 1 divisi tanpa
`view_purchase_price`). Ringkasan di §8.1.

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
