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

**Riwayat Git (transparansi):** commit lokal `7151fe0` (28 file) sempat terbuat oleh agent SEBELUM otorisasi Tahap 7 (tidak pernah
di-push; remote belum punya branch ini). Atas keputusan user, commit itu digabung (amend lokal, tanpa force push) bersama perubahan
retry deadlock menjadi SATU commit. Tidak ada `reset --hard`, `clean -fd`, force push, atau perubahan remote.

**Bug nyata ditemukan & diperbaiki (sesi final):** 2+ Approve & Post bersamaan -> InnoDB deadlock **1213** pada `SELECT … FOR UPDATE`
klaim CAS `ep_post` (`stock_opname_workflow_layer.py`) -> salah satu request **500**. Perbaikan (bukan engine MWA):
- `lock_conflict_errno()` + `retry_lock_conflict()` (modul `stock_opname_workflow_layer.py`): retry **hanya** `pymysql OperationalError`
  1213/1205; **maks. 3 percobaan** termasuk yang pertama (jeda 50/100 ms); habis -> **409**; error lain (1062, 2006, 1146, validasi
  bisnis, ValueError) langsung dilempar. Unit retry = SATU transaksi `find_one_and_update` (BEGIN; SELECT..FOR UPDATE; UPDATE; COMMIT);
  korban di-ROLLBACK oleh `_Tx.__aexit__` adapter sebelum retry.
- `cas_doc()` dipakai di 4 klaim status: transisi workflow, pemulihan posting basi, klaim posting, klaim koreksi Posted.
- Test permanen baru `backend/tests/stock_opname_cas_retry_test.py` **22/22** (deadlock ASLI InnoDB, 1213 setelah UPDATE -> rollback
  utuh + lock lepas, lock-wait timeout ASLI 1205 pulih & habis -> 409 tepat 3 percobaan, 6 klaim paralel x5 ronde tepat 1 pemenang),
  stabil 3x berturut-turut; M2–M4 di `stock_opname_workflow_test.py` (6 posting paralel: 1x200 + 5x409, 1 movement, 1 ledger valuasi,
  stok turun tepat 1). Didaftarkan di `scripts/run_regression_itest.sh` (19 suite).

**Quality Gates final (setelah perubahan terakhir, serial, `proc_itest`):**
| Gate | Hasil |
|---|---|
| Regresi backend `run_regression_itest.sh` | **19/19 PASS** (18 wajib + `stock_opname_cas_retry_test.py` 22/22); workflow 78/78, freeze 39/39, fixture 36/36, opening correction 83/83 |
| Full integrity `run_integrity_tests_mariadb.sh` | **13/13 PASS**, FAIL 0 |
| Frontend `*.test.mjs` | **17/17 PASS** |
| `CI=true yarn build` | **Compiled successfully** |
| `git diff --check` | bersih (exit 0) |
| MWA engine | `server.py`, `valuation_replay.py`, `mariadb_motor.py` **SHA-256 identik** dengan `origin/main` (diff 0 baris) |
| testing_agent_v3 `iteration_19.json` | **U1–U9 9/9**, 47/47 sub-skenario + 11/11 verifikasi independen + 8/8 browser, **0 open findings** |
| Harness independen main agent `opn_uat_9.py` | 47/47 (U6a: 1x200 + 1x409, tanpa 500) |

Catatan testing_agent: iterasi 14–18 tidak valid/tidak lengkap karena bug skrip tester (endpoint lampiran, header Excel baris 1,
`if resp:`, mode huruf besar, division_id hilang) — bukan bug aplikasi; iterasi 19 = laporan bersih yang dipakai.

