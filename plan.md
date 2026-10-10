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

### P4 — Reporting SPK & Kontrak Harga Vendor (Status: IN PROGRESS; branch `feature/reporting-p4-spk-contract` dari `main` a222436; target 1 PR ke `main`, TANPA merge/deploy)
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
(KPI 0 -> 0). Temuan existing di luar scope P4 (tidak diubah): kartu header & tab "Commitment & Realisasi" halaman /spk/{id} masih
stub (spk_layer._budget_summary commitment=0 "CP2"; Spk.jsx statis); Report Center: tanggal ISO & filter tidak dari URL.


### P5–P6 (Status: NOT STARTED)
P5 Invoice & Hutang · P6 export di list transaksi · lalu Performance Optimization menyeluruh (PR terpisah).
