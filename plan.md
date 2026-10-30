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

PR P0 = #57 (merged ke `main` 1cf2a11).

### P1 — Reporting Persediaan & Nilai Persediaan (Status: COMPLETED — Quality Gates PASS; branch `feature/reporting-p1-inventory` dari `main` 1cf2a11; PR #58 MERGED ke `main` 22e0c7d)
Keputusan user (2026-10-09): (1) tanpa `view_purchase_price`: Posisi Stok, Kartu Stok Qty, Mutasi, Min/Max tampil tanpa kolom
nilai; Ringkasan Nilai, Kartu Stok Nilai, Rekap HPP MI -> 403 (+ tidak tampil di katalog), sama dengan endpoint valuation;
(2) Transfer/Loan/Return internal = kolom "Transfer/Loan Masuk" & "Transfer/Loan Keluar" (net 0 pada cakupan seluruh gudang),
DO/MI/Adjustment/Opname/Saldo Awal kolom tersendiri; (3) Min/Max = `item_warehouse.min_stock/max_stock`, status Kosong / Di
bawah Min / Normal / Di atas Max (rule `cell_status` existing), saran reorder = Max − stok (Max kosong: Min − stok) untuk
Kosong/Di bawah Min; (4) Kartu Stok wajib 1 barang (opsional 1 gudang): saldo awal, mutasi kronologis + saldo berjalan,
saldo akhir; (5) push/PR dengan token GitHub baru di akhir.

**Audit sumber data & mapping:**
- Qty mutasi: `stock_ledger` (semua mutasi qty termasuk Opening Balance Import). Nilai: `valuation_ledger` (value_in/out,
  value_after hasil `server.post_movement`). Posisi hari ini: `item_warehouse` (current_stock/total_value/avg_cost/min/max).
- Posisi historis: qty = Σ stock_ledger s/d cut-off; nilai = value_after entri valuation_ledger terakhir per item×gudang
  s/d cut-off (= `stock_summary.value_as_of_fn` = Inventory/Dashboard per tanggal). Tidak ada harga/formula baru.
- Scope = `stock_summary.compute` (tenant, divisi barang, gudang aktif dalam cakupan + penugasan) -> total identik
  Inventory/Dashboard. Filter Divisi = divisi barang (sama dengan Inventory); Ringkasan per "Divisi Gudang" = divisi gudang.
- Kategori mutasi dari `doc_type` (Reversal X = kategori X arah terbalik): DO, MI, Transfer/Loan/Loan Return In|Out,
  Stock Adjustment, Stock Opname Adjustment, Opening Balance/Import/Valuation, Lainnya.
- HPP MI = Σ (value_out − value_in) entri MI/Reversal MI; per Proyek/Unit dari `project_id/unit_id` ledger; per SPK dibagi
  porsi qty `procurement_item_spk_allocations` (rumus existing `/mi/{id}/valuation`); tanpa alokasi -> "(Tanpa SPK)".
- Identitas: Saldo Awal + Σ mutasi + Selisih = Saldo Akhir; Selisih (kolom eksplisit, normalnya 0) = koreksi pool di luar
  mutasi tercatat (pembulatan saldo nol / revaluasi saldo awal) — tidak disembunyikan.
- **Penyelarasan cut-off WIB:** `stock_summary._txn_day` sebelumnya `str(txn_at)[:10]` (tanggal UTC untuk timestamp penuh,
  mis. reversal/DO) -> kini `reporting.scope.local_day` (tanggal bisnis WIB; tanggal murni tetap) = P0 valuation-ledger.
  Hanya jalur baca laporan/Inventory; backdate guard & engine MWA tidak diubah.

**Implementasi (fondasi P0 dipakai ulang, tidak dibuat ulang):**
- `reporting/registry.py`: Filter + `required`/`default`, tipe master warehouse/category/item/project/unit.
- `reporting/report_center.py`: validasi semua filter tanggal (as_of), default select, filter wajib -> notice (JSON 0 baris,
  export 400), label filter master, baris `_kind` (saldo awal/akhir) tidak ikut TOTAL, 403 "Tidak memiliki akses nilai
  persediaan" untuk laporan ber-permission harga, `check_limit` kompatibel hasil tanpa `meta`.
- `reporting/reports_inventory.py` (baru): 7 laporan — posisi-stok, ringkasan-nilai, kartu-stok-qty, kartu-stok-nilai,
  mutasi-persediaan, hpp-mi, min-max-reorder.
- FE `pages/ReportCenter.jsx` + `lib/reportCenter.js`: filter master dari lookup ber-scope existing, tanda wajib (*),
  notice server, baris saldo awal/akhir ditebalkan, select dengan default; tanpa perubahan desain/menu existing.
- Test: `tests/report_inventory_test.py` **63/63** (P posisi, N ringkasan, K kartu qty/nilai, M mutasi, H HPP MI, X min/max,
  E export, W cut-off WIB, Z read-only; didaftarkan di `run_regression_itest.sh`; guard: menolak berjalan di luar DB *itest*),
  FE `reportCenter.test.mjs` **19/19** (16–19 baru). Riwayat: run pertama 62/63 — P2 salah hitung ekspektasi di test
  (PX PA1 4 / PA2 2 sesuai item_warehouse; ekspektasi dikoreksi ke nilai pasti + perbandingan ke seluruh pool diperketat);
  P0 report_center_test sempat gagal (`check_limit` membaca `res["meta"]` -> KeyError pada hasil tanpa meta) -> diperbaiki di
  implementasi, kembali 59/59. Perbaikan tampilan "-0" (nol negatif) pada kolom keluar.

**testing_agent_v3 iterasi 23:** backend API 54/54 PASS, UI semua skenario PASS (7 laporan, filter master, notice barang
wajib, baris saldo awal/akhir, export, redaksi staff, scope approver), **0 open findings** (`test_reports/iteration_23.json`).
Catatan: agen menulis kredensial sandbox di `/tmp/backend_api_test.py` (di luar Git) -> nilai diredaksi `***REDACTED***`.