**Tabel Direct-Write Freeze (bukti = run terbaru):** baseline `origin/main` TIDAK memiliki Freeze Guard (file layer baru).
Guard: route-level `patch_routes()`/`doc_level_whs()` (pra-cek seluruh gudang dokumen sebelum menulis), collection-level
`MariaCollection.*` wrapper `guard_whs()` pada `item_warehouse` (insert/update/replace/delete/find_one_and_update/bulk), `reverse_guarded`,
`import_master_guarded`, `valuation_replays` status `applying`; pengecualian sah hanya `POSTING_CTX` (posting Opname pemilik Freeze) & kompensasi.
| Jalur | File / fungsi | Test | Status |
|---|---|---|---|
| DO create/edit/delete | `doc_procurement.create_do`; `transaction_mutation_layer.transaction_edit/transaction_delete` | Z1, Z1b, Z1c; U3b:do | PASS |
| MI create/delete | `doc_procurement.create_mi`; `transaction_delete` | Z2, Z2b; U3b MI | PASS |
| Loan / Return create/edit/delete | `doc_warehouse.create_loan/return_loan`; `loan_return_mutation_layer.edit_return/delete_return` | Z3, Z3b, Z4, Z4b, Z4c; U3b loan | PASS |
| Transfer create (dari/ke) / edit / delete | `doc_warehouse.create_transfer`; `transaction_edit/delete` | Z7a, Z7b, Z7, Z8; B2, B3; U3b | PASS |
| Adjustment create (multi-gudang) / edit / delete | `doc_warehouse.create_adjustment`; `transaction_edit/delete` | Z5, Z6, Z6b; B1; S19; U3a | PASS |
| Pemalsuan payload / path modul `opname` | `patch_routes.guarded` | Z5b, Z5c | PASS |
| Set saldo langsung | `server.item_warehouse_set` | Z9; B4 | PASS |
| Opening Valuation | `doc_procurement.post_opening_valuation` | Z14 | PASS |
| Opening Correction (Tetapkan massal/individual) | `opening_correction_layer.opening_mass_apply` | opening_correction_test "Freeze: Tetapkan Massal/individual … tanpa partial" | PASS |
| Valuation Replay apply / dry-run | `opening_correction_layer.replay_apply` / `replay_dry_run` | "Apply revaluasi saat gudang terdampak Freeze -> 409"; Z16; U3d | PASS |
| Import Excel saldo / saldo awal / min-max | `excel_import_layer.import_excel -> _import_master` | Z11, Z13 (blok), Z12 (min/max diizinkan) | PASS |
| Hapus master tunggal / massal | `master_delete_guard_layer.delete_master_safe`; `master_action_layer.bulk_delete` | Z15, Z15b | PASS |
| Clear min/max (bukan mutasi stok) | `master_action_layer.clear_minmax` | Z10, Z15c (diizinkan, saldo tetap) | PASS |
| Stock Opname post / koreksi Posted | `stock_opname_workflow_layer.ep_post` / `ep_tx_put` (POSTING_CTX) | Z20, F1–F11, G1–G4, M1–M4 | PASS |
| Integritas global saat Freeze | — | Z17, Z18, Z19, Z21–Z25 | PASS |

**Secret scan final (gitleaks 8.21.2, `--redact`):** scope PR 29 file vs `origin/main` = 0; patch PR + untracked = 0; arsip
`/root/procurement-uat-evidence` = 0; known-value scan 282 file = 0 hit. Working tree 6 + history 3 (107 commit) = **temuan legacy
identik baseline** (`backend/.env` ignored & tidak pernah di-commit; 3 skrip/CI legacy tidak berubah vs `origin/main`) -> tiket terpisah.

**Kredensial sandbox:** 4 akun dirotasi (lama 401 / baru 200). 2 akun fixture UAT dirotasi ULANG di sesi final karena nilai sempat
tampil di output tool agent (redaksi gagal; tidak ada di repo/arsip) -> lama 401 / baru 200, file 0600.

**Bukti:** `/root/procurement-uat-evidence/final-20261009-f/` (gates, suites, deadlock, testing_agent, harness, rotation, secret_scan)
dan `/root/procurement-uat-evidence/iteration-8-10/`.

## 3) Next Actions
1. Review PR oleh user (tanpa merge/deploy oleh agent).
2. Tiket terpisah (di luar scope PR ini): remediasi 6 temuan gitleaks working tree + 3 temuan history (legacy);
   konsistensi zona waktu UTC/WIB tanggal default transaksi; lint F401/F841 test legacy.

