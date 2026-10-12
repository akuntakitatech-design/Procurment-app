# Inventory Valuation Hardening — Plan (baseline `aab5ed4`)

> **Update konteks (Stock Opname Hardening — PT REAL)**
> - Basis kerja: `main` merge PR #55 (`b63de0e`), branch aktif: `feature/stock-opname-hardening`.
> - Keputusan user yang mengikat:
>   - **1A**: maksimal **1 Stock Opname aktif per gudang** (Counting/Review/Waiting Approval), validasi backend concurrency-safe.
>   - **2A**: Approval/Reject memakai permission existing **`opname.post` / `post_stock_opname`**; **reject wajib alasan** dan kembali ke proses perbaikan.
>   - **3A**: **Freeze** wajib memblokir **SELURUH** mutasi stok server-side pada gudang Freeze sampai posting sukses atau pembatalan sah.
>   - Opsi 1: jalur **direct-write** yang mengubah stok/ledger/valuasi juga harus diblokir saat Freeze; proses **read-only** tetap boleh.
> - Ketentuan delivery: 1 PR ke `main`, **tanpa merge/deploy/reset DB production**. Token GitHub diminta **hanya saat push** dan tidak disimpan/ditampilkan.

## 1) Objectives
- Menjaga moving weighted average valuation tetap **end-to-end aman + auditable** dan **tidak merusak perilaku modul lain**.
- Menyelesaikan hardening **Stock Opname 1 dokumen = 1 gudang** (bukan multi-gudang per item) dengan workflow lengkap:
  - Counting → Review → Waiting Approval → Posted
  - Return/Reject/Cancel beralasan, audit trail
  - Posting **atomic**, idempotent/retry-safe, reversal/correction aman
  - Mode **Freeze** dan **Live** (kronologis + penanda “perlu hitung ulang”)
- Menegakkan **security harga**:
  - Redaksi server-side untuk user tanpa `view_purchase_price` pada API/detail/list/print/export-import/report
  - Audit log & error tidak membocorkan nilai harga
- Memenuhi seluruh quality gates:
  - Backend tests + integrity suite full (DB terisolasi)
  - Frontend tests + `CI=true yarn build`
  - Browser UAT + `testing_agent_v3` sampai **0 temuan**
  - `git diff --check`, secret scan, scope audit

## 2) Implementation Steps

### Phase 1 — Core POC (isolation) for the valuation engine hard parts
> **Status:** COMPLETED (sebelum konteks Stock Opname hardening ini). Tidak diulang.

### Phase 2 — V1 App development (checkpoint-driven hardening)

#### Checkpoint 1 — Concurrency / Atomicity (commit)
> **Status:** COMPLETED (baseline engine + safeguards). Tidak diulang.

#### Checkpoint 2 — Reversal / Cancellation (commit)
> **Status:** COMPLETED (engine reversal `reverse_document_valuation` sudah ada). Ditambah wrapper/guard untuk Freeze (lihat Checkpoint 4).

#### Checkpoint 3 — Transfer valuation (commit)
> **Status:** COMPLETED. Regresi `transfer_multi_warehouse_test.py` perlu dijalankan dengan `STORAGE_DRIVER=local` sesuai asumsi test (sudah dilakukan).

#### Checkpoint 4 — Adjustment + Stock Opname valuation (commit)
> **Status:** **IN PROGRESS → mayoritas selesai (agent-tested)**