#### Sisa Data Uji Sandbox (P1)
testing_agent_v3 iterasi 23 menjalankan `report_inventory_test.py` tanpa `TEST_API_URL` -> default backend sandbox `localhost:8001`
-> membuat 1 tenant QA terisolasi baru di `proc_sandbox` (bukan production): **`RC f143d9c2`**
(`tenant-77876640-26eb-4ee8-9657-03a202d8b1a6`, 2026-10-09T07:59:19Z) berisi fixture test (divisi/gudang/barang PX·PY·PZ,
adjustment, transfer, loan/return, MI Direct, MRO/RO/PO). Tenant terpisah -> tidak memengaruhi `tenant-qa-sandbox`, laporan,
atau dashboard tenant lain. Pola sama dengan 23 tenant "RC …" dari run test lama. Tidak dihapus (tanpa direct-write/reset).
Pencegahan: guard di `report_inventory_test.py` (exit 2 bila DB bukan *itest*/*_test*).

#### Quality Gates final P1 (2026-10-09, serial, DB test `proc_itest`, tanpa production)
| Gate | Hasil |
|---|---|
| Regresi backend (`run_regression_itest.sh`) | exit 0 — **21/21 suite PASS** (report_inventory 63/63, report_center 59/59, inventory_value_asof 40/40, valuation_hardening 40/40, stock_summary_parity 41/41, master_tenant_isolation 218/218, …) |
| Full integrity (single-instance) | exit 0 — **PASS 13, FAIL 0** |
| Frontend `*.test.mjs` | **18/18 file PASS** (reportCenter 19/19) |
| `CI=true yarn build` / `git diff --check` | exit 0 / exit 0 |
| Scope MWA/valuation/ledger/transaksi | engine `server.post_movement`, `valuation_replay.py`, `transaction_mutation_layer.py`, `doc_*.py`, layer adjustment/opname/opening: **0 perubahan**; satu-satunya file ber-logika nilai yang berubah = `stock_summary._txn_day` (derivasi tanggal cut-off WIB, jalur baca) |
| requirements.txt | tidak berubah |
| Secret scan gitleaks 8.21.2 | scope PR / patch / arsip / artefak testing agent iter20–23 = **0** temuan; legacy working tree 6 & history 3 (109 commit) **identik baseline** (remediasi terpisah) |
| Known-value scan (termasuk seluruh /tmp) | **0 file hit** (setelah redaksi `/tmp/backend_api_test.py`) |
| testing_agent_v3 iterasi 23 | 54/54 + UI PASS, **0 open findings** |

PR P1 = #58 (merged ke `main` 22e0c7d).

### P2a — Reporting Operasional Procurement + Redesain/Konsolidasi Pusat Laporan (Status: COMPLETED — Quality Gates PASS; branch `feature/reporting-p2a-procurement` dari `main` 22e0c7d; PR #59 MERGED ke `main` b5d4722)
Keputusan user (2026-10-09): P2 dipecah 2 PR — **P2a** = Register MRO/RO/PO/DO/MI, Lead Time, Pemakaian per Unit/Proyek,
penyempurnaan MRO Traceability, + redesain beranda Pusat Laporan 5 card & konsolidasi laporan lama; **P2b** (setelah P2a merged)
= Outstanding MRO/RO/PO/DO per alokasi baris, Rekap Pembelian, Rekap Nilai Penerimaan DO.

**Audit laporan existing & keputusan konsolidasi (tanpa duplikasi):**
- `/reports` (Reports.jsx) tab MRO Traceability / Lead Time / Pemakaian Unit -> digantikan penuh oleh Pusat Laporan
  (`mro-traceability`, `lead-time`, `pemakaian-barang`); halaman, tab, endpoint lama (`/api/reports/lead-time`,
  `/api/reports/unit-usage`, `/api/reports/mro-traceability[/export.xlsx]`) TETAP + banner arahan ke laporan utama.
  Catatan lama: Lead Time lama hanya dokumen pertama per MRO header & dibatasi 300 MRO; Pemakaian Unit lama tidak
  mengurangi Reversal MI & tanpa periode — tidak diubah (kompatibilitas), versi Pusat Laporan memperbaikinya.
- `/inventory` (posisi & ledger) = menu operasional Persediaan, fungsinya sudah ada di P1 -> tidak didaftarkan ganda.
- Halaman modul berfungsi berbeda -> "Halaman modul terkait" pada card (permission aslinya): `/traceability` (Procurement),
  `/spk`, `/vendor-contracts` (SPK & Kontrak Vendor), `/invoice?tab=invoice`, `/invoice?tab=do` (invoice.view),
  `/dp-supplier` (supplier_dp.view) (Invoice & Hutang).
- Belum tersedia -> ditandai "Segera · fase" (tidak dapat diklik): P2b Outstanding/Rekap Pembelian/Rekap DO; P3 Transfer,
  Pinjam & Return, Penyesuaian, Opname; P4 Realisasi Anggaran SPK, Kepatuhan Harga PO; P5 Aging, Register Pembayaran, Kartu Hutang.

**Implementasi (reuse, tanpa engine/transaksi baru):**
- `reporting/reports_procurement_ops.py` (baru): register-mro/ro/po/do/mi (enrichment daftar `receipt_control_layer.enrich_list`
  + visibilitas `server.ACCESS_FILTER_VISIBLE` + helper status `doc_procurement.mro_status/ro_status`, status PO =
  `display_document_status` + filter kelompok dasar, status penerimaan label existing; tanpa batas 1000 dokumen); lead-time
  (rantai `report_trace_detail._build_rows` = MRO Traceability; per MRO × barang; filter periode/divisi/proyek/supplier/status);
  pemakaian-barang (valuation ledger MI net reversal, satuan dasar, scope P1). Nilai PO (bruto/diskon/DPP/pajak/total),
  Nilai DO (DPP × qty diterima, rumus MRO Traceability), HPP MI terpisah; semua price=True.
- `reporting/reports_procurement.py`: MRO Traceability + filter Barang & Kategori (builder/endpoint lama tetap).
- `reporting/hub.py` (baru) + catalog: judul 5 card, link modul (ber-permission), daftar belum tersedia.
- **Perbaikan bug (jalur baca)**: entri "Reversal MI" dari engine existing tidak membawa project_id/unit_id ->
  `reports_inventory.inherit_reversal_attrs` mewarisi dari entri asli (`reversal_of`) -> pembatalan MI mengurangi Unit/Proyek/
  SPK asal (berlaku juga untuk Rekap HPP MI P1). Ledger tidak diubah.
- FE: beranda `/report-center` = 5 card (grid 1/2/3 kolom), tombol "Semua Kategori", filter Supplier; Reports.jsx banner;
  ModuleHub deskripsi. Desain/komponen existing.
- Test: `tests/report_procurement_test.py` (guard DB *itest*; terdaftar di runner), FE 20–23.

**Audit scope Git (vs `origin/main` 22e0c7d):** 13 file — `reporting/{hub,reports_procurement_ops}.py` (baru),
`reporting/{registry,report_center,reports_inventory,reports_procurement}.py`, `scripts/run_regression_itest.sh`,
`tests/report_procurement_test.py` (baru), FE `ReportCenter.jsx`, `Reports.jsx`, `ModuleHub.jsx`, `reportCenter.test.mjs`, `plan.md`.
Tidak ada perubahan pada `server.py`, MWA/valuation engine, `valuation_replay.py`, stock/valuation ledger, layer transaksi/mutasi.
**`stock_summary.py`: 0 baris diff** terhadap `main` (perubahan P1 sudah ada di `main` via #58; P2a tidak mengubahnya) ->
perhitungan stok, nilai persediaan, cut-off WIB, dan pembatasan akses tidak berubah. Satu-satunya perubahan shared logic P1 =
`reports_inventory.inherit_reversal_attrs` (jalur baca Rekap HPP MI; field engine `reversal_of` diverifikasi di `server.py`),
tercakup oleh `report_inventory_test` 63/63 + `report_procurement_test` 39/39 + `stock_summary_parity_test` 41/41 + `inventory_value_asof_test` 40/40.

#### Quality Gates final P2a (2026-10-09, serial, DB test `proc_itest` terisolasi, tanpa production)
| Gate | Hasil |
|---|---|
| Backend regression penuh (`run_regression_itest.sh`) | **22/22 PASS** (report_procurement 39/39, report_inventory 63/63, report_center 59/59) |
| Full Integrity Suite (single-instance) | **13/13 PASS** |
| Frontend tests (18 file `*.test.mjs`) | **18/18 PASS** (reportCenter 23/23) |
| `CI=true yarn build` | PASS |
| `git diff --check` | PASS |
| testing_agent_v3 iterasi 24 | backend 9/9 suite + UI 12/12, **0 open findings** (sandbox tanpa PO/DO/MI -> skenario berdata dicakup test terisolasi) |
| Browser UAT (screenshot) | 5 card, 12 item "Segera · fase" aria-disabled, Register PO + filter, banner `/reports` |
| Gitleaks scope P2a + arsip test_reports | **0** |
| Gitleaks working tree / history | 6 / 3 = identik baseline legacy (`.env`, 2 script test, `legacy/ci.yml`) — remediasi terpisah; tambahan P2a **0** |
| Known-value scan | 0 secret di file P2a; 1 artefak `/tmp` testing agent (di luar repo) diredaksi |
Catatan eksekusi: run integrity pertama tercampur dengan run lain (kredensial DB salah) -> sesi bentrok; diulang sendiri -> 13/13.

## Urutan kerja (keputusan user 2026-10-09)
1. **H1 Performance Hotfix** — PR #60 MERGED ke `main` 57edd26.
2. **P2b** — branch `feature/reporting-p2b` dari `main` 57edd26 — Status: IN PROGRESS (termasuk konsolidasi navigasi Laporan 2 card).
3. **Performance Optimization menyeluruh** — PR terpisah SETELAH P2b merged (prioritas: pagination sebenarnya, N+1,
   agregasi Dashboard, optimasi frontend). **Perubahan indeks/migrasi DB dan multi-worker wajib diaudit & disetujui
   tersendiri sebelum diterapkan.**

### Performance Audit Tahap 1 (Status: COMPLETED — read-only; laporan disampaikan ke user)
Lingkungan: backend terisolasi `production_bootstrap.py` (1 worker = Dockerfile production), DB uji `proc_perf_itest` (20×:
5.000 MRO/RO/PO, 4.000 DO, 2.660 MI, 56.740 ledger, 60.260 allocations, 2.000 item, 20 gudang) dan `proc_perf1_itest` (1×: 250 alur
nyata via API). Production/sandbox tidak disentuh. Tooling di `/root/perf` (di luar repo).
Root cause (ranking): (1) KRITIS `mariadb_motor._op_matches` `$in` O(baris × panjang daftar) = 98,7% CPU Dashboard;
(2) KRITIS 1 worker + request CPU-bound -> head-of-line blocking (auth/me 4 ms -> 2,4 s saat 1 request berat);
(3) paginasi semu: list meng-enrich SELURUH koleksi sebelum dipotong (`txn_list_paging_layer`, `receipt_control_layer.enrich_list`);
(4) N+1 MRO Traceability/Lead Time (`report_trace_detail._build_rows` + `report_financial_fix`): 205.000 query @20×;
(5) Dashboard memuat seluruh riwayat, `$gte/$lte` tidak di-pushdown, po_lines dimuat 3×; (6) `valuation_ledger` tidak ada di
`schema.sql` (tanpa kolom/indeks), beberapa tabel tanpa `tenant_id`; (7) Adjustment list 1.013 query; (8) FE bundle tunggal 560 KB gzip
tanpa lazy route, subscription/status 3×, tanpa cache data antarhalaman (duplikasi 2× di preview = StrictMode dev saja);
(9) POST PO/DO ±300 ms (wrapper berurutan, lock DO in-process). Detail dokumen, auth, master, opname sudah cepat.
Insiden: saat setup, worker backend PREVIEW sempat terhenti (PID salah) ±1–2 menit, dipulihkan `supervisorctl restart`;
sejak itu setiap PID diverifikasi (cmd + port) sebelum tindakan.

### H1 — Performance Hotfix `$in` set-based (Status: COMPLETED — Quality Gates PASS; branch `hotfix/perf-h1-in-set` dari `main` b5d4722; PR #60 MERGED ke `main` 57edd26)
Scope: hanya `backend/mariadb_motor.py` — `_InList` (lookup `(is_bool, nilai)` = semantik `_eq` identik), `_compile_filter`
sekali per query di `_select_rows` & `$match` aggregate (filter asli tidak dimutasi, tanpa cache global), `_in_fast`; fallback
linear lama untuk elemen di luar str/int/float/bool/None (regex, list, dict, enum/subclass) dan NaN. Kontrak query, pushdown SQL,
filter tenant/divisi, transaksi, MWA, ledger, valuation, aturan bisnis: tidak berubah.
Test baru: `tests/mariadb_in_match_equivalence_test.py` (14/14; terdaftar di runner regresi).

#### Quality Gates H1 (2026-10-09, serial, DB test terisolasi `proc_itest`; benchmark `proc_perf1_itest`/`proc_perf_itest`)
| Gate | Hasil |
|---|---|
| Ekuivalensi `$in`/`$nin` (kosong, duplikat, null/missing, campuran, bool vs angka, NaN, tak-hashable, regex, enum, fuzz 135 filter × 400 dok, aggregate) | **14/14 PASS** |
| Backend regression penuh | **23/23 PASS** |
| Full Integrity Suite | **13/13 PASS** |
| Frontend tests (18 file) + `CI=true yarn build` | PASS / PASS |
| testing_agent_v3 iterasi 25 (UAT preview + API) | backend 17/17, FE alur kritis OK, **0 open findings** |
| `git diff --check` | PASS |
| Gitleaks scope H1 / test_reports | 0 / 0; worktree 6 / history 3 = baseline legacy identik; tambahan H1 **0** |
| Known-value scan | 0 di repo; artefak sementara testing agent di luar repo (`/app/backend_test.py` dipindah ke `/root/perf/archive` + diredaksi, 7 `.pyc` di `/tmp` dihapus) |
Benchmark (HTTP ke proses backend terisolasi 1 worker; before = `git archive origin/main`, after = branch H1; `/root/perf/bench3.py`,
`run_bench.sh`, hasil `/root/perf/H1_BENCH.md`) — warm p50 ms, before → after:
- 1×: Dashboard 1.618 → 454 · MRO 947 → 178 · PO 564 → 151 · RO 381 → 102 · DO 298 → 103 · Register PO 561 → 151 · Dashboard premium 230 → 118.
- 20×: Dashboard >90.000 (timeout) → 6.954 · MRO 12.867 → 802 · PO 7.108 → 691 · RO 4.830 → 462 · DO 5.265 → 516 · MI 3.126 → 370 ·
  Adjustment 2.053 → 670 · Dashboard premium 48.882 → 1.966 · Register PO >90.000 → 2.972 · Posisi Stok 2.612 → 1.966.
- Head-of-line @20× (auth/me idle 4 ms): saat Daftar MRO berat p95 2.337 → 50 ms; saat Dashboard premium max 32.920 → 531 ms.
- Tidak berubah (di luar scope H1 -> PR Performance): MRO Traceability/Lead Time (~50 s @20×, 205.000 query N+1), Inventory ledger,
  Dashboard @20× masih ~7 s (muat seluruh riwayat), Adjustment 1.013 query.

### P2b — Outstanding & Nilai Procurement + Konsolidasi Navigasi Laporan (Status: COMPLETED — PR #61 MERGED ke `main` 395f54f)
Keputusan user: struktur dokumen & aturan existing sebagai acuan; Outstanding per alokasi baris; Rekap Pembelian per Supplier/Barang/
Kategori/Divisi/Proyek/Periode (bulanan/tahunan) dengan filter kombinasi; basis nilai DO = DPP (PPN & total terpisah); Nilai PO = komitmen,
Nilai DO = realisasi; 1 PO multi-DO tanpa double counting; navigasi Laporan = 2 card (Pusat Laporan, Traceability); `/reports` redirect.
- Backend `reporting/reports_procurement_outstanding.py` (baru, read-only): Outstanding MRO (qty − MI), RO (qty − PO), PO komitmen
  Approved/Closed (qty − DO), DO→MI (diterima rantai `mro_monitor_batch` − MI); cut-off = Tanggal Akhir (tanggal bisnis WIB dokumen
  lanjutan); umur; % selesai; status baris; ref dokumen lanjutan. Rekap Pembelian (snapshot baris PO: bruto/diskon/DPP/PPN/total + DPP
  diterima/sisa). Rekap Nilai Penerimaan DO (qty × DPP/PPN per unit baris PO = rumus Register DO; komitmen per baris PO dihitung sekali).
- `reports_inventory.py`: + Riwayat Pergerakan Stok (semua barang; sumber stock_ledger = Kartu Stok) = padanan tab "Kartu Stok (Ledger)".
  Audit Inventory: Posisi Stok + status min/max -> sudah ada (Posisi Stok, Min/Max & Reorder P1). Halaman operasional `/inventory`
  TETAP (route, endpoint, tab) — card "Inventory / Stock" dipindah ke hub **Persediaan** (nav Persediaan aktif di `/inventory`, nav
  Persediaan tanpa syarat modul agar card tetap terlihat seperti sebelumnya) + drill Dashboard.
- Audit Laporan Lama `/reports`: MRO Traceability, Lead Time, Pemakaian Unit -> sudah ada (P0/P2a, builder sama) -> halaman dihapus,
  URL `/reports?tab=trace|lead|usage` redirect ke padanan (parameter lain dipertahankan); tombol "Laporan Lama" di header Pusat Laporan
  dihapus; endpoint `/api/reports/*` tetap.
- FE: `ModuleHub` Laporan = 2 card sejajar (`md:grid-cols-2`, tinggi & judul sejajar, focus-visible); `hub.py` placeholder P2b dihapus.
- Optimasi performa lapisan laporan P2b (read-only, output identik): daftar id besar -> 1 query pushdown kolom terindeks + saring himpunan
  (bukan ribuan parameter `IN`); pembacaan independen paralel (`asyncio.gather`); Rekap: enrichment telusur dilewati untuk pengguna
  lintas-divisi (hook visibilitas existing mengembalikan semua baris) — pengguna terbatas tetap lewat `ACCESS_FILTER_VISIBLE`.
  Paritas before/after 105 kasus (admin, terbatas+harga, terbatas tanpa harga, divisi lain; semua group_by, cut-off, status, show=all):
  **0 perbedaan** (hash seluruh baris + totals + kolom).

**Quality Gates P2b (agent-tested, 2026-10-09):** regression serial `proc_itest` **24/24 PASS** (report_outstanding_test **41/41**:
parsial, multi-referensi 1 MRO->2 RO & 1 PO->2 DO, pembatalan MI/DO = reversal, tanpa double counting, PPN 11% + diskon = snapshot PO,
JSON = Excel = PDF, scope divisi rekap/outstanding, redaksi harga JSON/Excel/PDF + kontrol positif) · integrity **13/13 PASS** · FE
18 file 0 gagal (reportCenter 25/25) · `CI=true yarn build` PASS · `git diff --check` bersih · testing_agent_v3 iteration_26: **0 temuan
aplikasi** (backend 47/48 — 1 = 403 export untuk staff tanpa izin `export`, perilaku izin existing yang benar; frontend 100%) · secret
scan perubahan P2b 0 temuan; baseline legacy tetap 6 worktree / 3 history (terpisah) · audit scope: tidak ada perubahan MWA, valuation,
stock ledger, transaksi, maupun mariadb_motor/receipt_control_layer/doc_procurement.

**Benchmark 20× (proc_perf_itest, backend terisolasi port 8031, 1 worker, metode H1 bench3: 1 cold + 10 warm, ms)**

| Endpoint | H1 p50/p95 | P2b awal p50/p95 | P2b final p50/p95 | CPU/req awal → final |
|---|---|---|---|---|
| Outstanding MRO | – | 1.392/2.747 | 1.400/2.251 | 1.139 → 1.214 |
| Outstanding RO | – | 1.052/1.162 | 898/975 | 870 → 769 |
| Outstanding PO | – | 1.537/1.589 | 1.262/1.293 | 1.231 → 1.067 |
| Outstanding DO→MI | – | 2.932/3.096 | 2.374/2.478 | 2.289 → 2.117 |
| Outstanding PO (show=all) | – | 3.803/4.022 | 3.480/3.748 | 3.135 → 2.913 |
| Rekap Pembelian (supplier) | – | 3.746/3.841 | 854/929 | 2.947 → 755 |
| Rekap Pembelian (bulan) | – | 3.612/4.580 | 813/880 | 2.919 → 741 |
| Rekap Nilai DO (supplier) | – | 2.589/3.024 | 784/796 | 1.984 → 722 |
| Riwayat Pergerakan Stok | – | 1.193/1.453 | 1.246/1.432 | 1.111 → 1.142 |
| Register PO (existing) | 2.972/3.568 | 2.984/3.236 | 3.018/3.303 | 2.485 → 2.496 |
| Posisi Stok (existing) | 1.966/2.162 | 2.149/2.493 | 2.051/2.152 | 1.955 → 1.946 |
| Daftar MRO / PO / DO (existing) | 802/863 · 691/727 · 516/566 | 878 · 705 · 540 | 861/935 · 726/770 · 541/589 | ≈ sama |
| Inventory ledger / item-stock (existing) | 801/917 · 53/132 | 853 · 47 | 824/964 · 47/93 | ≈ sama |
| Dashboard premium (existing) | 1.966/5.000 | 2.087/4.811 | 2.028/4.693 | ≈ sama |

- Endpoint existing: **tidak ada regresi** (selisih dalam noise ±5%). auth/me idle p50 5 ms; saat Dashboard premium berat p95 146 ms.
- Target p95 ≤500 ms pada 20× **belum tercapai** untuk Outstanding (0,9–2,5 s) & Rekap (0,8–0,9 s). Pemisahan penyebab (profil per
  langkah): (a) **P2b** — enrichment ganda untuk rekap, `IN` ribuan parameter, pembacaan serial -> SUDAH dihapus (rekap −70–77%,
  outstanding −15–20%); (b) **legacy shim** `mariadb_motor` — setiap `find` membaca dokumen JSON penuh (tanpa projection/aggregation
  pushdown), decode + verifikasi ulang per baris di Python, ORDER BY filesort; Outstanding wajib membaca seluruh baris dokumen + alokasi
  (±15–60 ribu dokumen pada 20×) — komponen yang sama membuat Register PO existing 3,0 s; (c) **enrichment existing**
  `RC.enrich_list` (telusur divisi/proyek, status penerimaan) yang dipakai daftar/Register untuk visibilitas & kolom Divisi/Proyek.
  Penyelesaian (b)/(c) = projection/aggregation pushdown & indeks di shim + enrichment terbatas halaman — lintas modul, butuh
  persetujuan migrasi → fase Performance Optimization setelah P2b merged (dicatat sebagai bottleneck legacy, bukan regresi P2b).
- Insiden lingkungan 14:35 UTC: container platform restart; supervisor gagal start MariaDB karena paket belum terpasang -> preview 502.
  Dipulihkan dengan izin user (`supervisorctl start mariadb` + `restart backend`), data `/root/mariadb-data` utuh, tanpa reset/migrasi.
- Status penerimaan user: BELUM dikonfirmasi user (seluruh hasil di atas agent-tested).

P2b PR #61 MERGED ke `main` 395f54f.

### P3 — Reporting Warehouse (Status: COMPLETED — PR #62 MERGED ke `main` a222436)
Keputusan user: Performance Optimization menyeluruh DITUNDA sampai seluruh tahap Reporting & Export selesai (P3 tidak menyentuh
bottleneck legacy). Terlambat = sisa > 0 dan Tanggal Akhir (cut-off) > jatuh tempo; umur = tgl pinjam s/d kembali penuh, atau s/d
cut-off bila masih outstanding; pinjaman per BARIS (partial/multi return, multi-gudang, reversal, legacy); nilai sisa = harga pokok saat
pinjam; izin harga = `view_purchase_price` (redaksi server-side UI/JSON/total/Excel/PDF); nilai selisih opname HANYA dokumen Posted
(valuation ledger), non-Posted qty saja; status workflow opname existing apa adanya (Counting/Review/Waiting Approval/Posting/Gagal
Posting/Posted/Cancelled — tidak ada status "Draft" di sistem).
- Backend `reporting/reports_warehouse.py` (baru, READ-ONLY — hanya `find`): 9 laporan card Warehouse — Transfer Register & Detail
  Barang; Pinjam Register & Outstanding per Baris; Pengembalian Register; Penyesuaian Register & Detail Barang/Gudang; Stock Opname
  Register & Detail Selisih. Visibilitas = `ACCESS_FILTER_VISIBLE` existing; gudang/proyek/unit per baris via helper existing
  (`transfer_lines`/`loan_lines`/`adjustment_lines`); angka opname via `stock_opname_workflow_layer.compute_line`; nilai = valuation
  ledger net "Reversal X" (doc_type existing: Transfer Out, Loan Return Out, Stock Adjustment, Stock Opname Adjustment).
- `report_center.py` +1 import; `hub.py` placeholder Warehouse dihapus; FE: `hooks/useOpenParam.js` (`?open=<id>` tervalidasi, sekali
  per id) dipakai Transfer/Loan/Adjustment/Opname; kolom drill generik `drillColumnIndex` (mro_no lalu no) — efek samping disadari: drill
  server-side Register P2a & Outstanding P2b (`/mro|ro|po|do/:id`, route ada) kini juga dapat diklik.
- Audit scope: TIDAK ada perubahan MWA/HPP/valuation/stock ledger/posting transaksi/mariadb_motor/doc_warehouse/helper baris.

Quality Gates P3 (agent-tested, 2026-10-09): report_warehouse_test **43/43** (termasuk L4 multi-gudang per baris + pengembalian
DIEDIT) · regression serial `proc_itest` **25/25 PASS** · integrity **13/13 PASS** · FE 18 file 0 gagal (reportCenter 28/28) ·
`CI=true yarn build` PASS · `git diff --check` bersih · Browser UAT preview (admin & staff tanpa harga): 9 laporan, drill Adjustment/Opname
membuka detail, `?open` invalid diabaikan, redaksi harga 9/9, scope divisi, export staff 403 (izin existing), paritas JSON=Excel=PDF pada
data preview (adjustment/opname: jumlah baris, urutan, TOTAL identik); opname non-Posted bernilai: 0/50.
testing_agent_v3 iteration_27: backend 102/102, frontend 100%, **0 open findings** (file test buatan agent berisi kredensial sandbox ->
dipindah ke `/root/perf/archive`, tidak di-commit) · verifikasi manual efek samping drill: Register MRO / Outstanding MRO / MRO Traceability
membuka detail MRO yang benar · secret scan: gitleaks scope P3 (15 file) **0**; worktree 6 / history 3 = baseline legacy identik
(`.env`, 2 script test, `ci.yml`) -> tambahan P3 **0**; known-value scan (513 file tracked+untracked) 0 kredensial sandbox, 0 pola token GitHub.
Sisa P3: tidak ada. Push & PR #62 (head 0716062) dibuat open; user me-review lalu MERGED ke `main` a222436.

### P4 — Reporting SPK & Kontrak Harga Vendor (Status: COMPLETED — PR #63 OPEN, belum di-merge; branch `feature/reporting-p4-spk-contract` dari `main` a222436; target 1 PR ke `main`, TANPA merge/deploy)
Keputusan user (2026-10-09):
1. Card "SPK & Kontrak Vendor": link "Monitoring SPK" tetap -> `/spk`; link "Daftar Kontrak Harga Vendor" DIGANTI laporan B; halaman
   operasional `/vendor-contracts` tetap (input/edit). Ketiga laporan A/B/C di Pusat Laporan; dari B user berwenang membuka detail kontrak.
   Laporan = lihat & analisis; halaman operasional = input/edit. Struktur 5 kategori tidak berubah, tanpa laporan duplikat.
2. A Realisasi Anggaran SPK: Nilai Kontrak SPK (`spk_value`) TERPISAH dari Anggaran Procurement (`procurement_budget`); masing-masing
   awal + addendum efektif = akhir sesuai sumber data (addendum efektif sudah diterapkan ke header -> jangan dihitung dua kali).
   Commitment/Sisa/% pemakaian berdasarkan procurement_budget. Sisa = Budget - Commitment; Realisasi DO bagian dari Commitment.
   Status filter Draft/Active/Closed/Cancelled, default Active+Closed. Historis cut-off WIB, konsisten Dashboard (`reporting/spk.py`).
3. B Kontrak: Aktif (berlaku pada cut-off WIB) / Akan Berakhir (aktif, berakhir 0-30 hari dari cut-off; subset Aktif, tidak dihitung dua
   kali) / Expired / Draft / Cancelled. Bila beda dengan Dashboard -> aturan Dashboard sumber kebenaran. Effective Price Resolver existing.
4. C Kepatuhan: status approval PO existing ditampilkan TERPISAH dari status kepatuhan (Sesuai/Melebihi Tolerance/Tanpa Kontrak);
   PO Approved != penyimpangan disetujui. Riwayat perubahan harga kontrak resmi (harga lama, baru, tgl efektif) dari histori existing.
   Tanpa fitur approval baru.
5. C cakupan PO = Dashboard: Approved final, Partially Received, Fully Received (tidak: Waiting Approval/Draft/Cancelled/Rejected);
   pembanding = harga kontrak yang berlaku pada tanggal PO (WIB); DPP/net sebelum pajak via `compute_po_totals`.
Permission: spk:view, vendor_contract:view, view_purchase_price — redaksi nominal/harga/selisih server-side (UI/JSON/total/Excel/PDF).
   A: laporan wajib spk:view, nominal SPK dengan spk:view (paritas Dashboard); harga satuan PO di detail + view_purchase_price.
   B: wajib vendor_contract:view; harga + view_purchase_price. C: wajib po.view; harga/selisih = vendor_contract:view AND price.
6. TEMUAN & KEPUTUSAN (Opsi A, disetujui): price-change kontrak menimpa baris item (harga + effective_start) -> Resolver/Dashboard
   menilai PO sebelum perubahan sebagai "Tanpa Kontrak". Solusi: SATU rekonstruksi versi harga READ-ONLY dari
   `vendor_contract_price_history` (`reporting/contract_history.py`) dipakai Dashboard Price Control + Laporan C. Harga lama berlaku
   s/d H-1 tanggal efektif; baru mulai tanggal efektif; multi perubahan & tanggal sama ditangani berurutan (`at`). Tanggal awal versi
   pertama TIDAK tercatat (audit item tidak menyimpan effective_start) -> PO pada rentang itu = status "Riwayat Harga Tidak Lengkap"
   (tanpa mengarang tanggal/harga, tanpa backfill). Resolver input PO, engine kontrak, data & histori TIDAK diubah.
   Label "Di Atas Tolerance" -> "Melebihi Tolerance" di Dashboard & Laporan C (disetujui). Perubahan KPI Dashboard wajib dilaporkan
   sebelum/sesudah. Info PO existing `price_status` / `price_change_reason` / snapshot kontrak ditampilkan (tanpa fitur approval baru).
Read-only: TIDAK mengubah aturan SPK/PO/DO/kontrak/MWA/valuation/stock ledger.
Progres (2026-10-10, agent-tested, belum dikonfirmasi user): audit scope bersih (tidak ada perubahan MWA/HPP/valuation/stock
ledger/posting/aturan transaksi; hanya Dashboard Price Control read-only + rekonstruksi histori).
Bug konfigurasi test EXISTING di `main` (bukan bug P4; user pilih Opsi A = commit terpisah dalam PR P4): `po_price_insight_test.py` &
`po_price_required_test.py` gagal identik di clean `main` a222436 (worktree, proc_itest). Akar: helper DB membaca DATABASE_URL
`backend/.env` (DB preview), bukan DB backend yang diuji -> UPDATE fixture 0 baris. Fix: helper memakai `T.test_env()` (TEST_DATABASE_URL)
+ guard STOP bila DB bukan *itest*/*_test (+ URL tanpa password). Assertion/expected tidak diubah. proc_sandbox terverifikasi tidak berubah.
Runner: + report_spk_test.py, dashboard_spk_contract_test.py. `opening_correction_test.ins` membuat tabel bila belum ada (DDL identik
mariadb_motor._ensure_table) — dibutuhkan fixture P4 di DB test kosong.
Quality Gates: regresi backend 27/27 suite PASS; integrity 13/13 PASS; frontend 18/18 *.test.mjs PASS; po_price_insight 37/37 &
po_price_required 19/19 PASS; CI=true yarn build PASS; git diff --check PASS; Browser UAT (stack terisolasi proc_itest + build lokal,
fixture P4) A/B/C, filter, cut-off, drill, export, redaksi PASS; paritas Dashboard = Laporan C (8 baris identik, selisih 700);
testing_agent_v3 iteration_28: 0 temuan; gitleaks worktree: no leaks. KPI Dashboard sebelum -> sesudah (fixture): Sesuai 2 -> 3 PO,
Melebihi 0 -> 1, Tanpa Kontrak 6 -> 2, Riwayat Harga Tidak Lengkap - -> 2, Nilai Selisih 0 -> 700; preview sandbox: tanpa data kontrak/PO
(KPI 0 -> 0).
Finalisasi (permintaan user, read-only, satu perhitungan): (a) halaman /spk/{id}: kartu Commitment/Realisasi/Sisa Budget & % dan tab
"Commitment & Realisasi" kini dari laporan Realisasi Anggaran SPK (filter tersembunyi `spk_id`, Filter.hidden) — sebelumnya placeholder
0 (spk_layer._budget_summary "CP2" TIDAK diubah; engine/aturan tidak diubah); redaksi harga server-side. (b) Tanggal Indonesia
DD-MM-YYYY di tabel UI, PDF, dan label Periode/filter tanggal; JSON & sel Excel tetap nilai ISO yang sama (kontrak paritas R6
Excel = JSON per sel tidak diubah). (c) Filter Pusat Laporan dari URL (request pertama, respon basi diabaikan), URL ikut
Terapkan/Reset, tombol "Reset filter" pada error filter URL tidak valid.
Gate final (kode final): regresi 27/27 (report_spk_test 45/45, report_center_test 59/59), integrity 13/13, frontend 18/18 file
(reportCenter 32/32), CI=true yarn build PASS, git diff --check PASS, Browser UAT ulang PASS (deep link stabil 3x, SPK detail =
laporan = API budget-control = Dashboard, redaksi uat_noprice), testing_agent_v3 iteration_29: 0 temuan, gitleaks: no leaks.
PR: https://github.com/akuntakitatech-design/Procurment-app/pull/63 (head 3211419, base main, 3 commit, 23 file, +1285/-75)
— state open, merged_at null, TANPA merge & TANPA deploy; tidak ada migrasi database. PR #63 kemudian DI-MERGE oleh user (main 017fdc2).


### P5 — Reporting Invoice, Pembayaran & Hutang Vendor (Status: COMPLETED & MERGED — PR #64 di-merge oleh user ke `main` (merge 90c7b5d), tanpa deploy otomatis; https://github.com/akuntakitatech-design/Procurment-app/pull/64; head d2420c4; commit 819c70a test akses invoice, 514b741 P5, d2420c4 fix keamanan audit)
Audit baseline (read-only): Invoice `vendor_invoices` (DPP/PPN/total, received_date = "invoice diterima" bukan dibayar, due_date,
payment_status, paid_total, dp_allocated_total); multi-DO `vendor_invoice_allocations` (DO boleh ditagih parsial lintas invoice);
pembayaran `vendor_invoice_payments` (parsial, banyak per invoice, Aktif→Dibatalkan + alasan; hanya Referensi & Catatan — tanpa
rekening/metode); DP `vendor_invoice_dp_allocations`; lampiran entity invoice / invoice_payment; izin invoice.* lewat hook route
global (access_control_layer.classify); visibilitas invoice = SELURUH DO dalam cakupan user; as-of WIB reporting/finance.invoices_as_of.
Keputusan user: (1) Monitoring Pembayaran: Referensi + Catatan saja; kolom "Rekening Utama Supplier" TIDAK ditampilkan
(keputusan terbaru, menggantikan opsi kolom master berlabel); (2) invoice tanpa status batal (hapus permanen) & nilai invoice tidak
berversi -> posisi historis memakai nilai invoice kini — KETERBATASAN yang diterima, dicatat di catatan laporan; (3) Sisa = Total −
DP Dialokasikan − Pembayaran Aktual, DP kolom terpisah, bukan pembayaran; DP belum dialokasikan tidak mengurangi hutang;
(4) filter divisi/proyek: invoice masuk bila salah satu DO cocok, nilai tidak dipecah; baris berlabel "Lebih dari satu divisi:
<nama>" / "Lebih dari satu proyek: <nama>"; ringkasan: kelompok "Lebih dari satu divisi/proyek"; drill kelompok = isi kelompok
persis; (5) placeholder hutang (termasuk Kartu Hutang Supplier) dihapus; tautan Register Invoice diganti laporan; Status Penagihan
DO & DP Supplier tetap; tanpa filter gudang; (6) jatuh tempo = cut-off -> Belum Jatuh Tempo.
Implementasi: backend/reporting/reports_ap.py (7 ReportSpec grup `hutang`, izin invoice.view): ap-invoice-register, ap-payments,
ap-outstanding, ap-outstanding-summary, ap-aging, ap-supplier-recap, ap-supplier-recap-monthly; hub.py; report_center.py (import,
badge harga tidak tampil untuk laporan tanpa kolom harga, pesan 403 ramah, label filter invoice_id hanya bila invoice terlihat).
Keamanan (audit menyeluruh): endpoint Invoice Vendor sudah dijaga hook izin global + get_inv (cakupan DO) — dibuktikan regression
commit 819c70a (vendor_invoice_access_test 14/14). TEMUAN BARU & DIPERBAIKI: /api/audit menampilkan baris audit export laporan
(entity "report": filter terpakai termasuk label invoice/SPK, jumlah baris) kepada user lintas divisi yang tidak berizin laporan tsb
-> report_center._install_audit_guard menyaring baris audit "report" per izin laporan (commit keamanan terpisah;
tests/report_audit_access_test.py 7/7; kontrol negatif tanpa perbaikan: 5/7 GAGAL = celah nyata). Cross-division leak test
report_ap_test I3b–I3h & I6 (JSON 7 laporan, pencarian, total, pagination, Excel, PDF, invoice_id langsung, drill 403, user tanpa
invoice.view 403 JSON/Excel/PDF).
Gate final (kode d2420c4, proc_itest serial): regresi 30/30 (report_ap 68/68, report_audit_access 7/7, vendor_invoice_access 14/14,
report_center 59/59), integrity 13/13, vendor_invoice 80/80, finance_role 22/22, frontend 18/18, CI build PASS, UAT browser PASS,
testing_agent_v3 iteration_31 0 temuan, git diff --check PASS, gitleaks commit range 0 (worktree: 3 temuan lama di file non-P5).
Temuan pre-existing di luar P5 (tidak diubah): supplier_dp_test.py 80/81 bila dijalankan pada backend terisolasi — helper `dbw`
menulis ke DATABASE_URL di backend/.env (DB sandbox), bukan DB test, sehingga UPDATE status PO tidak mengenai DB test. Perlu
perbaikan helper test terpisah (pola sama dengan 8ac72e3).

### P6 — Export Seluruh Daftar Transaksi (Status: COMPLETED & MERGED — PR #65 di-merge oleh user ke `main` (merge c20c92f), tanpa deploy otomatis; branch `feature/p6-export-transaksi` dari `main` 90c7b5d; target tepat 1 PR ke `main`, TANPA merge/deploy)
Status P0–P5: seluruhnya merged ke `main` (P5 via PR #64, merge 90c7b5d).
Keputusan user: export lewat engine Pusat Laporan existing (tanpa engine baru); spec daftar transaksi `catalog=False` (tidak tampil
di katalog/hub); export mengikuti filter/tab/pencarian/periode/sort daftar & memuat SELURUH hasil filter; tombol hanya untuk izin
`export`; batas Excel 100.000 / PDF 5.000 (422, pesan jelas, tanpa potong diam-diam); kolom = kolom daftar, harga diredaksi server-side;
baseline performa di proc_itest tanpa tuning; push/PR hanya setelah gate; tanpa merge/deploy.
Implementasi: `backend/reporting/reports_txn.py` (14 spec: txn-mro, -ro, -po, -do, -mi, -transfer, -loan, -adjustment, -opname, -spk,
-vendor-contract, -invoice, -do-billing, -supplier-dp); `registry.ReportSpec` + catalog/passthrough/param_labels/own_sort;
`report_center` parameter passthrough, sort (`sort`/`dir`, kolom harga tersembunyi ditolak 400), keterangan urutan;
`txn_list_paging_layer.filter_sort` + `server.TXN_LIST_ROWS` (logika daftar yang sama: tenant -> izin -> cakupan -> enrichment);
`list_cap` (default 1.000 tetap untuk daftar; dinaikkan per-request khusus export); exporters: nama sheet aman;
`server.py` CORS expose `Content-Disposition` & `X-Report-Rows` (nama file & jumlah baris terbaca lintas origin).
Frontend: `ListExportButtons` + `lib/listExport` (query aktif tanpa halaman), `useServerList.exportKey/query`, TxnList/DataTable,
SPK, Kontrak Vendor, DP Supplier. Read-only: tidak ada perubahan MWA, valuation, ledger, posting, logika transaksi.
Temuan & perbaikan: (1) laporan "tombol tidak muncul di Transfer/Pinjam/Penyesuaian" = skrip UAT membuka /transfers,/loans,/adjustments
padahal route /transfer,/loan,/adjustment (kode sudah benar) -> ditambah regresi backend F1–F6 & frontend (route->endpoint->kunci export);
(2) CORS tidak meng-expose header export -> nama file fallback & jumlah baris hilang lintas origin -> diperbaiki; (3) fixture test
ditolak aturan "tidak boleh posting mundur" -> fixture memakai tanggal hari ini (aturan bisnis tidak diubah); (4) batas 5 user/tenant:
tiap test mendaftarkan tenant sendiri; report_txn_test memakai tepat 5 user (admin + 4) -> aturan batas user tidak diubah.
Gate final (proc_itest serial, user DB `itest` khusus proc_itest; backup /tmp/itest-backup/proc_itest_pre_p6_202610110520.sql):
regresi 31/31 suite (1.653 assertion, report_txn_test 28/28) exit 0 141 s; integrity 13/13 exit 0 223 s; frontend 19 file 23/23 exit 0;
CI=true yarn build exit 0; git diff --check exit 0; Browser UAT 14/14 daftar (Excel & PDF terunduh, pencarian terkirim, batas PDF
MRO 5.131 / PO 5.103 -> pesan tanpa potong, Excel 5.131 baris, redaksi harga, scope Divisi B, tanpa izin export tombol tersembunyi);
testing_agent_v3 iteration_32: 0 temuan terbuka (retest Transfer/Pinjam/Penyesuaian PASS).
Secret scan gitleaks 8.21.2: file P6 + laporan UAT 0 temuan; worktree 6 & history 3 = temuan legacy (backend/.env di-gitignore &
tidak dilacak; run_integrity_tests_mariadb.sh, run_ro_multiprocess_test.sh, legacy/github-workflows/ci.yml identik dengan origin/main)
-> remediasi terpisah.
Baseline performa: docs/perf-baseline-p6.md. Catatan untuk Performance Optimization: daftar memuat maks 1.000 dokumen terbaru
(perilaku lama) sehingga pada volume > 1.000 total daftar < total export; export Excel 5,1 rb baris ≈ 1,3–1,4 s.

### P6.1 — Tanggal Approval 2 di Daftar PO (Status: COMPLETED & MERGED — PR #66 di-merge oleh user ke `main` (merge c505258); branch `feature/po-approval2-date` dari `main` c20c92f)
Keputusan user: tanggal di bawah badge hijau Disetujui, kecil abu-abu `DD/MM/YYYY · Approval 2 (WIB)` (garis miring); sorting lewat
KEDUA cara — klik judul "Status Dokumen" (klik 1 terlama→terbaru, klik 2 sebaliknya) & dropdown toolbar; tenant 1 tahap = tanpa tanggal.
Sumber: `receipt_control_layer.po_approval2_at_map` — approval_tasks module=po seq=2 Approved `acted_at` siklus aktif (submit ulang
menghapus & membuat ulang task), mirror po_approvals hanya bila PO tanpa task; hanya document_status=Approved; siklus belum final /
ambigu / tanpa acted_at / tanpa riwayat -> null (tanpa perkiraan; bukan tanggal PO/updated_at). Field daftar `approval2_at` =
'YYYY-MM-DD HH:MM:SS' WIB; sort `sort=approval2_at&dir=asc|desc` lewat paging existing (kosong di akhir). Export P6 txn-po: kolom
"Tgl Approval 2 (WIB)" (sort export ikut daftar). Frontend: `lib/poApproval2Date.js`, Po.jsx (render kolom + `serverSort` + dropdown).
Workflow approval, status & aturan transaksi tidak berubah.
Gate (proc_itest serial): po_approval2_date_test 30/30; po_document_status 64/64, po_approval2_batch 84/84, po_approval2_permission 35/35;
regresi 32/32 suite (1.683 assertion) exit 0; integrity 13/13 exit 0; frontend 20 file 28/28; CI build exit 0; git diff --check exit 0;
UAT browser PASS (tanggal, status lain, klik judul asc/desc, dropdown, export urut); testing_agent_v3 iteration_33 0 temuan.

### P6.2 — Cetak PO: nomor MRO di atas nama barang (Status: COMPLETED — gate PASS; 1 PR khusus ke `main`, belum di-merge, tanpa deploy; branch `feature/po-print-mro-ref` dari `main` c505258)
PR #66 sudah di-merge sebelum pekerjaan ini -> PR terpisah (sesuai instruksi user).
Backend: `receipt_control_layer.po_line_mro_refs` + `decorate_po_detail` -> `lines[].mro_refs` di GET /api/po/{id} (read-only; rantai
allocations PO<-RO<-MRO; PO<-RO ber-`via_alloc_id` = hanya MRO allocation yang dikonsumsi; allocation lama tanpa via = semua MRO sumber
baris RO; PO<-MRO langsung ikut; unik & urut; tanpa referensi = []). po_lines disimpan dengan field whitelist -> mro_refs tidak tersimpan.
Frontend: `print.js` `poDescCell` (template PO real_reference): `div.mro-ref` (font dasar-3px, min 7px) di atas `div.item-name`; tanpa
MRO sel identik dengan sebelumnya. Kolom, lebar tabel, harga, perhitungan, tanda tangan & format tidak berubah. Print Preview & PDF = HTML sama.
Gate (proc_itest serial): po_print_mro_test 16/16; frontend tests/po_print_mro_test.mjs 12/12, po_dp_print_test 15/15, src *.test.mjs 28/28;
regresi 33/33 suite (1.699 assertion) exit 0; integrity 13/13 exit 0; CI build exit 0; UAT browser Print Preview + PDF (1 MRO, multi,
tanpa MRO, campuran) PASS; testing_agent_v3 iteration_34 0 temuan.

### P7 — Performance Optimization menyeluruh (Status: COMPLETED (agent-tested) — PR #69 OPEN, tanpa merge/deploy)
Branch `feature/p7-performance` → PR #69 ke `main` (`85831df`). Detail lengkap, metode & angka: `docs/perf-p7.md` §13.
- Optimasi jalur BACA saja (paging server-side tanpa cap 1.000, adapter MariaDB adaptif, N+1 Pull/Dashboard dihapus via batch
  `alloc_out_many`/UoM/`visible_doc_ids`, pra-saring cakupan daftar user divisi, export background). MWA/HPP/valuation/ledger/
  approval/permission/redaksi harga/tenant isolation tidak diubah.
- Akar regresi daftar user terbatas divisi: jalur cepat RO/PO/DO/MI memperkaya seluruh kandidat 2x → jalur cepat divisi hanya MRO.
- Benchmark final ABBA (3 run, 3 persona, 38 endpoint): Pull terburuk 0,997 (≤ 1,0), non-Pull terburuk 1,071 (≤ 1,10), FAIL 0/38.
- Gate: regresi 40/40 file (1.769/1.769), integrity 13/13, multiprocess 9/9, scope-prefilter 166/166, paging completeness 108/108,
  parity 327/336 (9 beda hanya `total`, by design), FE test 21/21 (main 20/20), CI build OK, UAT + testing_agent_v3 0 temuan,
  secret scan bersih.

## Responsive Design — Seluruh Aplikasi (branch `feat/responsive-ui`, base `main` 5865db3 (setelah merge #69/#70/#71)) (Status: COMPLETED — menunggu push/PR)
- Keputusan user: base `main`, terpisah dari PR #69/#70/#71 (kini sudah di-merge user; branch di-rebase); frontend/CSS/layout only; mobile-first; sidebar drawer di mobile;
  **hybrid table** (kartu untuk MRO/RO/PO/DO/MI/Invoice, tabel lain scroll dalam container); form 1 kolom di mobile;
  viewport QA 320/375/390/430/768/1024/1366/1440/1920; screenshot dirangkum (tidak di-commit); 1 PR ke `main`, tanpa merge/deploy.
- Hasil: overflow 13 → 0 dari 396 kombinasi route×viewport; target sentuh mobile ≥44px untuk kontrol shadcn; `MobileSortBar` baru.
- Verifikasi: `CI=true yarn build` OK; node unit test 29/29; testing_agent iterasi 7 (1 temuan overlay drawer → fixed), iterasi 8 & 9 (pasca-rebase) = 0 temuan.
- Detail: `docs/responsive-audit.md`.

## Platform Admin — Hapus Tenant dua tahap (branch `feat/platform-delete-tenant`, base `main` 06fcdca) (Status: COMPLETED — PR ke `main`, tanpa merge/deploy)
- Keputusan user: dua tahap — **Hapus** (soft delete, dapat dipulihkan) lalu **Hapus Permanen** (purge DB + storage); tidak wajib Suspend dulu;
  file storage tenant ikut dihapus saat purge. Dikerjakan dari laptop (Zed) dengan preview 1:1 ke DB/R2 production.
- Backend `tenant_delete_layer.py`: `GET /api/platform/tenants/{id}/delete-preview`, `POST .../delete` (status `deleted`, sesi user dicabut,
  token aktivasi pending dicabut), `POST .../restore`, `POST .../purge` (hanya status `deleted`; storage prefix `procureflow/tenants/<id>/` dulu,
  lalu semua dokumen ber-`tenant_id` di seluruh koleksi kecuali koleksi platform, lalu dokumen tenant). Tenant default & `platform-root` dilindungi (409);
  konfirmasi = ketik kode tenant; audit `tenant.deleted|restored|purged` di `platform_audit_logs` (dipertahankan).
- Pendukung: `storage.list_prefix/delete_keys`; `mariadb_motor._delete` batch 500 pk (semantik sama); lifecycle `deleted` -> locked;
  dashboard platform tidak menghitung tenant terhapus (field `deleted`); detail `is_default_tenant` + `deletion_history`; UI filter **Dihapus**.
- Verifikasi: `tests/platform_tenant_delete_test.py` 35/35 (tenant uji dibuat & di-purge sendiri); cek langsung DB+R2 tenant uji: 0 baris, 0 objek;
  data PT REAL utuh; `CI=true yarn build` OK; UAT browser (tombol, dialog dampak, banner, filter). Sisa data uji: PRC-000168 (status Dihapus).

## Kode Master — Nomor Urut Terakhir & Sinkron dari Data (Status: COMPLETED — lokal, preview 1:1 production)
- Keputusan user: opsi A — format kode (prefix/pemisah/lebar digit) + **nomor urut terakhir** + tombol **Sinkron dari data** + counter naik otomatis setelah impor Excel.
- Backend `master_code_settings_layer.py`: GET `/api/settings/master_codes` mengembalikan `sequences`, `last_seq`, `next_code`; PUT menerima `sequences`
  (validasi 0..999999999; master berkode manual dilewati); endpoint baru `POST /api/settings/master_codes/{name}/sync-sequence`
  memindai kode sesuai format aktif lalu menaikkan counter (tidak menurunkan); `bump_sequence_for_codes()` dipanggil `excel_import_layer`
  setelah impor master agar penambahan berikutnya melanjutkan nomor terakhir.
- Frontend `MasterCodeSettings.jsx`: input nomor urut terakhir per master, tombol Sinkron dari data, pratinjau kode berikutnya, simpan format+nomor.
- Verifikasi: 18/18 tes API (validasi negatif/non-angka, master manual, sinkron, restore), 5/5 tes logika bump impor,
  UI simpan 5000 -> `BRG-05001` bertahan setelah reload lalu dikembalikan ke 2, `CI=true yarn build` OK.
- Tanpa perubahan skema/env. Redeploy: backend lalu frontend.

## SPK Addendum — Tombol Edit & Hapus (Status: COMPLETED — lokal, preview 1:1 production)
- Permintaan user: tab Addendum SPK belum punya tombol edit dan hapus.
- Backend `spk_layer.py`: `DELETE /api/spk/{spk_id}/addendums/{aid}` (izin `spk_addendum:manage`); hanya status draft/cancelled,
  addendum effective ditolak 409; baris `spk_addendum_documents` ikut dihapus lalu objek storage dibersihkan best-effort; audit `delete`.
- Frontend `Spk.jsx`: tombol **Edit** (dialog terisi otomatis, memakai `PUT` existing) dan **Hapus** (konfirmasi, `DELETE`);
  kolom Aksi dibuat satu baris (`whitespace-nowrap`) agar 4 tombol tidak terlipat.
- Pembatalan Addendum **Effective** (keputusan user, opsi A): `POST /api/spk/{spk_id}/addendums/{aid}/reverse` (izin `spk_addendum:finalize`)
  membuat addendum koreksi bernilai berlawanan yang langsung effective, lalu menandai addendum asli `reversed` (histori terkunci, tidak bisa dihapus).
  Nilai SPK/budget kembali ke sebelumnya, audit mencatat status lama/baru dan nomor koreksi. UI: tombol **Batalkan** + dialog alasan wajib.
- Verifikasi: 11/11 tes API (buat draft, edit, hapus, 404, hapus ulang 404); UI: tombol Finalisasi/Edit/Batal/Hapus tampil,
  dialog "Edit Addendum" terisi nomor, toast "Addendum diperbarui", hapus -> baris hilang + "Belum ada Addendum", API 404;
  reversal: 5/5 tes negatif (draft/reversed ditolak 409, hapus reversed 409) + UI Batalkan mengembalikan budget 700.100.000 -> 700.000.000; build OK.
- Tanpa env/skema. Redeploy: backend lalu frontend.

## Email Outbound — Form Disederhanakan + Perbaikan Keamanan (Status: COMPLETED — lokal, preview 1:1 production)
- Permintaan user: klien cukup memasukkan email pengirim, tanpa setelan SMTP lain.
- Frontend `EmailOutboundSettings.jsx`: hanya **Email Pengirim** + **App Password**; nama pengirim otomatis dari nama perusahaan;
  jenis akun default Gmail dengan tautan **Pakai SMTP perusahaan** yang membuka server/port/keamanan; ringkasan "Dikirim sebagai".
- Backend `email_outbound_layer.py`: `_normalize_public` Gmail memakai `from_email` bila `username` kosong (data lama);
  `PUT` mengisi `from_name` dari Settings → Perusahaan dan `from_email` dari username.
- **Perbaikan keamanan**: route generik `/api/settings/{key}` terdaftar lebih dulu dan menelan `/api/settings/email_outbound`,
  sehingga GET mengembalikan dokumen settings mentah **termasuk password SMTP plaintext** (ditemukan saat uji). Route generik
  dipindah ke urutan terakhir (di layer email dan pass akhir `production_bootstrap.py`); password plaintext lama otomatis
  dienkripsi ke `password_encrypted` lalu field `password` dihapus saat startup (idempoten).
- Verifikasi: GET hanya field publik (`password_set=true`, `ready=true`, tanpa `password`); PUT nilai identik `200` dan password
  lama tetap dipakai; DB `password` plaintext=0, `password_encrypted`=1; UI 2 isian + status "Siap digunakan" + ringkasan
  "Dikirim sebagai: Procurement <…>"; `CI=true yarn build` OK.
- Tanpa env/skema baru. Redeploy: backend lalu frontend.

## Cetak DO — Template "Bukti Penerimaan Barang" (Status: COMPLETED — lokal, preview 1:1 production)
- Permintaan user (opsi A): cetak DO mengikuti form manual — header logo + nama perusahaan, judul kanan, dua kolom alamat
  (Warehouse/Vendor), nomor DO besar, baris `Received By | Order | State | Received Date`, tabel `Product | Quantity | To`,
  catatan "Wajib lampirkan Dokumen ini…", dua kotak tanda tangan, dan footer. Semua nilai dari data transaksi (bukan hardcode).
- `backend/print_layout_layer.py`: DO boleh `template_style=real_reference`; default REAL DO = judul "Bukti Penerimaan Barang",
  margin atas/bawah 12 & kiri/kanan 15, logo 24 mm, tanpa QR, footer kosong, label TTD
  "Project Manager / Spv Part Management" + "To Send Invoice, sign here & return"; field baru `do_note_text` dan
  `do_signature_note` (diatur di Layout Dokumen, divalidasi panjangnya).
- `backend/doc_procurement.py` `get_do()`: menambah `supplier_legal_name/address/city/phone` (telepon fallback kontak utama),
  `warehouse_address` (master Gudang → field `location`), `project_name`, `order_no` (gabungan PO sumber), dan `receipt_state`:
  semua PO sumber `Fully Received` → **Done**; ada `Partially Received`/`Fully Received` → **Partial**; selain itu status DO.
- Frontend `src/lib/doPrintReal.js` (baru): HTML cetak A4 (margin per sisi), qty format id-ID, jam dari `created_at`
  (Asia/Jakarta), kolom **To** = nomor SPK + nama project (alokasi SPK tahap DO → `lines[].spk` → `doc.spk` → "-"),
  mis. `spk01 — timbun tanah`; bila alokasi terbagi: `spk02 — pengadaan alat (200), Non-SPK (76)`.
  `@page margin` dibuat `0` dan margin dokumen dipindah ke padding sheet agar browser tidak mencetak
  header/footer bawaan (tanggal+jam, judul dokumen kecil di kanan atas, `about:blank`, nomor halaman).
- `src/lib/print.js`: cabang DO `real_reference` memakai template baru dan meneruskan `allocLines`
  (`GET /api/spk-allocations/do/doc/{id}` sudah diambil untuk DO).
- `src/pages/PrintLayouts.jsx`: selector **Template Visual** untuk PO & DO, card "Detail Template REAL" DO
  (Catatan Wajib Lampirkan + Catatan Kotak Tanda Tangan), card builder generik disembunyikan saat template REAL,
  preview DO memakai iframe template yang sama dengan hasil cetak.
- Config `tenant-pt-real` diubah via `PUT /api/settings/print_layouts` (payload `modules` lengkap):
  `modules.do.template_style=real_reference` + judul/margin/logo/QR/footer/label TTD sesuai default REAL.
- Verifikasi: cetak `DO/2026/10/00002` → PT. Rajawali Emas Ancora Lestari, Warehouse Address dari Gudang
  ("Yard Balai Raja, Jalan Lingkar Timur Pinggir"), Vendor PT. Abagi Besar Citra + alamat + kota + telepon, nomor DO,
  Received By `aprove2@gmail.com`, Order `PO/2026/10/00004`, **State Done**, Received Date + jam, `100 Pcs`, **To `spk01 — timbun tanah`**
  (alokasi SPK nyata), catatan wajib lampirkan, 2 kotak TTD; cetak `DO/2026/10/00001` (tenant uji terbuka) juga State Done;
  PO/2026/10/00004 tetap tercetak "PURCHASE ORDER" (tanpa regresi); preview Layout Dokumen DO sesuai; `CI=true yarn build` OK.
  Header/footer browser: uji `Page.printToPDF` dengan `displayHeaderFooter=true` → 1 halaman A4 (595×842 pt), tanpa tanggal/jam,
  tanpa `about:blank`, nomor DO hanya muncul 1x (di badan dokumen).
  State **Partial** mengikuti status PO, belum ada sampel PO `Partially Received` di tenant yang tidak terkunci langganan.
- Tanpa env/skema baru. Redeploy: backend lalu frontend.

## Cetak DO — Penyempurnaan (Status: COMPLETED — lokal, preview 1:1 production)
- Permintaan user: (1) hilangkan nomor DO kecil di atas judul, (2) tampilkan No. DO supplier dan No. Faktur di bawah
  Vendor Address, (3) kolom `To` menampilkan nama project setelah nomor SPK.
- `doPrintReal.js`: `document.title` dikosongkan tepat sebelum `window.print()` lalu dipulihkan, sehingga header cetak
  browser tidak lagi mencetak nomor dokumen kecil di kanan atas (margin `@page` tetap 0 agar tanggal/jam/URL tidak tercetak).
- `doPrintReal.js`: blok `.addr-meta` di bawah Vendor Address mencetak `No. DO: <supplier_dn>` dan
  `No. Faktur: <supplier_invoice>` (hanya bila datanya ada; keduanya dari data DO, bukan hardcode).
- Kolom `To` memakai SPK + nama project dari alokasi SPK tahap DO, mis. `spk01 — timbun tanah`.
- Verifikasi: cetak `DO/2026/10/00002` → Vendor Address diikuti `No. DO: ewe3w4343` dan `No. Faktur: 54668779`,
  `To: spk01 — timbun tanah`; `Page.printToPDF` (`displayHeaderFooter=true`, `preferCSSPageSize`) → 1 halaman A4 595×842 pt,
  tanpa tanggal/jam/`about:blank`, nomor DO hanya muncul 1×; `CI=true yarn build` OK.
- Tanpa env/skema baru. Redeploy: frontend saja.

## Cetak DO — Nama Project di Form & Alamat Gudang (Status: COMPLETED — lokal, preview 1:1 production)
- `SpkAllocationModal.formatAllocText(summary, {withProject})`: opsi baru menampilkan nama project setelah nomor SPK
  (`spk01: 100 — timbun tanah`). Default mati agar tampilan MRO/RO/PO tidak berubah.
- `Do.jsx`: sel **Alokasi SPK** di form DO memakai `withProject`; pratinjau baris sebelum simpan juga menampilkan nama project
  (tanpa duplikasi bila teks SPK sudah memuatnya).
- Warehouse Address: kode sudah memakai `warehouses.location`; pemilik mengisi field Lokasi di master Gudang production
  (`Yard Balai Raja, Jalan Lingkar Timur Pinggir, Duri`) sehingga cetakan memakai alamat gudang, bukan fallback alamat perusahaan.
  Tidak ada perubahan kode untuk bagian ini.
- Verifikasi: `DO/2026/10/00002` → sel form `spk01: 100 — timbun tanah`; cetak → Warehouse Address
  `Yard Balai Raja, Jalan Lingkar Timur Pinggir, Duri`, Vendor + `No. DO: ewe3w4343` + `No. Faktur: 54668779`,
  `To: spk01 — timbun tanah`; `CI=true yarn build` OK.
- Tanpa env/skema. Redeploy: frontend saja.

## Perbaikan — Alokasi SPK Hilang Setelah DO Diedit (Status: COMPLETED — lokal, preview 1:1 production)
- Laporan pemilik: setelah DO diedit, nomor SPK di form dan cetak hilang padahal di PO ada.
- Akar masalah: `transaction_mutation_layer._replace` membuat ulang seluruh baris dokumen dengan `id` baru
  (`server.gid()`), sedangkan alokasi SPK disimpan di `procurement_item_spk_allocations` per `item_line_id`.
  Akibatnya baris alokasi menunjuk id baris yang sudah dihapus (orphan) dan alokasi tidak lagi terbaca.
- Bukti data: DO/2026/10/00004 punya baris alokasi `item_line_id=68823b89…` yang tidak ada lagi di `do_lines`
  (baris aktif `d8727756…`), sedangkan DO lain (mis. DO/2026/10/00002) alokasinya masih cocok.
- Perbaikan: `_replace` memetakan `id` baris lama → id baris baru dari payload, lalu `update_many` alokasi SPK
  ke id baru; alokasi milik baris yang dihapus dibersihkan agar tidak menjadi orphan yang ikut menghitung pemakaian SPK.
  `_delete` juga menghapus alokasi SPK dokumen. Tidak ada perubahan pada `source_key` ledger (tetap unik per posting).
- Verifikasi: `py_compile` OK; nama field koleksi terverifikasi (`source_document_id`, `item_line_id`, `allocated_qty`);
  pemetaan id diverifikasi dari payload frontend (`lines` memuat `id` baris tersimpan). Uji edit end-to-end belum dijalankan
  agar tidak mengubah data production.
- Tanpa env/skema. Redeploy: backend.

## Master Barang — 5000 Item + Perbaikan Import & Batas Daftar (Status: COMPLETED — data production)
- Permintaan pemilik: buat nama barang baru sampai total 5000; wajib isi nama, kategori, satuan, divisi, supplier utama.
- Data `tenant-pt-real`: 949 → **5000** item. 4051 item baru: kode `SKU/0948`–`SKU/4998`, nama
  `BARANG TEST 0001`–`BARANG TEST 4051`, kategori `SPAREPART`, divisi `SPAREPART`, satuan `Pcs`,
  supplier utama `SUP-00001` (PT. ABC). Dibuat lewat `POST /api/excel/import/items` (2 baris uji + 4049 sisanya).
- `excel_import_layer._import_master` (items): kini mengisi field turunan `category`, `unit`, dan `uoms` seperti
  `master_auto._normalize_item` (sebelumnya kosong karena jalur import melewati normalisasi).
- `server.master_list`: `.to_list(3000)` → `.to_list(50000)` agar seluruh 5000 item terjangkau di halaman Master
  (sebelumnya `total` berhenti di 3000 dan item terlama tidak muncul/tidak bisa dicari).
- Verifikasi: DB total 5000, `BARANG TEST` 4051, tidak ada item tanpa tenant; `GET /master/items?page=1` → `total=5000`;
  lookup form memakai `to_list(50000)` sehingga semua item tersedia di combobox; uji import 1 baris (`SKU/9999`)
  menghasilkan `category=SPAREPART`, `unit=Pcs`, `uoms=[{base,factor:1}]` lalu baris uji dihapus (total kembali 5000);
  `py_compile` OK.
- Tanpa env/skema. Redeploy: backend.
- Catatan: 4051 item `BARANG TEST` adalah data uji; hapus bila tidak diperlukan (butuh perintah eksplisit).

## Approval Supplier — Supplier Baru Wajib Disetujui Atasan (Status: COMPLETED — lokal, preview 1:1 production)
- Permintaan pemilik: input supplier baru butuh approval atasan; sebelum disetujui **tidak muncul di transaksi PO**;
  tersedia approval massal; menunya di **Approval** (ditambah kartu Supplier).
- Backend layer baru `supplier_approval_layer.py`:
  - `POST /api/master/suppliers` menandai supplier baru `approval_status=pending` (+ pemohon & waktu) dan mengirim notifikasi.
  - `GET /api/supplier-approvals?status=pending|approved|rejected` (izin `view`) → daftar + `counts`.
  - `POST /api/supplier-approvals/approve|reject` (izin `approve`), menerima banyak `ids` sekaligus (approval massal);
    reject wajib alasan; setiap keputusan masuk audit `approve`/`reject`.
  - Guard PO: `POST /api/po` dan `PUT /api/transactions/po/{id}` menolak supplier yang belum approved (400, pesan jelas)
    sehingga aturan tidak bisa di-bypass lewat API langsung.
  - `access_control_layer.lookup_rows`: supplier non-approved disembunyikan dari `/lookup/suppliers` dan `/lookup-batch`
    (dipakai form PO).
  - `master_list_paging_layer`: label status supplier menjadi `Menunggu Approval` / `Ditolak`.
  - Supplier lama tanpa field `approval_status` dianggap **approved** (backward compatible; 63 supplier existing tetap bisa dipakai).
  - Catatan teknis: layer mengambil `server.db` saat request karena `tenant_isolation_layer` memasang proxy tenant setelah layer ini.
    Versi pertama sempat membaca 860 supplier lintas tenant; setelah diperbaiki terbaca 63 (tenant sendiri).
- Frontend: kartu ke-4 **Supplier** di menu Approval (`approval-tab-supplier`) + komponen `SupplierApprovalPanel`
  (tab Menunggu/Disetujui/Ditolak, pencarian, pilih semua, **Setujui Terpilih** / **Tolak Terpilih**, aksi per baris)
  dan banner di form Supplier baru.
- Verifikasi: create supplier → `pending` & tidak ada di lookup (63) → approve → muncul di lookup (65 dengan 2 uji) →
  reject → `POST /po` ditolak 400; `status_label` `Ditolak`/`Aktif` benar; **approval massal 2 supplier via UI** → 0 tersisa;
  banner form tampil; `CI=true yarn build` OK. Data uji `SUP-00006/7/8` dihapus → 63 supplier, 0 pending.
- Belum tercakup: import Excel supplier tetap membuat supplier langsung aktif (bisa diubah bila diminta).
- Redeploy: backend lalu frontend.

## Dashboard Top 10 Supplier (Status: COMPLETED — branch `feat/dashboard-top10-supplier`, menunggu merge)
- Permintaan pemilik: widget dashboard "Top 5 Supplier" dinaikkan menjadi **Top 10 Supplier**.
- Backend:
  - `reporting/charts.py` → `supplier_rank(po_rows, perm, limit=10)` (sebelumnya `limit=5`).
  - `premium_dashboard_layer.py` → `top_suppliers` dipotong `[:10]` (sebelumnya `[:5]`); `top_categories` tetap 5.
- Frontend: `components/dashboard/TopSuppliers.jsx` judul panel menjadi **"Top 10 Supplier"**.
- Test: `tests/dashboard_control_center_test.py` asersi `len(rk) <= 10`.
- Tanpa env/skema baru. Redeploy: backend lalu frontend.
- Catatan data: `tenant-pt-real` baru punya **5 supplier dengan PO valid**, jadi widget tetap menampilkan 5 baris
  sampai ada lebih banyak supplier ber-PO. Batas 10 adalah plafon, bukan jumlah baris paksa.

## Cetak PO — Paraf Approval 1 (Status: COMPLETED — branch `feat/po-paraf-approval1`)
- Permintaan pemilik: paraf Approval 1 muncul di cetak PO setelah Approval 1 disetujui, dan terbawa sampai Approval 2.
  Posisi di sisi kanan stempel/TTD Approval 2, sementara stempel tetap **center** seperti sebelumnya.
- `frontend/src/lib/poPrintReal.js`: data diambil dari `doc.approvals` (`seq = 1`, status `Approved`, `acted_by`, `acted_at`),
  dirender sebagai blok `.paraf-l1` (label "Paraf Approval 1", nama approver, tanggal) di dalam `.sign-space` kolom kiri.
- CSS: `.sign-space` tetap tinggi 14mm, kini grid `minmax(0,1fr) auto minmax(0,1fr)`; `.approved-signature` di kolom 2
  (tetap center), `.paraf-l1` di kolom 3 (`margin-left:3mm`) → posisi stempel tidak bergeser, paraf menempel di kanannya.
- Tidak diubah: watermark DRAFT (termasuk PO berstatus `Waiting Approval`), label "Approved by,"/"Signed by,",
  nama & perusahaan, footer, tabel item, QR verifikasi.
- Test `frontend/tests/po_print_real_test.mjs`: +6 asersi (tampil saat Approval 1 disetujui; tampil saat `Waiting Approval`
  bersama watermark DRAFT; tetap tampil di PO yang sudah Approval 2; tidak tampil bila Approval 1 belum disetujui;
  tidak tampil bila `show_signatures=false`; grid memastikan stempel tetap center).
- Cakupan: tombol Print, Cetak Internal, Save as PDF, dan pratinjau Print Layouts. Email PO memakai HTML terpisah → belum memuat paraf.
- Tanpa env/skema baru. Redeploy: frontend.

## Cetak PO — Paraf Approval 1 sebagai Gambar & Konfigurabel (Status: COMPLETED — branch `feat/po-paraf-image-config`)
- Permintaan pemilik: paraf Approval 1 memakai gambar (bukan hanya teks) dan **bisa dikonfigurasi di menu Layout Dokumen**.
- Backend (`backend/po_email_signature_layer.py`): 4 endpoint baru dengan record settings terpisah `po_paraf`
  (agar tidak hilang saat Layout Dokumen disimpan):
  - `POST /api/settings/print_layouts/po/paraf` — upload PNG/JPG/WEBP maks 5 MB, izin `edit`, disimpan ke storage
    sebagai `settings/po-paraf.<ext>`, field `po_paraf_path/content_type/version`, audit "Paraf Approval 1 diperbarui".
  - `GET /api/settings/print_layouts/po/paraf` — kirim gambar (`Cache-Control: no-store`).
  - `DELETE /api/settings/print_layouts/po/paraf` — hapus record + audit.
  - `GET /api/settings/print_layouts/po/paraf-status` — `{available, version, stored}`.
- Frontend:
  - `pages/PrintLayouts.jsx`: kartu **Paraf Approval 1** (preview gambar tersimpan, upload, hapus) + pratinjau PO memakai
    gambar paraf yang sama.
  - `lib/printAssets.js`: `poParafPath()`; `lib/print.js`: ambil paraf (selalu dicek untuk PO, tidak bergantung status final).
  - `lib/poPrintReal.js`: parameter `parafImg`; gambar maks 20mm × 7,5mm di kolom kanan ruang tanda tangan (stempel tetap center).
    Bila paraf belum diupload → fallback teks nama + tanggal seperti rilis sebelumnya.
- Test: `frontend/tests/po_print_real_test.mjs` 59/59 (4 asersi baru: gambar dicetak, tanggal tidak dicetak saat bergambar,
  fallback teks, gambar tidak muncul bila Approval 1 belum disetujui).
- Uji endpoint nyata di preview (DB & storage production, data uji 1×1 transparan lalu dihapus): 9/9 —
  status awal belum ada → GET 404 → upload 200 → status available → GET 200 image → file non-gambar 400 → hapus 200 → status bersih → GET 404.
  State akhir production: **tidak ada paraf** (menunggu upload gambar asli oleh pemilik).
- Tanpa env/skema baru. Redeploy: backend lalu frontend.

## Cetak PO — Paraf Hanya Gambar (Status: COMPLETED — branch `fix/po-paraf-image-only`)
- Permintaan pemilik: paraf cukup **gambar paraf saja**; label "Paraf Approval 1", nama approver, dan tanggal dihilangkan.
  Posisi tetap seperti yang dikirim pemilik (sisi kanan area tanda tangan, sejajar dengan stempel).
- `frontend/src/lib/poPrintReal.js`:
  - Blok paraf disederhanakan menjadi `<div class="paraf-l1"><img class="paraf-signature" .../></div>`.
  - Gate berubah dari "task seq 1 Approved + acted_by" menjadi "ada task seq 1 berstatus Approved" (nama tidak dipakai lagi).
  - CSS `.paraf-title/.paraf-name/.paraf-date` dihapus; hanya `.paraf-l1` + `.paraf-signature` (maks 20mm × 7,5mm).
  - Tidak ada fallback teks: bila gambar paraf belum diupload, blok paraf tidak dicetak.
- `frontend/src/pages/PrintLayouts.jsx`: keterangan kartu diperbarui (hanya gambar yang dicetak).
- `frontend/tests/po_print_real_test.mjs`: asersi disesuaikan — paraf hanya gambar (tanpa label/nama/tanggal), tampil saat Approval 1,
  tetap tampil setelah Approval 2, tidak tampil bila Approval 1 belum disetujui / gambar belum diupload / `show_signatures=false`.
- Verifikasi: test cetak PO **56/56**; render Edge headless memakai **gambar paraf asli** (yang sudah diupload pemilik) — hanya paraf
  yang tampil, sejajar dengan stempel dan tidak menimpa nama; kondisi `Waiting Approval` (tanpa stempel) juga sesuai gambar pemilik.
- Catatan data: `settings.po_paraf` sudah berisi gambar dari pemilik (`aprove1@gmail.com`, 467 KB PNG) — tidak diubah/dihapus.
- Tanpa env/skema baru. Redeploy: frontend.

### Revisi posisi & ukuran (permintaan pemilik)
- Paraf dipindahkan dari ruang tanda tangan ke **baris nama approver**: dirender inline tepat setelah teks nama
  (`<span class="sign-name-text">…</span><img class="paraf-signature">`, `margin-left:2mm`, maks 22 × 8 mm),
  jadi posisinya tepat di sisi kanan huruf terakhir nama ("pas sebelah N nya").
- Stempel/TTD diperbesar: `max-width:60mm; max-height:21mm` (sebelumnya 40 × 13,8 mm; tampil nyata 28 × 21 mm atau ±1,5×),
  ditambatkan ke dasar ruang tanda tangan (`align-self:end; margin-bottom:3,5mm`) sehingga tumbuh ke atas dan
  menimpa label "Approved by," (disetujui pemilik) tanpa menimpa nama.
- `grid-auto-rows:14mm` ditambahkan pada `.sign-space` agar tinggi baris grid tidak ikut memanjang —
  tanpa ini `margin-bottom` tidak berpengaruh dan stempel menimpa nama.
- Verifikasi: test cetak PO 57/57; render Edge headless memakai gambar paraf + stempel asli dari produksi.

### Revisi kedua (mengikuti foto dokumen pemilik)
- Stempel/TTD kini **lapisan di belakang teks** yang menutupi seluruh blok tanda tangan, bukan hanya ruang 14 mm:
  `.signatures>div{position:relative}` + `.approved-signature{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);max-width:70mm;max-height:30mm;z-index:0}`.
- Label, nama, dan nama perusahaan diberi `position:relative;z-index:1` agar tetap terbaca di atas stempel.
- `.sign-space` kembali menjadi ruang kosong 14 mm (tanpa grid) — gambar tidak lagi memengaruhi tinggi baris, sehingga tidak ada risiko halaman meluber.
- Paraf tetap inline di baris nama (di kanan huruf terakhir) dan ikut berada di atas stempel.
- Verifikasi: test cetak PO 57/57; render Edge headless memakai gambar paraf + stempel asli dari produksi (tampilan sama seperti foto pemilik).

### Revisi ketiga (jarak baris nama–perusahaan)
- Baris nama dan nama perusahaan dirapatkan: `.sign-name` dan `.sign-company` memakai `line-height:1.2` (tanpa margin).
- Penyebab jarak sebelumnya: gambar paraf berupa inline image meninggikan line box nama. Sekarang paraf
  `position:absolute;left:100%;top:50%;translateY(-50%)` di dalam `.sign-name-wrap` (inline-block), sehingga
  tidak lagi menambah tinggi baris — nama & perusahaan rapat, paraf tetap menempel di kanan huruf terakhir nama.
- Verifikasi: test cetak PO 58/58 (asresi baru: paraf absolute + line-height 1.2); render Edge headless dengan
  gambar paraf + stempel asli dari produksi.

## Vendor Invoice: Faktur Pajak + Checklist Dokumen & Modul Transmittal (Status: COMPLETED — branch `feat/invoice-transmittal`)
- Permintaan pemilik: field Nomor/Tanggal Faktur Pajak, checklist kelengkapan 8 dokumen (multi-lampiran per jenis,
  status terpisah dari file digital), lalu modul **Transmittal Invoice** (Procurement) + integrasi ke daftar invoice.

### Tahap 1 — Vendor Invoice
- `backend/vendor_invoice_layer.py`: `tax_invoice_no`, `tax_invoice_date`, `doc_checklist` (8 kunci; nilai
  `Lengkap`/`Belum Lengkap`/`Tidak Berlaku`; nilai tak dikenal -> Belum Lengkap; data lama dinormalisasi).
  Endpoint baru `PUT /api/vendor-invoices/{id}/document-check` (hanya field dokumen, tidak menyentuh alokasi DO/DP/nilai),
  audit `document_check`, dan `files_by_category` (jumlah file per kategori) di detail.
- Frontend: `lib/docChecklist.js`, `components/invoice/DocChecklist.jsx` (status + upload multi-file per jenis + hapus),
  field baru di form & detail, ringkasan kelengkapan, serta kartu riwayat transmittal di detail invoice.

### Tahap 2 — Transmittal Invoice
- `backend/invoice_transmittal_layer.py`: koleksi `invoice_transmittals` + `invoice_transmittal_items` (snapshot vendor,
  no invoice, faktur pajak, PO, nilai, checklist), 11 endpoint, nomor otomatis `TRN/{tahun}/{bulan}/{seq}` (counter atomik).
- Status `Draft -> Dikirim -> Diterima | Dikembalikan`; guard invoice tidak boleh ada di dua transmittal aktif
  (409), transmittal non-Draft tidak dapat diubah/dihapus, kirim ulang setelah Dikembalikan tercatat sebagai transmittal baru.
- Cetak (`GET /{id}/print`) tidak mengubah status; penerimaan menyimpan waktu/user + bukti serah terima (opsional).
- Permission baru `transmittal.view/create/edit/delete/print/receive` (grup Keuangan) + default role
  Finance/Purchasing/Director/Manager; cakupan divisi mengikuti DO sumber invoice.
- Didaftarkan di `txn_list_paging_layer.LISTS` sehingga pencarian/filter/paginasi daftar berjalan di backend.

### Integrasi daftar invoice
- Kolom **No Faktur Pajak** (kanan No Invoice), **No. Transmittal** + link histori, **Status Transmittal**
  (`Belum Transmittal/Draft/Dikirim/Diterima/Dikembalikan`), filter status transmittal, checkbox multi-pilih +
  tombol **Buat Transmittal** (baris dengan transmittal aktif tidak dapat dipilih).
- Status transmittal TIDAK memengaruhi `payment_status`, `remaining`, maupun `settlement_status`.

### Pengujian
- `backend/invoice_transmittal_unit_test.py` → **38/38 lulus** (checklist, validasi tanggal, state machine, permission,
  11 route terdaftar). Tanpa database.
- `frontend/tests/transmittal_print_test.mjs` → **16/16 lulus** (isi cetak A4, tanda tangan pengirim/penerima, escaping).
- `CI=true yarn build` → OK; `py_compile` seluruh file backend → OK.
- Smoke read-only pada backend preview (data production): login admin, daftar invoice mengembalikan
  `transmittal_status`/`no`, `/invoice-transmittals` 200, `eligible-invoices` 200, `by-invoice` 200.
- `backend/invoice_transmittal_integrity_test.py` (HTTP, rantai MRO→RO→PO→DO→Invoice + transmittal) **belum dijalankan**:
  tidak tersedia database uji terpisah (user DB aplikasi hanya punya akses ke database `default`).
  Test siap dijalankan dengan `TEST_API_URL`/`ADMIN_EMAIL`/`ADMIN_PASSWORD` pada DB uji.

### Catatan
- Tidak mengubah logika PPN, DP, pembayaran, outstanding, MWA/HPP, maupun stock ledger.
- Tanpa env/skema baru (koleksi dibuat otomatis). Redeploy: backend lalu frontend.
- Data production: 2 invoice existing (12345, 123234) belum memiliki nomor faktur pajak; field tersedia untuk diisi.

---

## Redesign cetak Transmittal Invoice (mengikuti form manual PT REAL) — PR lanjutan

### Tujuan
Menyesuaikan layout cetak Transmittal Invoice dengan form manual PT REAL: kolom checklist kelengkapan
dokumen dikelompokkan (satu header "Checklist Kelengkapan" dengan 5 sub-kolom), memakai simbol
✓ / ✗ / −, logo perusahaan di atas nama perusahaan, dan format nilai ribuan memakai koma.

### Perubahan
- `frontend/src/lib/transmittalPrint.js`
  - Orientasi A4 **landscape**, `table-layout: fixed`.
  - Kolom: No | Nama Vendor | No. Invoice | No. Faktur Pajak | No. PO | Nilai (Inc PPN) |
    Checklist Kelengkapan (colspan 5: DO, Bukti Penerimaan Barang (PT. REAL), Kwitansi,
    BAST / Timesheet, Kontrak Kerja (Subcon)).
  - Export baru `PRINT_CHECKLIST` (5 item) dan `checklistMark()` → `Lengkap="✓"`, `Belum Lengkap="✗"`,
    `Tidak Berlaku="−"`.
  - Nilai diformat koma (`Intl.NumberFormat("en-US")`), mis. `1,000,000`.
  - Logo `<img class="logo">` dirender **di atas** `.company-name`; parameter baru `logoImg`.
  - Header info (tujuan/pengirim/penerima/status/jumlah/total), keterangan, tanda tangan pengirim &
    penerima, footer, dan `autoPrint` tetap seperti sebelumnya.
- `frontend/src/pages/InvoiceTransmittalForm.jsx`
  - Handler `print()` mengambil logo via `printImage(companyLogoPath(...))` lalu meneruskannya ke
    `openTransmittalPrint({ ...data, logoImg })`.
- `frontend/tests/transmittal_print_test.mjs`
  - Ditulis ulang mengikuti desain baru (22 asersi): kolom, 5 sub-kolom, simbol, urutan logo,
    format koma, landscape, escaping, dan ringkasan checklist.

### Pengujian
- `frontend/tests/transmittal_print_test.mjs` → **22/22 lulus** (esbuild bundle + node).
- `CI=true yarn build` → **OK (30,50 s)**.
- Tidak ada perubahan backend, env, maupun skema. Redeploy: **frontend saja**.

---

## Daftar Transmittal: aksi Edit/Hapus + Export Excel & PDF (1 atau massal)

### Tujuan
Melengkapi halaman daftar Transmittal Invoice: tombol **Ubah** dan **Hapus** per baris, serta **Export Excel**
dan **Export PDF** yang bisa memakai baris terpilih (1 atau banyak) maupun seluruh hasil filter.
Cetak/PDF tetap **A4 landscape** seperti form manual PT REAL.

### Perubahan
- `backend/reporting/reports_txn.py`
  - ReportSpec baru `txn-transmittal` (grup `hutang`, izin `transmittal.view`, `catalog=False`) memakai jalur daftar
    yang sama (`server.TXN_LIST_ROWS("transmittal", ...)`) -> cakupan tenant/divisi & filter identik dengan daftar.
  - Parameter `ids` (dipisah koma) membatasi export ke baris terpilih; kolom: No, Tanggal, Tujuan/Departemen,
    Pengirim, Penerima, Supplier, Jml Invoice, Total Nilai, Status.
- `backend/reporting/report_center.py`
  - `ids` tidak dimasukkan ke keterangan filter pada kop Excel/PDF (parameter pilihan baris, bukan filter pengguna).
- `frontend/src/components/ListExportButtons.jsx`
  - Prop opsional `formats` (default `["xlsx","pdf"]`) untuk menampilkan sebagian tombol; perilaku lama tidak berubah.
- `frontend/src/pages/InvoiceTransmittal.jsx`
  - Kolom **Aksi**: tombol Ubah (buka form) dan Hapus (konfirmasi) — hanya aktif untuk status **Draft** dan
    mengikuti izin `transmittal.edit` / `transmittal.delete` (backend tetap menolak non-Draft dengan 409).
  - Seleksi baris (checkbox) untuk export terpilih; tombol **Export Excel** (Pusat Laporan, `ids` bila ada pilihan)
    dan **Export PDF** (layout dokumen landscape, satu halaman per transmittal, maksimal 100 dokumen per ekspor).
- `frontend/src/lib/transmittalPrint.js`
  - `buildTransmittalMultiHtml` + `openTransmittalPrintMany`: beberapa transmittal dalam satu dokumen cetak
    (`break-before: page`), satu dialog cetak/print-to-PDF.
- `frontend/tests/transmittal_print_test.mjs` + `backend/invoice_transmittal_unit_test.py` diperluas.

### Pengujian
- `backend/invoice_transmittal_unit_test.py` -> **46/46 lulus** (termasuk registrasi `txn-transmittal`, izin,
  filter `ids` → 1 baris, tanpa `ids` → semua baris, jalur daftar transmittal).
- `frontend/tests/transmittal_print_test.mjs` -> **29/29 lulus** (termasuk multi-dokumen: 2 section, page break,
  satu `window.print`, escaping, landscape).
- `CI=true yarn build` -> **OK (25,26 s)**.
- Exporter Excel/PDF diuji dengan data sintetis: xlsx 6.378 byte, pdf 2.771 byte.
- Data nyata (read-only, tenant PT REAL): `TXN_LIST_ROWS("transmittal")` → **1 baris** `TRN/2026/10/00002`
  (FINANCE, febby→sella, PT. Profita Abadi, 1 invoice, **11.100.000**, Draft); `ids=<id>` → 1 baris;
  `ids=tidak-ada-id` → 0 baris; `f_status=Draft` → 1 baris. Endpoint daftar ber-halaman `{items:1,total:1}`,
  endpoint cetak mengembalikan 1 item + 8 kunci checklist + company. `_filters_applied` hanya memuat Status.
- Layout cetak dirender dari payload nyata dan diperiksa visual: landscape, 6 kolom identitas + grup
  Checklist Kelengkapan (5 sub-kolom), 5 tanda ✓, TOTAL 11,100,000, kolom tanda tangan.
- Tidak diuji: cetak fisik/pratinjau PDF di browser dengan sesi login; build image Docker.

### Catatan
- Tanpa env/skema baru. Redeploy: **backend lalu frontend**.
- Data production tidak diubah (semua verifikasi read-only; tidak ada export yang dijalankan ke server sehingga
  tidak ada baris audit baru).

---

## Kolom Status Dokumen pada daftar Invoice Vendor

### Tujuan
Menampilkan kelengkapan dokumen invoice langsung di daftar transaksi: **Lengkap** / **Belum Lengkap**.
Aturan yang diminta pemilik: dokumen berstatus **Tidak Berlaku** ikut dihitung lengkap — hanya dokumen
**Belum Lengkap** yang membuat status menjadi tidak lengkap.

### Perubahan
- `backend/vendor_invoice_layer.py`
  - Helper `doc_status_of(checklist)`: `Lengkap` bila tidak ada nilai `Belum Lengkap`
    (`Lengkap` dan `Tidak Berlaku` sama-sama dianggap selesai); selain itu `Belum Lengkap`.
  - `enrich()` mengisi `doc_status` untuk setiap baris invoice (dipakai daftar, ringkasan, export, dan filter).
- `frontend/src/pages/InvoiceMonitoring.jsx`
  - Kolom **Status Dokumen** (badge) setelah **Status Invoice**, dengan tooltip berisi daftar dokumen yang
    masih kurang; nilai memakai `doc_status` dari server (fallback hitung dari `doc_checklist`).
  - Filter **Semua Status Dokumen** (`f_doc_status`) — faset otomatis dari data.
  - `minWidth` 1950 -> 2080.
- `backend/reporting/reports_txn.py`
  - Laporan export `txn-invoice` menambah kolom **Status Dokumen** dan label parameter `f_doc_status`.
- `backend/invoice_transmittal_unit_test.py` — 6 asersi baru (aturan status + kolom export).

### Pengujian
- `backend/invoice_transmittal_unit_test.py` -> **53/53 lulus** (termasuk: tanpa checklist -> Belum Lengkap;
  semua Lengkap -> Lengkap; sebagian `Tidak Berlaku` -> tetap Lengkap; satu `Belum Lengkap` -> Belum Lengkap;
  seluruh `Tidak Berlaku` -> Lengkap; export `txn-invoice` memuat `doc_status`).
- `CI=true yarn build` -> **Compiled successfully (25,91 s)**.
- Data nyata, read-only, tenant PT REAL (58 invoice): distribusi **1 Lengkap / 57 Belum Lengkap**;
  `f_doc_status=Lengkap` -> 1 baris (invoice `4121`), `Belum Lengkap` -> 57 baris; faset `doc_status`
  mengembalikan kedua nilai; export `txn-invoice` dengan filter tersebut -> 1 baris + keterangan
  "Status Dokumen: Lengkap".
- UI lokal (dev 4200 + backend 4180, tenant uji 2 invoice): kolom **STATUS DOKUMEN** tampil dengan badge
  "Belum Lengkap" dan tooltip berisi 8 dokumen yang kurang; filter Status Dokumen tersedia dan pilihannya
  mengikuti data (hanya "Belum Lengkap" pada tenant tersebut).
- Tidak diuji: klik filter sampai memuat ulang untuk nilai `Lengkap` di UI (tenant uji tidak punya invoice lengkap).

### Catatan
- Tanpa env/skema baru; data production tidak diubah. Redeploy: **backend lalu frontend**.

---

## Nama Project pada daftar Approval 1

### Tujuan
Menampilkan **nama project** pada daftar inbox Approval 1 agar approver tahu konteks pekerjaan tiap dokumen
tanpa harus membuka dokumennya.

### Perubahan
- `backend/approval_email_layer.py`
  - `/api/approvals/inbox` memuat peta `projects` (id -> name/code) sekali per permintaan, lalu mengisi
    `project_id` dan `project_name` dari `default_project_id` dokumen (MRO/RO/PO).
- `frontend/src/pages/Approval.jsx`
  - Kolom **Project** setelah **Pemohon / Supplier**; nilai "-" bila dokumen tidak punya project.
  - Pencarian ikut mencocokkan nama project; `colSpan` baris kosong 9 -> 10; `min-w` tabel 1050 -> 1100.

### Pengujian
- `CI=true yarn build` -> **Compiled successfully (30,65 s)**.
- Data nyata read-only (tenant PT REAL, 32 approval task): **32/32 punya `project_name`**
  (OMSS 22, BALAI RAJA 4, EX.NK 2, NK 2, EW PPPRE 2).
- UI lokal (dev 4200 + backend 4180): kolom **PROJECT** tampil dan terisi "OMSS" pada 4 PO Pending;
  tabel tetap selebar container sehingga tombol Aksi tidak terpotong (lebar natural 1114 px).
- Tidak diuji: screenshot pada viewport mobile.

### Catatan
- Tanpa env/skema baru; data production tidak diubah (hanya membaca). Redeploy: **backend lalu frontend**.

---

## Penomoran PO: kode project + bulan Romawi

### Tujuan
Format nomor PO mengikuti form manual PT REAL: `PO/{kode project}/{seq}/{bulan Romawi}/{tahun}`, contoh
**PO/WUR-MD/193/VI/2026**. Kode project diambil otomatis dari project yang dipilih di header PO.

### Perubahan
- `backend/server.py`
  - `next_number(doc_type, project_id=None)` + `fill_number_format()`: placeholder baru `{project}`,
    `{roman_month}` (I–XII), dan `{seq:N}` (minimal N digit; `{seq}` tetap 5 digit seperti sebelumnya).
  - `project_number_code()`: `code` (fallback `name`) -> huruf besar, karakter selain A-Z/0-9 menjadi `-`,
    maksimal 24 karakter. Contoh `WUR MD` -> `WUR-MD`.
  - Dokumen tanpa project: segmen `{project}` dihapus tanpa menyisakan `//`.
  - `numbering_upgrade()` + `NUMBERING_VERSION = 2` + `PO_FORMAT_V2`.
- `backend/doc_procurement.py` — pembuatan PO mengirim `default_project_id` ke `next_number("PO", ...)`.
- `backend/production_bootstrap.py` — default PO baru untuk tenant baru + migrasi ber-versi: hanya
  menaikkan PO yang masih default lama; format yang sudah dikustom pengguna TIDAK ditimpa.
- `backend/saas_platform_layer.py` — default tenant baru memakai format PO v2 + `numbering_version: 2`.
- `backend/numbering_unit_test.py` (baru) — 30 asersi tanpa database.
- `frontend/src/pages/Settings.jsx` — hint placeholder di tab Penomoran (`{roman_month}`, `{seq:3}`, `{project}`).

### Pengujian
- `backend/numbering_unit_test.py` -> **30/30 lulus**: `PO/WUR-MD/193/VI/2026`, `{seq:3}` (007), tanpa project
  (`PO/193/VI/2026`), format lama tetap 5 digit, bulan I/XII/VIII, kode project (spasi/karakter khusus/batas 24),
  `next_number` dengan DB palsu (project dibaca hanya bila `{project}` ada), dan migrasi ber-versi
  (default lama -> v2, custom tidak ditimpa, idempoten).
- `backend/invoice_transmittal_unit_test.py` -> **53/53 lulus** (regresi server.py aman).
- `CI=true yarn build` -> **Compiled successfully (54,26 s)**.
- Baseline produksi (read-only): `tenant-pt-real` sudah memakai format v2 dari uji lokal; `numbering_version`
  belum ada -> setelah deploy migrasi akan menyetel `numbering_version: 2` (bukti backend baru berjalan).

### Catatan
- Nomor dokumen lama tidak berubah (hanya dokumen baru memakai format baru).
- Sequence tetap penghitung bulanan per jenis dokumen (global per tenant), bukan per project.
- Redeploy: **backend lalu frontend**. Tanpa env baru.

---

## Label "No Invoice (Opsional)" pada form Penerimaan Barang (DO)

### Tujuan
Istilah pada form Penerimaan Barang disamakan: field `supplier_invoice` berlabel **No Invoice (Opsional)**
(sebelumnya "No. Faktur (opsional)"), agar tidak tertukar dengan Faktur Pajak.

### Perubahan
- `frontend/src/pages/Do.jsx` — label Field `supplier_invoice` pada form DO baru/ubah.

### Pengujian
- `CI=true yarn build` -> **Compiled successfully (30,19 s)**.
- UI lokal (`/do/new`): label terbaca **NO INVOICE (OPSIONAL)**; tidak ada perubahan pada nilai yang disimpan
  (tetap `supplier_invoice`) maupun API.
- Tidak diuji: daftar DO masih memakai judul kolom "No. Faktur" (di luar permintaan; dapat disamakan bila diminta).

### Catatan
- Redeploy: **frontend saja**. Tanpa env/skema/data.

---

## Cetak PO: tanpa header/footer browser + DPP Nilai Lain dibulatkan

### Tujuan
1. Menghilangkan baris kecil di atas kertas PO (tanggal/jam, nomor PO) dan baris bawah (URL `about:blank`, `1/1`) —
   keduanya header/footer bawaan browser saat mencetak.
2. Nilai **DPP Nilai Lain** dicetak tanpa desimal (dibulatkan ke rupiah).

### Perubahan
- `frontend/src/lib/poPrintReal.js`
  - `@page{size:...;margin:0}` + `@media print{.sheet{padding:<margin layout>;min-height:<tinggi kertas>}}`
    (pola yang sudah dipakai cetak DO). Dengan margin halaman 0, Chrome tidak lagi menggambar header/footer
    bawaan; margin dokumen tetap sesuai Layout Dokumen karena dipindah ke padding sheet.
  - Pratinjau layar tetap memakai `body{padding:<margin>}` sehingga tampilan tidak berubah.
  - Baris ringkasan `dpp_other` dan kolom **DPP Nilai Lain** pada tabel rincian pajak memakai `fmtIdr0`.
- `frontend/src/lib/poTaxPrint.js` — helper baru `fmtIdr0` (rupiah tanpa desimal, `Math.round`).
- `frontend/src/components/po/PoTaxV2.jsx` — DPP Nilai Lain pada detail baris, ringkasan, dan tabel kelompok
  ikut dibulatkan (konsisten dengan cetak).
- Test: `tests/po_print_margin_test.mjs` (53 asersi) dan `tests/po_print_real_test.mjs` (58 asersi) disesuaikan
  dengan pola `@page margin 0 + padding sheet`.

### Pengujian
- `tests/po_print_margin_test.mjs` -> **53/53 lulus**; `tests/po_print_real_test.mjs` -> **58/58 lulus**;
  `tests/po_dp_print_test.mjs` -> **15/15 lulus**.
- `CI=true yarn build` -> **Compiled successfully (23,91 s)**.
- `src/lib/poTaxV2.test.mjs` tidak dapat dijalankan dari akar `frontend` (harness memuat file via path relatif —
  masalah lama, bukan akibat perubahan ini).

### Catatan
- Perubahan hanya presentasi (margin & format angka); nilai tersimpan (DPP, PPN, grand total) tidak diubah.
- PO multi-halaman: halaman ke-2 dst. tidak lagi memiliki margin atas/bawah dari browser (konsekuensi
  menghilangkan header/footer) — sama seperti cetak DO saat ini.
- Redeploy: **frontend saja**.

---

## Traceability: rantai sampai Invoice & Pembayaran + tanggal tiap transaksi

### Tujuan
1. Rantai traceability diperpanjang: **MRO → RO → PO → DO → MI → Invoice → Pembayaran**.
2. Setiap kartu tahap menampilkan **tanggal transaksi** di bawah nomor dokumen (Invoice juga menampilkan nilai).

### Perubahan
- `backend/doc_reports.py` — `/api/traceability/{mro_id|no}`:
  - Node RO/PO/DO/MI kini membawa `date` (sebelumnya hanya `id` + `no`).
  - Invoice dicari dari `vendor_invoices.do_ids` yang beririsan dengan DO pada rantai
    (`no` = nomor invoice vendor, `internal_no`, `date` = `invoice_date`, `amount`, `status`).
  - Pembayaran dari `vendor_invoice_payments` berstatus `Aktif` untuk invoice tersebut
    (`no` = referensi pembayaran, `date`, `amount`, `invoice_no`), diurutkan menurut tanggal.
- `frontend/src/pages/Traceability.jsx`
  - Tahap **INVOICE** dan **PEMBAYARAN** ditambahkan pada rantai; kartu invoice dapat diklik ke detail invoice.
  - Tanggal (`fmtDate`) tampil di bawah setiap nomor; nilai (`rupiah`) tampil untuk invoice & pembayaran.
  - Subjudul halaman diperbarui.

### Pengujian
- Read-only data nyata (tenant PT REAL):
  - MRO `3654` → RO/2026/10/00009 (23-10-2026), PO/2026/10/00010 (26-10-2026), DO/2026/10/00007 (26-10-2026),
    MI 0, **INVOICE 1** `675-673` (26-10-2026, Rp 33.300, Belum Dibayar), PAYMENT 0.
  - MRO ber-invoice dibayar: `INV-002` (01-06-2026, Rp 12.000.000, Dibayar Sebagian) + pembayaran
    `TRF-1` (10-06-2026, Rp 5.000.000) dan `TRF-3` (13-06-2026, Rp 1.000); MRO lain `INV-001` + `OV`.
- `CI=true yarn build` -> **Compiled successfully (24,42 s)**.
- Tidak ada perubahan skema/env; read-only (tidak ada baris DB ditulis). Redeploy: backend lalu frontend.

---

## Semua nilai rupiah pada PO dibulatkan (tanpa desimal)

### Tujuan
Nilai pada dokumen PO (Amount/DPP/DPP Nilai Lain/PPN/Grand Total, termasuk ringkasan di layar) tidak lagi
menampilkan desimal — dibulatkan ke rupiah.

### Perubahan
- `frontend/src/lib/poTaxPrint.js` — `fmtIdr` memakai `maximumFractionDigits: 0` + `Math.round`
  (formatter bersama untuk form, detail, dan cetak PO). Helper `fmtIdr0` dihapus karena menjadi duplikat.
- `frontend/src/lib/poPrintReal.js` — `idrPlain` (PO v1 & kolom harga/diskon) juga dibulatkan; kolom
  DPP Nilai Lain memakai `fmtIdr`.
- `frontend/src/components/po/PoTaxV2.jsx` — memakai `fmtIdr` (tanpa `fmtIdr0`).
- Test: `src/lib/poTaxV2.test.mjs` (ekspektasi `916.667`) dan `tests/po_print_real_test.mjs`
  (Nilai Sebelum PPN Include `892.857`) disesuaikan.

### Pengujian
- `tests/po_print_real_test.mjs` -> **58/58**; `tests/po_print_margin_test.mjs` -> **53/53**;
  `tests/po_dp_print_test.mjs` -> **15/15**.
- `CI=true yarn build` -> **Compiled successfully (22,26 s)**.
- `src/lib/poTaxV2.test.mjs` tidak dapat dijalankan di Windows (harness lama memakai `import()` dengan path
  Windows -> `ERR_UNSUPPORTED_ESM_URL_SCHEME`); ekspektasi angka sudah disesuaikan.
- Nilai tersimpan (DPP/PPN/grand total) tidak diubah; hanya format tampilan/cetak. Redeploy frontend saja.

---

## 2026-10-29 — PO: nama project pada dialog "Tarik RO"

### Tujuan
Saat Tarik RO di transaksi PO, baris kebutuhan RO menampilkan nama project. Bila satu RO memakai lebih dari
satu project (header + baris berbeda), semua nama project ditampilkan dan dipisah koma.

### Perubahan
- `backend/pull_source_eligibility_layer.py` — `_ro_rows` menambahkan field `project_names` per baris:
  agregasi `default_project_id` header RO + `project_id` seluruh baris RO, unik dan urut, di-resolve dari
  `maps()["projects"]` (fallback `code` tidak dipakai; konsisten dengan `enrich_line` yang memakai `name`).
- `frontend/src/components/po/PoRoSplit.jsx` — kolom **Project** setelah **Divisi**
  (`data-testid="po-ro-project-<ro_no>-<item_code>"`), nilai `project_names || project_name || "-"`;
  teks pencarian dialog menyertakan project; `min-w` tabel 1450px -> 1600px.

Catatan: `doc_procurement.pull_ro_for_po` bukan implementasi live — `pull_source_eligibility_layer.install()`
menghapus route `/api/pull/ro-for-po` lalu mendaftarkan `_ro_rows`; karena itu perubahan hanya di layer tersebut.

### Pengujian
- Payload live via rantai route aplikasi (`_resolve_current` tanpa dokumen aktif): **18 baris**, **13 RO unik**,
  13/13 punya `project_names`; **2 RO multi-project** -> `RO/2026/10/00010 = "OMSS, WUR-MD"`,
  `RO/2026/10/00027 = "EW PPPRE, WUR MD"`; RO pada screenshot `RO/2026/10/00019` & `RO/2026/10/00021` = `EW PPPRE`.
- `CI=true yarn build` -> **Compiled successfully / Done in 59,44 s**.
- Tidak ada perubahan skema/DB, tidak ada env baru; murni aditif (field tambahan pada respons).

---

## 2026-10-29 — Master Barang: status "Tanpa Stok" (jasa/sewa/perizinan)

### Tujuan
Memisahkan barang jasa/sewa/perizinan dari hitungan status stok, tanpa mengubah proses transaksi.
Barang bertanda **Tanpa Stok** tidak lagi dihitung sebagai Stok Habis / Stok Menipis / Overstock dan punya
hitungan sendiri. MRO/RO/PO/DO tetap berjalan seperti biasa.

### Perubahan
- `backend/stock_summary.py` (sumber tunggal Master Barang, Inventory, Dashboard):
  status baru `Without Stock`; field master `without_stock` -> `item_status(..., without_stock=True)`;
  `SUMMARY_KEY`/`STATUS_RANK`/`STATUSES` diperluas; ringkasan menambah key `without_stock` (terpisah dari
  `no_stock` = belum ada catatan stok) dan `no_stock` tidak lagi menghitung barang bertanda;
  `dashboard_stock` menyertakan `without_stock`.
- `backend/master_auto.py` — `_normalize_item` menormalkan `without_stock` menjadi boolean.
- `backend/tests/master_item_stock_test.py` — blok uji Tanpa Stok (flag, ringkasan, filter, lepas flag).
- `frontend/src/pages/MasterData.jsx` — checkbox **Tanpa Stok** di form Tambah/Edit Barang + keterangan.
- `frontend/src/components/master/ItemStockTab.jsx` — kartu ke-5 **Tanpa Stok** (grid 5 kolom), badge status,
  catatan "Belum ada catatan stok" tidak ditampilkan untuk barang bertanda.
- `frontend/src/pages/Inventory.jsx` — kartu ke-5 **Tanpa Stok**, filter status `Without Stock` diterima.
- `frontend/src/components/StatusBadge.jsx` — label/warna `Tanpa Stok`.

Tanpa skema/DB baru (field hanya tersimpan di dokumen item), tanpa env baru, tidak ada perubahan alur transaksi.

### Pengujian
- Verifikasi read-only pada data nyata (simulasi penandaan di memori, tanpa menulis ke DB): **21/21 cek lulus** —
  9.297 barang aktif, `without_stock` = 0 sebelum; simulasi 3 barang bertanda -> `out_of_stock` 8998 -> 8995
  (turun tepat 3), `no_stock` 8997 -> 8994, `total` tetap 9.297, status/filter/sort `Without Stock` benar,
  blok `stock` dashboard memuat `without_stock`, normalisasi `"true"/"false"/None` benar.
- `py_compile` untuk `stock_summary.py`, `master_auto.py`, `tests/master_item_stock_test.py` -> OK.
- `CI=true yarn build` -> **Compiled successfully (24,54 s)**.
- Belum dijalankan: `backend/tests/master_item_stock_test.py` (butuh backend uji + tenant QA sementara; tidak tersedia
  di laptop ini) — blok uji Tanpa Stok ditambahkan agar ikut jalan pada harness repo.

---

## 2026-10-29 — Import Excel Master Barang: kolom `without_stock` (Tanpa Stok)

### Tujuan
Template impor Master Barang belum bisa menetapkan status **Tanpa Stok** (jasa/sewa/perizinan) secara massal.
Kolom `without_stock` ditambahkan ke template & parser agar status bisa diisi via Excel.

### Perubahan
- `backend/excel_import_layer.py`
  - `MASTER_DATASETS["items"]["columns"]` + `"without_stock"` (kolom terakhir, **opsional**, tidak masuk `required`);
    contoh baris di template = `Tidak` (barang pakai stok).
  - `_parse_without_stock(v)` -> `(nilai, valid)`: `Ya/Tanpa Stok/1/true` -> True; `Tidak/Pakai Stok/0/false` -> False;
    sel kosong / kolom tidak ada -> `None` (nilai item **tidak diubah**, insert default pakai stok);
    nilai lain -> `valid=False` sehingga import berhenti dengan pesan `Baris N: without_stock harus Ya ... atau Tidak ...`
    (impor bersifat all-or-nothing, tidak ada baris setengah tersimpan).
  - Header alternatif `tanpa_stok` juga diterima.
  - Sheet `Petunjuk` menjelaskan kolom baru.
- Tidak ada perubahan frontend: halaman Import Excel membaca spesifikasi dari `/api/excel/datasets`,
  dan template diunduh dari `/api/excel/template/items`.

Kompatibilitas: template lama (11 kolom, tanpa `without_stock`) tetap lolos `_check_headers` dan **tidak mengubah**
status tanpa stok barang yang sudah ada.

### Pengujian
- Verifikasi read-only **17/17 cek lulus**: header template `items` = spec (12 kolom, contoh 12 nilai), kolom
  `without_stock` ada & tidak wajib, Petunjuk memuat penjelasan, parser 15 kasus (termasuk menolak nilai tak dikenal
  dan menerima `Tanpa Stok`/`Pakai Stok`), template lama tetap diterima, file `template_items.xlsx` milik pemilik
  tetap terbaca dan barisnya tidak memuat key `without_stock`.
- `py_compile backend/excel_import_layer.py` -> OK.
- Tanpa perubahan frontend, tidak perlu build ulang; tanpa skema/DB baru, tanpa env baru.

---

## 2026-10-29 — Transmittal Invoice: kolom PO & DO kosong

### Masalah
Halaman detail Transmittal Invoice menampilkan "-" pada kolom **PO** dan **DO** walaupun invoice sumber punya DO/PO.
Contoh nyata (produksi, transmittal `d97a4aa7-bcff-4394-a270-7e9952fa671c`): invoice `434666` punya
`DO/2026/10/00003` -> `PO/2026/10/00002`, tetapi item transmittal tersimpan `po_nos: ""`, `do_nos: ""`.

### Akar masalah
`invoice_transmittal_layer.snapshot()` membaca `inv["trace_po"]` dan `inv["do_nos"]` seolah tersimpan di dokumen
invoice. Kenyataannya kedua field itu **dihitung saat baca** oleh `vendor_invoice_layer.enrich()` (dari DO), tidak
pernah dipersistensikan — sehingga selalu kosong. `eligible_invoices()` punya bug yang sama.

### Perbaikan (backend saja)
- `invoice_transmittal_layer.py` — helper `trace_map(invs)`: hitung No DO + PO per invoice dari `do_ids` memakai
  sumber yang sama dengan daftar invoice (`receipt_control_layer.enrich_list`).
- `snapshot()` memakai `trace_map` -> transmittal baru menyimpan PO/DO yang benar.
- `detail()` (dipakai juga oleh cetak/print) melengkapi item lama yang `po_nos`/`do_nos` masih kosong saat dibaca —
  **tanpa menulis DB** (tanpa migrasi/backfill).
- `eligible_invoices()` memakai `trace_map` -> daftar pilihan invoice juga menampilkan PO/DO.

Frontend tidak diubah (sudah membaca `i.po_nos` / `i.do_nos`). Tanpa skema/DB baru, tanpa env baru, tanpa perubahan
angka/nilai invoice, pembayaran, atau stok.

### Pengujian
- Read-only lewat rantai route aplikasi (data nyata): transmittal `d97a4aa7-…` ->
  DETAIL `po_nos = PO/2026/10/00002`, `do_nos = DO/2026/10/00003`; PRINT sama; `eligible-invoices` 57/57 baris
  ber-PO/DO (sebelumnya kosong).
- Baseline production sebelum deploy: 2 invoice ber-DO (`PO/2026/10/00054` + `DO/2026/10/00004`,
  `PO/2026/10/00047` + `DO/2026/10/00002`) tetapi `eligible` masih `po_nos: ""`, `do_nos: ""` -> dipakai sebagai
  sinyal verifikasi setelah deploy.
- `py_compile backend/invoice_transmittal_layer.py` -> OK.
- Belum dijalankan: `backend/invoice_transmittal_integrity_test.py` (butuh backend uji + DB terpisah).

---

## 2026-10-29 — Menu Approval: kolom Termin Pembayaran

### Tujuan
Daftar Approval belum menampilkan termin pembayaran, padahal approver perlu melihatnya saat menyetujui PO.

### Perubahan
- `backend/approval_email_layer.py` — `/api/approvals/inbox` menambahkan field `payment_term` pada setiap baris
  (diambil dari dokumen; hanya PO yang punya nilai — modul lain `None`).
- `frontend/src/pages/Approval.jsx` — kolom **Termin Pembayaran** setelah Project
  (`data-testid="approval-term-<no dokumen>"`), nilai `payment_term || "-"`; teks pencarian menyertakan termin;
  `colSpan` 10 -> 11; lebar minimum tabel 1100px -> 1240px.

Tanpa skema/DB baru, tanpa env baru, aditif (respons hanya bertambah satu field). Nilai ditampilkan apa adanya
sesuai yang diisi di PO (mis. `Net 120`, `Cash on Delivery`) — tidak ada perubahan/normalisasi data.

### Pengujian
- Read-only lewat rantai route aplikasi (data nyata): inbox **60 baris**, semua punya key `payment_term`;
  **56 terisi**, contoh nilai `Net 120`, `30`, `Net 60`, `Cash on Delivery`; PO tanpa termin tampil "-".
- `CI=true yarn build` -> Compiled successfully (27,39 s).
- Tidak ada pemakaian baru field ini di tempat lain; penambahan key tidak mengubah bentuk respons lama.

---

## 2026-10-29 — Cetak Transmittal Invoice disamakan dengan form manual PT REAL

### Tujuan
Desain cetak/PDF Transmittal disesuaikan dengan form manual "Pengiriman Transmittal Invoice" milik pemilik
(lampiran gambar), termasuk kolom **No DO SUPLIER** dan grup **Item Pemeriksaan Kelengkapan**.

### Perubahan (`frontend/src/lib/transmittalPrint.js`, berlaku untuk cetak satuan & export PDF massal)
- Kop: kiri logo + nama + alamat perusahaan; kanan 3 baris **Pengiriman Transmittal Invoice** /
  **Vendor Proyek PHR** (teks tetap sesuai keputusan pemilik) / **Tanggal : dd Bulan yyyy**, plus
  **No : <nomor transmittal>** dengan ukuran font normal.
- Info 2 kolom sesuai form: kiri **Tujuan / Departemen**, **Penerima**; kanan **Pengirim**, **Total Invoice**
  = **jumlah invoice** (bukan nominal). Baris "Status" dan "Total Nilai" dihapus.
- Tabel 2 baris header: `No | Nama Vendor | No. Invoice | No. Faktur Pajak | No. PO |
  [Item Pemeriksaan Kelengkapan: Bukti Penerimaan Barang (PT. REAL)✓ | No DO SUPLIER | Nilai (Inc PPN)] |
  Kwitansi✓ | BAST / Timesheet✓ | Kontrak Kerja (Subcon)✓`.
  Kolom **No DO SUPLIER** berisi nomor DO (bukan tanda ✓) — memanfaatkan perbaikan PO/DO sebelumnya.
- Minimal **7 baris bernomor** (baris kosong ditambahkan bila invoice kurang), **tanpa baris TOTAL** nominal.
- Blok **Keterangan** hanya muncul bila catatan diisi.
- Tanda tangan: **Dikirim Oleh,** / **Diterima Oleh,** dengan **Nama :** dan **Tanggal :**.
- `PRINT_CHECKLIST` kini 4 tanda ✓ (`bukti_penerimaan`, `kwitansi`, `bast`, `kontrak`); konstanta `MIN_ROWS = 7`.

### Pengujian
- `frontend/tests/transmittal_print_test.mjs` diperbarui -> **39/39 lulus** (kop, info, kolom, grup header,
  simbol ✓/✗/−, 7 baris, tanpa total, keterangan opsional, tanda tangan, A4 landscape, autoPrint, escaping,
  multi-dokumen 2 halaman x 7 baris).
- Render HTML dari payload produksi nyata (`TRN/2026/10/00005`, invoice 434666, PO/2026/10/00002,
  DO/2026/10/00003, Rp 5.350.000) -> tampilan sesuai lampiran (bukti: `transmittal-print-new.png`).
- `CI=true yarn build` -> Compiled successfully (30,78 s).

---

## 2026-10-29 — Cetak Transmittal: No DO Sistem & No. DO Supplier (surat jalan) + kolom tanda tangan manual

### Tujuan (permintaan pemilik)
1. Kolom **"Bukti Penerimaan Barang (PT. REAL)"** diganti **"No DO Sistem"** — diambil dari nomor DO sistem.
2. Kolom **"No DO SUPLIER"** diganti **"No. DO Supplier"** — diambil dari **nomor surat jalan** supplier.
3. **Pengirim**, **Penerima**, serta **Nama** & **Tanggal** pada blok tanda tangan **dikosongkan** (diisi manual setelah dicetak).

### Perubahan
- `backend/invoice_transmittal_layer.py`
  - `trace_map()` menambah `do_supplier_nos` = `supplier_dn` DO terkait (nomor surat jalan supplier).
  - `snapshot()` menyimpan `do_supplier_nos`; `detail()` melengkapi transmittal lama saat dibaca (tanpa menulis DB).
    Fallback PO/DO dirapikan: hanya mengisi field yang masih kosong.
- `frontend/src/lib/transmittalPrint.js`
  - Header kolom 6 = **No DO Sistem** (isi `do_nos`), kolom 7 = **No. DO Supplier** (isi `do_supplier_nos`).
  - Grup **Item Pemeriksaan Kelengkapan** tetap mencakup 3 kolom tersebut.
  - `PRINT_CHECKLIST` kini 3 tanda ✓ (`kwitansi`, `bast`, `kontrak`) — `bukti_penerimaan` tidak lagi dicetak
    (sudah diwakili No DO Sistem).
  - Info: nilai **Pengirim** dan **Penerima** dikosongkan (label tetap).
  - Tanda tangan: **Dikirim Oleh,** / **Diterima Oleh,** + **Nama :** dan **Tanggal :** keduanya kosong.
- `frontend/tests/transmittal_print_test.mjs` — ekspektasi disesuaikan.

Tanpa skema/DB baru, tanpa env baru. Perilaku transaksi/status tidak berubah (murni tampilan cetak).

### Pengujian
- `frontend/tests/transmittal_print_test.mjs` -> **44/44 lulus** (termasuk: label kolom baru, `No DO Sistem` =
  `DO/2026/10/00003`, `No. DO Supplier` = `121336`, kolom lama sudah tidak ada, Pengirim/Penerima & Nama/Tanggal
  kosong, 7 baris, tanpa total, escaping, multi-dokumen).
- Backend lewat rantai route aplikasi (data nyata, read-only): payload cetak `TRN/2026/10/00005` memuat
  `do_nos = DO/2026/10/00003` dan `do_supplier_nos = 121336`.
- Render HTML dari payload produksi nyata -> sesuai permintaan (bukti: `transmittal-print-v2.png`).
- `py_compile backend/invoice_transmittal_layer.py` -> OK; `CI=true yarn build` -> Compiled successfully (106,21 s).

---

## 2026-10-29 — Cetak Transmittal: hilangkan header/footer browser & rapikan proporsi

### Tujuan (permintaan pemilik)
1. Hapus teks kecil di atas hasil cetak (tanggal/jam browser, nomor dokumen, dan "about:blank") — itu header/footer
   bawaan browser, bukan bagian template.
2. Angka **Total Invoice** terlalu jauh ke kanan -> didekatkan ke label.
3. Font blok info (Tujuan/Departemen, Pengirim, Penerima, Total Invoice) ukuran **standar 12px**.
4. Blok tanda tangan (Dikirim/Diterima + Nama/Tanggal) **di tengah** agar proporsional.

### Perubahan (`frontend/src/lib/transmittalPrint.js`)
- `@page` margin `10mm` -> **0**, dan margin isi dipindah ke `.doc{padding:10mm}`. Dengan margin halaman 0, Chrome tidak
  lagi mencetak header/footer otomatis (tanggal/jam, judul dokumen, URL `about:blank`), sementara isi tetap punya
  margin 10mm. Cetak tunggal kini juga dibungkus `<section class="doc">` agar margin berlaku per halaman
  (export PDF massal = 1 halaman per transmittal).
- `.info` -> `font-size:12px`; setiap baris memakai `display:flex` sehingga nilai langsung mengikuti label
  (`Total Invoice : 1`), tidak lagi di kolom 38mm.
- `.signs .box` -> `text-align:center` (sebelumnya rata kiri dengan padding 10mm).
- Layar: latar abu + `.doc` putih (pratinjau lebih jelas); tidak memengaruhi hasil cetak.

### Pengujian
- `frontend/tests/transmittal_print_test.mjs` -> **48/48 lulus** (termasuk cek `@page{...margin:0}`,
  `.doc{padding:10mm}`, info 12px + flex, tanda tangan center, satu dokumen dibungkus `.doc`).
- Render HTML dari payload produksi nyata (`TRN/2026/10/00005`) dengan emulasi media cetak -> sesuai permintaan
  (bukti: `transmittal-print-v3.png`).
- `CI=true yarn build` -> Compiled successfully (25,11 s).

---

## 2026-10-29 — Cetak Transmittal: model header tabel disamakan dengan lampiran

### Tujuan (permintaan pemilik)
Header tabel cetak dibuat persis seperti lampiran: satu grup **Item Pemeriksaan Kelengkapan** mencakup **seluruh
kolom detail** (bukan hanya 3 kolom).

### Perubahan (`frontend/src/lib/transmittalPrint.js`)
- Baris 1 header: **No** & **Nama Vendor** (`rowspan="2"`) + **Item Pemeriksaan Kelengkapan** (`colspan="9"`).
- Baris 2 header: `No. Invoice | No. Faktur Pajak | No. PO | No DO Sistem | No. DO Supplier | Nilai (Inc PPN) |
  Kwitansi | BAST / Timesheet | Kontrak Kerja (Subcon)`.
- Lebar kolom disesuaikan proporsi lampiran: No 10mm, Nama Vendor 38mm, No. Invoice 27mm, No. Faktur Pajak 29mm,
  No. PO 28mm, No DO Sistem 28mm, No. DO Supplier 32mm, Nilai 24mm, Kwitansi 13mm, BAST 13mm, Kontrak 16mm.
- Isi baris tidak berubah (urutan kolom sama), jadi data tetap sejajar.

### Pengujian
- `frontend/tests/transmittal_print_test.mjs` -> **49/49 lulus** (tambah cek: grup `colspan="9"`,
  hanya `No` & `Nama Vendor` yang `rowspan="2"`, seluruh sub-kolom ada di baris ke-2).
- Render HTML dari payload produksi nyata (`TRN/2026/10/00005`) dengan emulasi media cetak -> header sesuai lampiran
  (bukti: `transmittal-print-v4.png`).
- `CI=true yarn build` -> Compiled successfully (31,99 s).

---

## 2026-10-29 — Laporan MRO Traceability: kolom invoice (tanggal, no, qty, total)

### Tujuan (permintaan pemilik)
Menambah 4 kolom invoice pada laporan **MRO Traceability** di Pusat Laporan, tepat setelah
**Total DO (DPP x Qty Diterima)**: **Tanggal Invoice, No. Invoice, Qty Invoice, Total Invoice**.

### Perubahan (`backend/report_trace_detail.py`, `backend/reporting/reports_procurement.py`)
- Helper `_po_unit_dpp(po_line)` — DPP per unit baris PO (snapshot `dpp`, fallback gross - diskon,
  tax-inclusive dinormalkan). Rumus sama dengan Total DO laporan.
- Helper `_attach_invoices(server, rows, show_financial)` — menghitung 4 kolom invoice per baris MRO x barang dari
  DO yang sudah ditelusuri (`_do_qty`):
  - nilai DO = SUM(DPP per unit x qty diterima); qty DO = SUM(qty diterima)
  - `billed` = alokasi invoice per DO (`vendor_invoice_allocations`), fallback `amount` invoice bila invoice hanya 1 DO
  - **Qty Invoice** = qty baris pada DO x min(1, alokasi DO / nilai DO). Invoice di aplikasi ini menagih **DO**
    (nominal, tanpa qty), jadi qty diturunkan proporsional dari data existing — bukan angka baru.
  - **Total Invoice** = porsi nilai invoice untuk DO x (qty baris / qty DO), dengan
    porsi = alokasi DO / total alokasi invoice x `amount` invoice. Normalisasi ke `amount` perlu karena alokasi
    tersimpan sebagai DPP sementara `amount` invoice termasuk pajak, sehingga jumlah seluruh baris untuk satu
    invoice = nilai invoice.
  - Tanpa izin `view_purchase_price` -> `inv_total = None` (kolom otomatis disembunyikan `ReportSpec.visible_columns`).
- Excel export: 4 header + 4 nilai baru; `money_cols` menambah 26 (Total Invoice); `qty_cols` menambah 25
  (Qty Invoice); lebar kolom 31 entri.
- ReportSpec `mro-traceability`: 4 `Column` baru (`inv_date`, `inv_no`, `qty_invoice`, `inv_total`) setelah
  `do_total`; `inv_total` bertanda `price=True` + `total=True`; `search_keys` menambah `inv_no`.

### Pengujian (data produksi, read-only)
- Builder: **368 baris**; **80 baris** ber-invoice (16 nomor invoice unik).
- Kasus acuan `DO/2026/10/00003` -> invoice `434666`:
  2.377.777,78 + 1.188.888,89 + 1.783.333,33 = **5.350.000,00** (= nilai invoice).
- Invarian level DO: **74 DO ber-invoice, 0 selisih** antara jumlah Total Invoice baris dan porsi nilai invoice DO.
- Tanpa izin harga: 80/80 baris `inv_total = None`, `qty_invoice` tetap terisi.
- `py_compile` kedua file: OK; `report-center` rows memuat 4 key invoice.
- `backend/tests/p7_trace_batch_test.py` (T5) tetap aman: query baru bersifat batch/konstan (4 query), bukan per baris.

### Revisi (permintaan pemilik) — Total Invoice memakai **DPP**
- Basis `Total Invoice` diubah dari `amount` invoice (termasuk pajak) menjadi **`dpp` invoice**:
  porsi = alokasi DO / total alokasi invoice x DPP invoice. Alokasi hanya menentukan pembagian antar DO.
- `dpp` diambil dari field invoice: `dpp` -> `amount - tax_amount` -> `amount` (fallback untuk data lama).
- Rasio qty ikut dinormalkan ke DPP (`faktor = dpp / amount`) agar qty dan nilai konsisten saat alokasi
  tersimpan termasuk pajak.
- Bukti data produksi: invoice `4121` (amount 11.100.000, dpp 10.000.000) -> **10.000.000**;
  `675-673` (33.300 / 30.000) -> **30.000**; `456-0976` (7.881.000 / 7.100.000) -> **7.100.000**;
  `434666` (5.350.000, tanpa pajak) -> **5.350.000** (tidak berubah).
- Invarian level DO: **74 DO ber-invoice, 0 selisih** (jumlah baris = Σ porsi DPP invoice per DO).

---

## 2026-10-29 — Laporan MRO Traceability: kolom No. SPK

### Tujuan (permintaan pemilik)
Menampilkan **No. SPK** pada laporan MRO Traceability, kolom **setelah Satuan**. Jika satu item memakai lebih dari
satu SPK, semuanya digabung dalam satu kolom dan dipisahkan **koma**.

### Perubahan (`backend/report_trace_detail.py`, `backend/reporting/reports_procurement.py`)
- `trace_batch()` memuat batch `procurement_item_spk_allocations` (`source_type="mro"`) + dokumen `spk`
  (2 query batch tambahan; tetap konstan, bukan per baris).
- `_build_rows()` mengumpulkan nomor SPK per baris MRO x barang dari alokasi SPK baris MRO (hanya qty > 0),
  di-dedupe, diurutkan, lalu di-join dengan `", "` ke `spk_no`.
- `_flat()` + ReportSpec `mro-traceability`: kolom baru **No. SPK** (`spk_no`) tepat setelah **Satuan**;
  `search_keys` menambah `spk_no` (pencarian berdasarkan no SPK).
- Excel export: header & nilai **No. SPK** di kolom ke-5; indeks format uang/qty dan lebar kolom disesuaikan
  (32 kolom). Kolom lain tidak berubah.
- Catatan: baris tanpa alokasi SPK dibiarkan **kosong** (tidak diberi label "Non-SPK") sesuai permintaan.

### Pengujian (data produksi, read-only)
- 368 baris; **27 baris ber-SPK** — 25 baris 1 SPK, **2 baris 2 SPK** (contoh: `01234, SPK017323`).
- 16 nomor SPK unik pada laporan, **16/16 ditemukan** di master `spk` (tidak ada nomor karangan).
- Urutan kolom terverifikasi: `... kategori, unit, spk_no, mro_date ...`.
- Excel: **32 kolom**, `No. SPK` di kolom 5, `Total DO` kolom 23, `Total Invoice` kolom 27,
  `Qty DO` 22, `Qty Invoice` 26, `Outstanding` 31 — format uang/qty tepat.
- `py_compile` kedua file: OK.

---

## 2026-10-29 — MRO Traceability: Nama Proyek, Nama Supplier, Total DO/Invoice setelah PPN

### Tujuan (permintaan pemilik)
1. Kolom **Nama Proyek** setelah **No. SPK**.
2. Kolom **Nama Supplier** setelah **Tanggal PO**.
3. **Total DO**: dari `DPP x qty diterima` menjadi **harga satuan setelah PPN x qty diterima** (judul cukup "Total DO").
4. **Total Invoice**: **harga satuan setelah PPN x qty yang diinvoicekan**.

### Perubahan
- `backend/report_trace_detail.py`
  - `_po_unit_total(pl)`: harga satuan setelah PPN = `po_lines.total / qty` (fallback DPP + pajak).
  - `Total DO` baris = `_po_unit_total x qty diterima` (sebelumnya DPP/unit).
  - `_attach_invoices()`: nilai DO kini berbasis harga setelah PPN; `Qty Invoice = qty DO baris x min(1, alokasi/nilai DO)`;
    `Total Invoice = harga satuan setelah PPN x Qty Invoice` (sebelumnya prorata DPP invoice). Normalisasi
    `dpp/amount` dihapus karena tidak lagi dipakai.
  - `Nama Proyek`: dari `mro_lines.project_id` (fallback `mro.default_project_id`) -> `projects.name`.
  - `Nama Supplier`: dari `po.supplier_id` -> `suppliers.name` pada setiap PO di rantai.
  - Nama ganda digabung satu kolom, urut, dipisah **koma**.
  - `trace_batch()` menambah batch `projects` + `suppliers` (konstan, bukan per baris).
  - Excel: 34 kolom (`Nama Proyek` kolom 6, `Nama Supplier` kolom 14); indeks format uang `{17..21, 25, 29}`,
    qty `{9, 12, 16, 24, 28, 32, 33}`; judul `Total DO` (tanpa "(DPP x Qty Diterima)").
- `backend/report_financial_fix.py` (wrapper yang menghitung ulang untuk user ber-izin harga):
  `do_total` ikut memakai harga satuan setelah PPN (`total / qty`), agar konsisten dengan builder dasar.
- `backend/reporting/reports_procurement.py`: kolom `project_name` (setelah `spk_no`) & `supplier_name`
  (setelah `po_date`); label `do_total` -> **Total DO**; `search_keys` menambah `project_name`, `supplier_name`.
- Test disesuaikan dengan aturan baru: `tests/report_center_test.py` (label "Total DO") dan
  `tests/p7_trace_batch_test.py` T3b (Total DO = total/qty x qty diterima).

### Pengujian (data produksi, read-only)
- 373 baris; **309 baris ber-proyek**, **299 ber-supplier**; contoh multi-supplier: `Teknik Mandiri, Toko Cat Mutiara Warna`.
- Total DO berbasis PPN: po_line qty 1 DPP 100.000 -> satuan 111.000 (+11%); contoh baris `SKU/0231` = 111.000 x 8 = **888.000**.
- Invarian: 53 DO dengan 1 invoice penuh -> **Total Invoice = Total DO** (selisih 0); 21 DO sisanya penagihan sebagian.
- Tanpa izin harga: `do_total` & `inv_total` None; `spk_no`, `project_name`, `supplier_name`, qty tetap terisi.
- Excel: **34 kolom**; posisi `No. SPK`=5, `Nama Proyek`=6, `Tanggal PO`=13, `Nama Supplier`=14, `No. PO`=15,
  `Total DO`=25, `Total Invoice`=29; format uang/qty tepat.
- `py_compile` 5 file: OK.

---

## 2026-10-30 — Perbaikan Total Invoice: harga satuan item, bukan rata-rata DO

### Masalah (temuan pemilik)
Contoh: `PO/2026/10/00002` qty 20 (Total DO 2.600.000) dengan invoice `434666` menampilkan Total Invoice
**2.377.777,78** padahal Qty Invoice = Qty DO. Penyebab: Total Invoice dihitung dari **harga satuan rata-rata DO**
(nilai seluruh DO / qty DO) lalu dikali qty — sehingga item yang harganya berbeda dalam satu DO saling "tertukar".

### Perubahan
- `report_trace_detail._build_rows()` menyimpan `_do_money[do_id]` = nilai DO baris itu sendiri (harga satuan
  setelah PPN x qty diterima) di samping `_do_qty`.
- `_attach_invoices()`: `Total Invoice baris = _do_money[do_id] x rasio penagihan` (bukan harga rata-rata DO).
  Rasio = `min(1, alokasi invoice DO / nilai DO)`, dihitung dari penjumlahan seluruh baris DO.
  Konsekuensi: **bila Qty Invoice = Qty DO maka Total Invoice = Total DO** per baris.
- Kolom invoice dipasang setelah koreksi finansial (`report_financial_fix`) supaya basis nilainya sama dengan
  Total DO final; `_attach_invoices` dipanggil di wrapper (kedua cabang: ber-izin & tanpa izin harga).
- `_po_unit_dpp()` / `_po_unit_total()` dan query `do_lines`/`po_lines` di `_attach_invoices` dihapus (tidak dipakai lagi
  → 2 query lebih sedikit per request).
- `_do_money` juga diisi untuk user tanpa izin harga (hanya internal, untuk menghitung rasio) agar Qty Invoice tetap akurat.

### Pengujian (data produksi, read-only)
- `DO/2026/10/00003` + invoice `434666`: baris menjadi **2.600.000 / 1.250.000 / 1.500.000** = Total DO
  (sebelumnya 2.377.777,78 / 1.188.888,89 / 1.783.333,33); Σ = 5.350.000 = nilai invoice.
- Invarian: **59 baris** dengan Qty Invoice = Qty DO → Total Invoice = Total DO, **0 selisih**.
- Tanpa izin harga: `do_total` & `inv_total` None, **80 baris** tetap ber-Qty Invoice (sama dengan user ber-izin).
- `py_compile` OK.

---

## 2026-10-30 — Kontrak Harga Vendor: UOM otomatis mengikuti master barang

### Tujuan (permintaan pemilik)
Pada dialog **Tambah/Edit Item Harga** kontrak vendor, UOM tidak ikut master barang. Sekarang:
- UOM **terisi otomatis** dengan **satuan dasar barang** begitu barang dipilih.
- Pilihan UOM **dibatasi**: hanya satuan dasar + satuan turunan milik barang itu (`items.uoms`), bukan seluruh master satuan.

### Perubahan (`frontend/src/pages/VendorContract.jsx`, ItemDialog)
- `onItemChange()`: saat barang dipilih, `uom_id` diisi `items.base_uom_id` → fallback `items.uom_id` → fallback
  pencocokan nama/simbol/kode dengan `items.unit` (data lama) → kosong.
- `uomOptions`: dibangun dari `[base_uom_id] + items.uoms[].uom_id` (unik). Bila barang belum punya data satuan,
  kembali ke seluruh master satuan agar form tidak buntu. Nilai `uom_id` yang sudah tersimpan (edit data lama)
  selalu disertakan agar tidak hilang.
- Tambahan kecil: bila satuan terpilih adalah satuan turunan (faktor > 1), tampil keterangan
  `1 <satuan> = <faktor> <satuan dasar>`.

### Pengujian
- `CI=true yarn build` → **Compiled successfully** (68,56 s), tanpa warning ESLint (warning = error di Coolify).
- Uji logika dengan data produksi (6 item multi-satuan, 3 item satu satuan, 2 item lama): **11/11 lolos, 0 gagal**
  — auto UOM = satuan dasar; opsi ⊆ {satuan dasar + satuan barang}; contoh `SKU/0206` hanya 2 opsi
  (bukan 176 master satuan); item lama `unit="Pcs"` otomatis memilih satuan Pcs.
- Belum diuji di browser (dialog butuh login + izin `vendor_contract:manage`).