## 4) Success Criteria
- Stock Opname memenuhi:
  - 1 dokumen = 1 gudang; 1 gudang = 1 opname aktif (Counting/Review/Waiting Approval) secara concurrency-safe.
  - Freeze memblokir semua mutasi stok (termasuk direct-write dan reversal) untuk gudang Freeze; gudang lain tetap bisa transaksi.
  - Live menjaga kronologi: mutasi “diinput belakangan namun tanggal <= hitung” menandai `needs_recount` dan membatasi submit/post.
  - Posting atomic, idempotent/retry-safe, tidak ada partial posting/ledger duplikat/valuasi inkonsisten.
  - Koreksi Posted via reversal aman; delete/reversal diblokir bila membuat stok negatif.
  - Redaksi harga server-side untuk user tanpa `view_purchase_price` (API/print/Excel/export/import/report) dan audit log aman.
- Semua suite/regresi + build lulus:
  - Full integrity suite (single instance, DB terisolasi) PASS.
  - Frontend tests PASS + `CI=true yarn build` PASS.
  - Browser UAT + `testing_agent_v3` 0 temuan.
- Delivery:
  - 1 PR ke `main` dari `feature/stock-opname-hardening`.
  - Tidak ada merge/deploy/reset DB production.

## PO — Informasi Harga & Supplier saat Tarik RO (Status: COMPLETED, lokal, branch feature/po-ro-price-insight)
- Kolom "Harga" + tombol "Lihat Harga" di popup Tarik RO; popup "Informasi Harga & Supplier" (lazy, per baris RO).
- Backend read-only: GET /api/pull/ro-for-po/price-insight, GET /api/pull/ro-for-po/price-history (maks 5).
- Kontrak: resolver Kontrak Harga Vendor existing (batch `resolve_vendor_item_prices`, aturan identik `resolve_price`).
- Harga Beli Terakhir: PO Approved/Partially Received/Fully Received (tidak cancelled), net setelah diskon item, tanpa PPN, per satuan dasar.
- Pilih Supplier hanya mengubah supplier PO di form (belum simpan); Supplier Utama & kontrak tidak berubah.
- Test: tests/po_price_insight_test.py 25/25; regresi PO/RO/receipt/invoice + multi-proses lulus; CI=true yarn build sukses.

## Reporting & Export — Procurement & Warehouse PT REAL (branch `feature/reporting-export`, base `main` 74747eb)
Blueprint disetujui user (5 kelompok: Persediaan & Nilai · Procurement · Warehouse · SPK & Kontrak · Invoice/Hutang).
Keputusan: PDF server-side `reportlab` (cetak dokumen existing tetap); cut-off = tanggal bisnis WIB (Asia/Jakarta);
batas export Excel 100.000 / PDF 5.000 baris (ditolak tegas 422, tidak dipotong); aging: Belum JT/JT hari ini, 1–30, 31–60,
61–90, >90 (pembayaran parsial + DP teralokasi); engine/formula MWA, valuation, ledger, transaksi TIDAK diubah.

### P0 — Reporting Foundation (Status: COMPLETED — Quality Gates PASS; PR P0 ke `main` lalu STOP menunggu review, tanpa merge/deploy)
1. **Keamanan valuasi (pekerjaan pertama):** `valuation_report_scope_layer.py` mengganti `/api/reports/valuation-summary` &
   `/valuation-ledger` (bentuk respon sama): scope divisi + penugasan gudang (`stock_summary.allowed/assigned_warehouses/
   wh_in_scope`), `warehouse_id` di luar cakupan → 403, tanpa batas 5000, filter tanggal ledger = tanggal efektif WIB
   (`txn_at`, fallback `at`; field baru `txn_date`). Sebelumnya: hanya izin harga + tenant (nilai lintas divisi terbuka).
2. **Registry + builder bersama:** `reporting/registry.py` (ReportSpec/Column/Filter, 5 GROUPS), `reporting/report_center.py`
   (`run()` satu alur: validasi filter → builder seluruh baris → pencarian → proyeksi kolom → total seluruh baris → halaman/export).
   Route: `GET /api/report-center/catalog`, `/{key}` (page/page_size ≤ 500), `/{key}/export.xlsx`, `/{key}/export.pdf`.
3. **Export server-side:** `reporting/exporters.py` — Excel openpyxl write-only (kop, filter, pencetak, header beku, autofilter,
   TOTAL, sheet Parameter); PDF reportlab (A4/A3 landscape otomatis, header berulang, TOTAL, "Hal x/y", metadata rows).
4. **Permission/redaksi:** kolom `price=True` dibuang server-side (JSON, Excel, PDF, totals) tanpa `view_purchase_price`;
   export butuh izin `export`; setiap export dicatat di audit (`entity=report`, format, jumlah baris, filter).