**Implementasi Stock Opname Hardening (sudah dilakukan):**
- Backend: `backend/stock_opname_workflow_layer.py` + terdaftar di `backend/production_bootstrap.py`.
  - Workflow server-side (WF v2): Counting → Review → Waiting Approval → Posted.
  - Return/Reject/Cancel: alasan wajib, audit trail.
  - **Lock 1 gudang 1 opname aktif** via `opname_locks` PK deterministik, aman concurrency.
  - Mode **Freeze**:
    - Freeze guard di `MariaCollection` untuk `item_warehouse` (insert/update/replace/delete/find_one_and_delete/bulk_write)
    - Resolusi warehouse bila filter tidak punya `warehouse_id` (mis. delete master)
    - Mengizinkan perubahan **min/max** tanpa mengubah saldo.
    - Guard valuation replay: insert `valuation_replays` status `applying` precheck gudang sebelum ada perubahan.
    - Precheck import Excel yang bisa menyentuh saldo: `stock_limits` bila ada `current_stock` dan dataset `opening_inventory`.
    - Freeze race safety: transaksi yang lolos tepat saat snapshot freeze → baris ditandai `needs_recount`.
  - Mode **Live**:
    - Mutasi yang diinput setelah hitung namun bertanggal <= waktu hitung → tandai `needs_recount`, submit/post diblokir.
  - Posting:
    - Atomic posting, retry-safe dengan `source_key` suffix attempt.
    - Pemulihan `status=Posting` basi / `Gagal Posting` → reversal cleanup lalu retry.
    - Koreksi Posted via reversal + repost, aman terhadap stok negatif.
  - Redaksi harga server-side pada detail/lines/print-data; template Excel tanpa harga; audit log tidak menyimpan nilai harga.
  - Excel import/export: template & import preview/commit **mengupdate dokumen yang sama**, tidak posting otomatis.
  - Attachment draft module `opname` terdaftar menggunakan infrastruktur draft existing.

- Frontend (sudah dibuat + tested):
  - `frontend/src/pages/Opname.jsx` (list + create + draft attachment)
  - `frontend/src/components/OpnameWorkspace.jsx` (workspace detail: counting, review/submit/approve/reject/return/cancel, import, template, print 2 format, pagination/filter/search, history)
  - `frontend/src/lib/opnameLines.js`, `frontend/src/lib/opnamePrint.js` (logo perusahaan)
  - Test: `frontend/src/lib/opnameLines.test.mjs` (21 test)
  - Parameterisasi reusable attachment draft: `AdjustmentDraftAttachments.jsx` mendukung `entity/category`.

- Test baru (backend):
  - `backend/tests/stock_opname_workflow_test.py` **74/74 passed**
  - `backend/tests/stock_opname_freeze_coverage_test.py` **37/37 passed** (DO, MI, Loan, Return, Transfer, Adjustment multi-gudang, edit/delete reversal semua modul stok, import Excel, opening valuation, master delete tunggal/massal, replay dry-run, anti-pemalsuan pengecualian)
  - `backend/tests/stock_opname_uat_fixture_test.py` **36/36 passed**
  - `backend/tests/opening_correction_test.py` **83/83 passed** termasuk verifikasi replay apply ditolak saat Freeze tanpa partial.

- Penyesuaian test lama agar sesuai aturan bisnis baru (bukan melemahkan kontrol):
  - `stock_opname_integrity_test.py`: 1 gudang 1 opname aktif; Live stale → wajib hitung ulang; submit sebelum post; alasan selisih.
  - `full_e2e_integrity_test.py`: alasan selisih saat count.
  - `transaction_input_validation_test.py`: hitung semua baris + submit sebelum post.
  - `valuation_hardening_test.py`: `cost_reason` + workflow.
  - `loan_multi_warehouse_test.py`: modul draft yang tidak terdaftar tetap ditolak (pakai `invoice`).

**Regresi yang sudah PASS (agent-tested):**
- Backend:
  - `adjustment_multi_warehouse_test.py` 83/83
  - `loan_multi_warehouse_test.py` 63/63
  - `transfer_multi_warehouse_test.py` 76/76 (dengan `STORAGE_DRIVER=local`, lalu env dipulihkan ke `s3`)
  - `transfer_shared_guard_regression_test.py` 16/16
  - `loan_return_attachment_legacy_test.py` 102/102
  - `valuation_hardening_test.py` 40/40
  - `opening_inventory_valuation_test.py` 44/44
  - `receipt_control_test.py` (DO) 41/41
  - `transaction_input_validation_test.py` (DO/MI) 66/66
  - `inventory_value_asof_test.py` 31/31
  - `stock_summary_parity_test.py` 41/41
  - `master_item_stock_test.py` 55/55
  - `stock_info_test.py` 16/16