5. **UI Pusat Laporan:** `/report-center/:key` (`pages/ReportCenter.jsx`, `lib/reportCenter.js`), menu Laporan → "Pusat Laporan";
   filter tanggal `input type=date` (tanpa konversi UTC), kolom/total dari server, drill-down ke dokumen MRO; `/reports` tetap.
6. **Migrasi MRO Traceability (BUKAN perbaikan keamanan):** pembatasan divisi MRO Traceability SUDAH diterapkan sistem
   existing (`report_control_scope_layer.scoped_build_rows` yang membungkus `report_trace_detail._build_rows`) → bukan celah
   keamanan; mekanisme visibilitas lama TIDAK diubah. Spec `mro-traceability` memanggil rantai builder existing yang sama
   (`_build_rows` + `report_financial_fix` + `scoped_build_rows`) sehingga endpoint lama (`/api/reports/mro-traceability`,
   `/export.xlsx`, tetap ada) dan Pusat Laporan (JSON/Excel/PDF) menghasilkan baris identik per user — tanpa perluasan akses.
   Izin export Pusat Laporan = izin export lama (`server.require(user, "export")`). Perubahan builder dasar (berlaku juga untuk
   endpoint lama, sesuai keputusan user): periode = tanggal MRO bisnis WIB inklusif (sebelumnya perbandingan string UTC) dan
   batas diam-diam `to_list(2000/1000)` dihapus (tidak ada pemotongan data).
7. **Test isolasi:** `tests/report_center_test.py` **59/59 PASS** (runner `scripts/run_regression_itest.sh`, DB `proc_itest`):
   V1–V14 keamanan valuasi lintas divisi/gudang; R1–R22 paritas JSON/Excel/PDF, pagination & total seluruh baris, kompatibilitas
   endpoint lama, scope divisi, redaksi, validasi, pencarian, cut-off WIB, audit; R10b paritas user Divisi A & B (endpoint lama =
   Pusat Laporan, baris identik); R10c scope divisi di Excel & PDF; R16/R16b/R16c izin export (403 tanpa izin di endpoint lama
   DAN Pusat Laporan, 200 dengan izin); R9 PDF multi-halaman (valid pypdf, header berulang, "Hal x/N", seluruh baris, TOTAL
   format Indonesia di halaman akhir); R13–R15 redaksi harga JSON/Excel/PDF + catatan redaksi; L1–L3 batas export; Z1 read-only.
   Riwayat: 51/51 → 57/57 (paritas scope + PDF ketat) → 59/59 (R16b/R16c). FE `src/lib/reportCenter.test.mjs` 15/15.
8. **Dependensi (manual, tanpa pip freeze):** `backend/requirements.txt` hanya +2 baris vs `main`: `reportlab==5.0.1` (render PDF
   server-side) dan `pypdf==6.19.0` (validasi/baca-ulang PDF di test). Dependensi lain tidak berubah. Instalasi di venv bersih
   lolos (versi 5.0.1 / 6.19.0 terverifikasi).
9. **testing_agent_v3:** iterasi 20 = backend 52/53 — satu-satunya gagal API-6.6 adalah kontrak tester yang salah (mengira staff
   sandbox tanpa izin export; faktanya fixture UAT existing `scripts/uat_fixture_stock_opname.py:41` memberi override
   `export: allow`, dan endpoint lama juga 200 → paritas). Catatan FE minor (opsi page-size "10" tidak ada — opsi shared 25/50/100;
   selector logout) juga kontrak tester. Tidak ada perubahan kode aplikasi. Iterasi 21 (kontrak dikoreksi, assertion bisnis tidak
   dilemahkan): **backend 52/52 PASS, frontend semua skenario PASS, 0 open findings** (`test_reports/iteration_21.json`). Jumlah 52
   vs 53: iterasi 21 memakai ulang data MRO iterasi 20 sehingga langkah setup "buat MRO" tidak dijalankan. Hasil 59/59 di atas
   adalah suite berbeda (isolasi) dan tidak dihitung sebagai kelulusan testing agent.