- Frontend:
  - Seluruh `frontend/**/*.test.mjs` **PASS** (17 file)
  - `CI=true yarn build` **PASS**

#### Checkpoint 5 — Loan valuation (commit)
> **Status:** COMPLETED (baseline). Regresi lulus; Freeze guard juga meng-cover jalur loan/return.

#### Checkpoint 6 — Backdated posting safety (commit)
> **Status:** COMPLETED (baseline) + diperluas di Stock Opname Live melalui mekanisme `needs_recount` untuk transaksi “diinput belakangan namun tanggal <= waktu hitung”.

#### Checkpoint 7 — Opening Inventory Valuation UI (commit)
> **Status:** COMPLETED (baseline fitur existing). Tambahan hardening: saat ada gudang Freeze, jalur yang menulis pool/valuasi diblokir; dry-run replay tetap boleh.

#### Checkpoint 8 — Reconciliation + diagnostics + full regression (final commit)
> **Status:** **COMPLETED (agent-tested) — seluruh syarat finalisasi user PASS, 0 temuan terbuka -> Tahap 7 dieksekusi:**
> 1 commit (squash, sesuai pilihan user) di `feature/stock-opname-hardening` -> push -> tepat 1 PR ke `main`. **Tanpa merge/deploy.** Production tidak disentuh.

(… bagian P0–P6 tetap sama seperti versi sebelumnya; P7 ditambahkan/diupdate di bawah.)

---

## P7 — Performance Optimization Procurement & Warehouse (Status: **IN PROGRESS**; branch `feature/p7-performance` dari `main` merge PR #67 `6e27d1d`; target tepat **1 PR** ke `main`, **OPEN** tanpa merge/deploy)

### Konteks & keputusan user (mengikat)
- Pendekatan: **measurement-led** (profiling + benchmark before/after), bukan “percepatan” yang mengubah hasil.
- Benchmark DB: **hanya DB terisolasi** (utama: `proc_perf_itest`; untuk suite: `proc_itest`). **Jangan pernah menyentuh DB production** atau `proc_sandbox`.
- Data benchmark target: “±20.000+ per modul”. **Beberapa modul saat ini di bawah 20k dan cukup diungkapkan** (tidak perlu ditambah):
  - DO 16k, MI 10,6k, Transfer 8k, Adjustment 11k, Invoice 16k, Loan 5k, Kontrak 2k.
- Invariants wajib: **MWA/HPP/valuation/stock ledger/aturan transaksi/approval/permission/tenant isolation/divisi-gudang scope/redaksi harga** tidak berubah.
- Tidak boleh ada **silent truncation** untuk performa. Excel limit **100.000 rows**, PDF **5.000 rows** tetap eksplisit (422 bila lewat).
- Penambahan index **boleh**, hanya DDL index, melalui mekanisme schema yang ada, diuji di DB itest/perf saja, dan didokumentasikan + rollback plan.
- Export:
  - Export kecil tetap sinkron (UX tidak berubah).
  - Export besar menjadi **background job** dengan status → notifikasi selesai → tombol Download.
  - Wajib: keamanan download (tenant & user owner), retry/failure handling, cleanup file sementara.
- GitHub: push/PR hanya memakai **token baru via platform Secret/Save to GitHub** (tidak pernah token lama). 1 PR P7 ke `main`, **jangan merge/deploy**.
- Ambiguitas instruksi terakhir user “langsung pr ke db production” ditafsirkan sebagai **PR ke branch `main` (repo)**, **bukan** menyentuh DB production.

### Temuan baseline (ringkas; angka awal, bukan baseline final)
- Bottleneck utama yang disetujui user:
  1) Pagination belum benar-benar server-side (muat+enrich ~1000 dulu, halaman 1 ≈ halaman 40).
  2) Adapter MariaDB sering memuat doc JSON penuh lalu filter/sort di Python → full scan/filesort.
  3) N+1 query fanout: Dashboard ~2.021 query; Loan/Adjustment list ~1.013 query.
  4) Invoice/Tagihan DO memuat besar (hingga 100k) lalu filter di Python.
  5) Control Center/report agregasi di Python pada data besar.
  6) Export besar sinkron mempengaruhi concurrency.

> Catatan: baseline final wajib dipersist di `/app/docs/perf-p7.md` sebelum final PR, dan harus memuat protokol run, dataset, parameter, p50/p95 sebelum/sesudah, serta error/timeout.

### Status implementasi saat ini (worktree belum commit) — update sesi lanjutan
- Keputusan user terbaru: "PR ke db production" = **1 PR ke `main`, OPEN, tanpa merge/deploy/production**. PR tetap dibuat walau
  sebagian target belum tercapai **asal** semua gate fungsional/keamanan PASS + testing_agent 0 temuan + laporan jujur.
  Token GitHub: user akan mengirim via chat saat PR, lalu merotasinya (jangan simpan/echo).
- Prioritas user: search/filter MRO/RO/PO → Invoice & Tagihan DO → N+1 Loan/Adjustment → Dashboard/CC → Background export → gates.
- Audit diff (sesi ini): seluruh perubahan = jalur BACA (list/dashboard/report/export). Tidak ada perubahan MWA/HPP/valuation/
  ledger/posting/approval. Adapter write path tidak berubah (hanya invalidasi memo).
- Baru sesi ini (agent-tested):
  - `mariadb_motor`: urutan dasar `ORDER BY created_at, pk` dihitung di Python bila SQL butuh filesort (`_py_order`,
    `_pk_pair_safe` — dibuktikan vs collation utf8mb4_unicode_ci nyata; fallback ORDER BY SQL); WHERE kosong/tenant saja tetap
    ORDER BY SQL (indeks berurutan). Memo baca per request GET (SQL+param identik; invalidasi setiap tulis/transaksi; ditutup akhir
    request; anggaran global 192 MB). `p7_adapter_equivalence_test` 12/12.
  - `txn_list_paging_layer._mro_lifecycle`: >2000 MRO → 1 scan alokasi bertipe (identik per kunci, semantik kolom generated).
    `p7_lifecycle_scan_test` 2/2 (menangkap 1 beda semantik array → diperbaiki).
  - `vendor_invoice_layer.traces`: `enrich_list(items=False)` (hanya no/date/trace_* dipakai).
  - `export_jobs`: heartbeat + deteksi stale multi-proses, idempoten, tulis atomik (.part), cleanup berkala, izin export & harga
    diperiksa ulang saat unduh, retry hanya untuk kegagalan sementara (maks 3), `data_as_of`. `p7_export_jobs_test` 21/21.
  - Frontend `*.test.mjs` 23/23 file PASS.
- Temuan lingkungan: buffer pool MariaDB 256 MB < working set (allocations ±770 MB) → query `IN` besar = full scan 12–13 dtk
  (I/O bound; projection tidak membantu). Rekomendasi (butuh izin user, config server): naikkan `innodb_buffer_pool_size`.
  Insiden: kontainer restart 1x saat profiling in-process invoice (memori) → MariaDB FATAL saat boot (start manual), backend
  preview di-restart. Skrip jejak kini punya pengaman RSS.