#### Sisa Data Uji Sandbox
Dibuat testing_agent_v3 iterasi 20 (2026-10-09 ±13:16 WIB) di DB sandbox `proc_sandbox` (bukan production). Tidak dihapus
(tidak ada route DELETE MRO → 405; tanpa direct-write DB / reset / endpoint baru), sesuai keputusan user.
| No MRO | ID | Tanggal (UTC) | Tenant | Divisi | Status |
|---|---|---|---|---|---|
| MRO-UAT-RC-20261009131629-0 | c42db7d1-32f7-4da8-acb7-55abe9eec73e | 2026-10-09T06:16:29Z | tenant-qa-sandbox | Asset (DIV-AST) | Open |
| MRO-UAT-RC-20261009131629-1 | db6b12d0-43f2-4f0c-8c7a-9ab1ab0cab38 | 2026-10-09T06:16:29Z | tenant-qa-sandbox | Asset (DIV-AST) | Open |
| MRO-UAT-RC-20261009131629-2 | 98f9cb01-d877-492c-9c17-81820e6f877e | 2026-10-09T06:16:29Z | tenant-qa-sandbox | Asset (DIV-AST) | Open |
Dampak: masing-masing 1 baris, tanpa RO/PO/DO/MI (qty_ro/po/mi = 0) → tidak memengaruhi stok, nilai persediaan, ledger, atau
valuasi; hanya tampil sebagai 3 baris MRO Open di MRO Traceability/dashboard MRO tenant sandbox (iterasi 21 memakainya ulang).
Pengujian deterministik P0 memakai DB terisolasi `proc_itest` (direset per run), sehingga tidak terpengaruh.

#### Quality Gates final P0 (2026-10-09, serial, setelah seluruh perubahan terakhir; DB test `proc_itest`, tanpa production)
| Gate | Perintah | Hasil |
|---|---|---|
| Regresi backend | `DATABASE_URL=$ITEST_DATABASE_URL bash scripts/run_regression_itest.sh` | exit 0 — **20/20 suite PASS, FAIL 0** (termasuk report_center 59/59, valuation_hardening 40/40, inventory_value_asof 40/40, stock_summary_parity 41/41, master_tenant_isolation 218/218) |
| Full integrity | `scripts/run_integrity_tests_mariadb.sh` (single-instance) | exit 0 — **PASS 13, FAIL 0** |
| Frontend | `node src/**/*.test.mjs` | **18/18 PASS** |
| Build | `CI=true yarn build` | exit 0 |
| Diff | `git diff --check` | exit 0 |
| Scope MWA/valuation/ledger/transaksi | `git diff origin/main` pada file yang memuat logika MWA/avg cost (server.py, valuation_replay.py, stock_summary.py, transaction_mutation_layer.py, doc_*.py, opening_*/adjustment/opname layer, dll.) | **0 file berubah** (satu-satunya file "valuation" baru = `valuation_report_scope_layer.py`, layer scope laporan read-only) |
| requirements.txt | `git diff origin/main -- backend/requirements.txt` | hanya `+reportlab==5.0.1`, `+pypdf==6.19.0` |
| Secret scan (gitleaks 8.21.2, `--redact`) | scope PR · patch PR (committed+staged+unstaged+untracked) · arsip bukti · artefak testing agent iter20/21 + test_reports | **0 / 0 / 0 / 0 temuan** (exit 0) |
| Secret scan legacy | working tree /app · riwayat Git (108 commit, termasuk commit lokal P0) | 6 / 3 temuan — **identik baseline** (fingerprint sama); remediasi TERPISAH, tidak diubah di PR ini |
| Known-value scan | nilai kredensial dikenal vs scope + arsip + test_reports + artefak testing agent (nilai tidak dicetak) | **0 file hit** — sebelumnya 3 salinan skrip testing agent iter20 di arsip bukti (di luar Git) memuat kredensial sandbox → nilai diredaksi `***REDACTED***` |
| testing_agent_v3 | iterasi 21 | backend 52/52, frontend PASS, **0 open findings** |

### P1–P6 (Status: NOT STARTED — menunggu review PR P0)
P1 Persediaan (posisi as-of, ringkasan nilai, kartu stok qty/nilai, mutasi persediaan, HPP pemakaian, min/max) · P2 Procurement ·
P3 Warehouse · P4 SPK & Kontrak · P5 Invoice & Hutang (aging, pembayaran, kartu hutang) · P6 export di list transaksi.