- Index: tidak ada index baru (EXPLAIN: IN kecil sudah pakai index; IN besar → full scan apa pun indexnya).
- Gates sesi ini: regresi backend 38 file 1756/1756 (EXIT 0); integrity 13/13 file (EXIT 0, 308 dtk); frontend 23/23 file;
  `CI=true yarn build` PASS (setelah perbaikan lint `Mro.jsx`); testing_agent_v3 iteration_35: 0 bug P7 (temuan "harga terlihat
  staff.gudang" = kebocoran PRE-EXISTING di `main` — field diskon/DPP/UoM; dilaporkan ke user, PR ditahan sampai keputusan).
- Benchmark final AFTER (`docs/perf/p7-after.json`) + dokumen `docs/perf-p7.md` ditulis; parity base vs P7 berjalan
  (`docs/perf/p7-parity.json`, user global + user terbatas).

### Test infra & credential test DB (P7)
- `backend/scripts/itest_url.py` membangun DSN itest dari host `backend/.env` + kredensial test dari **file lokal di luar repo** `/root/.procureflow_itest.env` (chmod 600).
- User DB test: `itest@127.0.0.1` memiliki grant untuk schema:
  - `proc_itest` (suite), `proc_perf_itest`, `proc_perf1_itest` (benchmark).
- Tujuan: mencegah salah arah ke `proc_sandbox`/production dan menjaga kredensial tidak masuk repo.

### Urutan kerja P7 (keputusan user; progress ditandai)

#### Step 0 — Safety & reproducibility (WIP)
- [ ] Re-run benchmark baseline terkontrol (warmup/repeat), simpan raw JSON dan ringkasan ke `/app/docs/perf-p7.md`.
- [ ] Pastikan semua benchmark/seed memakai `*_itest` schema guard; jangan menulis ke `proc_itest` kecuali runner suite.

#### Step 1 — Fix/verify pagination parity test (**DONE**)
- [x] Perbaiki dan jalankan `backend/tests/p7_list_paging_test.py` pada DB `proc_itest` terisolasi.
  - Hasil: **10/10 passed** (via runner `scripts/run_regression_itest.sh` dengan `ONLY=p7_list_paging_test.py`).
- Catatan penting:
  - Perubahan pagination P7 harus tetap:
    - total = seluruh hasil filter (tanpa cap 1.000)
    - sorting stabil
    - tenant isolation & scope divisi/gudang aman
    - redaksi harga tidak bocor
    - tanpa `page` tetap respons array legacy (cap 1.000) untuk kompatibilitas.

#### Step 2 — Invoice Vendor & Tagihan DO: DB-side filter/sort/paging (NEXT)
- Pindahkan filter/pencarian/sort/pagination ke jalur query DB, **bukan** memuat semua lalu filter di Python.
- Wajib:
  - total hasil = seluruh hasil filter (bukan hanya halaman)
  - sorting stabil (tie-breaker id/pk)
  - tidak ada duplikasi invoice multi-DO karena JOIN
  - DP/pembayaran parsial/outstanding/aging identik
  - tenant/divisi/proyek scope & permission & redaksi harga diterapkan server-side
  - kompatibilitas kontrak API/format respons.
- Bukti:
  - parity before/after (hash/compare) + benchmark p50/p95.

#### Step 3 — Dashboard & Control Center: hilangkan N+1 + agregasi SQL (identik 100%)
- Profiling: identifikasi N+1 & query fanout (mis. Dashboard ~2.021 query).
- Strategi:
  - batch query / JOIN / agregasi SQL yang aman
  - hindari memuat seluruh dokumen ke Python hanya untuk SUM/COUNT/GROUP.
- Wajib: seluruh KPI/angka (stok, MWA, HPP, outstanding, laporan, permission) **100% identik** sebelum/sesudah.
- Bukti: parity + jumlah query turun + benchmark.

#### Step 4 — N+1 Loan/Adjustment & document enrichment
- Eliminasi query per-dokumen/per-baris pada list/detail enrichment.
- Gunakan batch lookup yang aman, tanpa mengubah field/structure response.
- Verifikasi khusus:
  - outstanding loan/return parsial
  - adjustment multi-gudang
  - scope gudang/divisi dan redaksi harga.

#### Step 5 — Indexes (allowed; DDL index-only; documented)
- Berbasis profiling (`EXPLAIN`), fokus: allocations, ledger (stock/valuation), sort tanggal per-tenant.
- Mekanisme:
  - lewat schema mechanism existing (tanpa reset/seed/alter data)
  - diuji hanya di DB `*_itest`
  - dokumentasi: SQL, dampak lock, benefit, rollback plan.

#### Step 6 — Export performance: small sync, large async background job
- Kriteria “large export” harus jelas & terdokumentasi (mis. perkiraan row/time threshold) agar small export tetap sinkron.
- Background export wajib:
  - status/progress endpoint
  - notifikasi selesai (minimal polling UI)
  - tombol Download
  - file sementara aman: akses hanya untuk owner (tenant + user), expiry & cleanup
  - handling failure/retry & idempotency
  - tetap gunakan batas Excel 100k / PDF 5k (422 bila lewat), **tanpa** potong diam-diam.
- Uji:
  - concurrent export
  - job failure + retry
  - keamanan download lintas tenant/user
  - cleanup file.

#### Step 7 — Dokumentasi + Quality Gates + Delivery (FINAL)
- [ ] `/app/docs/perf-p7.md` berisi:
  - dataset counts per modul
  - endpoint list + parameter
  - protokol benchmark (warmup/repeat, p50/p95)
  - before/after table + concurrency
  - catatan error/timeout + langkah mitigasi
  - daftar perubahan (file/fungsi) dan risiko tersisa.
- [ ] Jalankan Quality Gates **serial** (tidak paralel untuk suite shared):
  1) Backend regression penuh (`proc_itest`)
  2) Integrity suite full (`proc_itest`)
  3) Frontend tests (`*.test.mjs`)
  4) `CI=true yarn build`
  5) Browser UAT
  6) `testing_agent_v3` sampai **0 temuan terbuka**
  7) Secret scan (gitleaks) + known-value scan
  8) Git audit (`git diff --check`, review untracked, history).
- [ ] Setelah semua PASS:
  - commit perubahan P7
  - push branch `feature/p7-performance` memakai **fresh platform secret**
  - buat tepat **1 PR** ke `main`, biarkan **OPEN** (tanpa merge/deploy).

### Target performa (realistis; disetujui user)
- List (hal. 1/search/filter): p95 **≤ 1,5s**
- Detail: **< 100ms**
- Dashboard: **≤ 1,5s**
- Invoice & Tagihan DO: **≤ 3s**
- Report: **≤ 10–15s**
- Control Center: **≤ 15s**
- Export Excel 20k: **≤ 45s**
- 10 user concurrent: p95 **≤ 3s**, **0 error**

### Catatan kepatuhan (P7)
- Tidak menjalankan server langsung: gunakan supervisor untuk service utama.
- Tidak gunakan `npm` (frontend pakai `yarn`).
- Tidak ubah `frontend/.env` atau `backend/.env` (khususnya `REACT_APP_BACKEND_URL` / `MONGO_URL`).
- Endpoint tetap `/api`.
- Tidak ada pekerjaan infra/k8s/docker/CI/SSL.
- Tidak ada perubahan aturan bisnis transaksi/approval/MWA/HPP/valuation/stock ledger.

---

## 3) Next Actions
1. Finalisasi dokumen baseline P7 awal di `/app/docs/perf-p7.md` (angka existing masih berserakan di `docs/perf/`).
2. Mulai Step 2: optimasi Invoice & Tagihan DO dengan pembuktian parity + benchmark.
3. Pastikan semua perubahan P7 tetap optimization-only (tanpa perubahan bisnis), dan tiap langkah punya bukti before/after.

## 4) Success Criteria
- Semua invariants terpenuhi (angka & permission identik; tanpa kebocoran; tanpa silent truncation).
- Semua target performa P7 tercapai atau perbedaannya dijelaskan jujur dengan data.
- Semua Quality Gates PASS + `testing_agent_v3` 0 temuan.
- Delivery: tepat 1 PR P7 ke `main`, **OPEN**, tanpa merge/deploy; tidak menyentuh DB production.
