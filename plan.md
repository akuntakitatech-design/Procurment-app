# CP5A-3 — Pre-Save SPK Budget Preview (Local Only)

## 1) Objectives
- Menampilkan **Kontrol Budget SPK** untuk PO **sebelum save** dan untuk **semua PO yang editable (New + Draft edit)**.
- Preview harus memakai **basis nilai & distribusi yang sama persis** dengan commitment saat PO Approved:
  - nilai line = `total` (tax-inclusive) seperti `create_po` dan `_line_total_int()`.
  - distribusi nilai per SPK proporsional qty via `_distribute()` (largest-remainder; reconcile eksak).
  - evaluasi budget/policy via `spk_layer.effective_policy()` + `spk_layer.evaluate_budget()`.
- Preview **read-only, zero-write**: tidak membuat PO/alloc/ledger/commitment, tidak mengubah saldo/budget.
- UI ringkas: tabel `SPK | Budget | Commitment | PO Ini | Sisa Proyeksi | Status`, hanya `spk_number` (tanpa UUID).

## 2) Implementation Steps

### Phase 1 — Core POC (Isolated backend core)
**User stories (POC)**
1. Sebagai buyer, saya bisa mengirim payload PO draft (unsaved) dan mendapat proyeksi budget per SPK.
2. Sebagai buyer, nilai multi-SPK terdistribusi proporsional dan totalnya reconcile 100%.
3. Sebagai buyer, alokasi Non-SPK tidak memengaruhi budget SPK.
4. Sebagai admin, memanggil endpoint preview berulang kali tidak menambah ledger/commitment apa pun.
5. Sebagai QA, hasil preview untuk payload yang sama selalu deterministik.

**Backend (FastAPI) — `backend/spk_allocation_layer.py`**
1. Refactor helper shared (tanpa ubah behavior existing):
   - `async _budget_eval_for_amounts(per_spk: dict[str,int], exclude_po_id: str|None)`
     - ambil `spk.procurement_budget`, existing commitment via `_spk_committed(spk_id, exclude_po_id)`.
     - policy via `spk_layer.effective_policy(...)["global"]`.
     - evaluasi via `spk_layer.evaluate_budget(existing, amount, budget, policy)`.
     - return shape kompatibel dengan `per_spk` pada `budget-summary`.
   - Update `_evaluate_po_budget(po_id)` agar memakai helper ini.
2. Tambah calculator untuk input mentah (unsaved):
   - `_line_total_int_raw(line)` mengikuti formula tax-inclusive (qty/price/discount/tax).
   - `_amounts_from_lines(raw_lines)`:
     - untuk setiap line: hitung `total_int` + `parts=[(spk_id, allocated_qty),("__nonspk__", non_spk_qty)]`.
     - pakai `_distribute(total_int, parts)`; agregasi hanya SPK (exclude `__nonspk__`).
3. Endpoint baru (READ-ONLY):
   - `POST /api/spk-allocations/po/preview-budget`
   - Request minimal: `{ lines: [{ key, qty, price, discount, tax, allocations:[{spk_id, allocated_qty}], non_spk_qty? }] }`
   - Backend **validasi**: qty/price/discount/tax numeric; allocations unique; `spk_id` valid (tenant-scoped).
   - Response: `{ per_spk:[...], blocked, warning }` (reuse canonical `decision` values: ok/warning/block).
4. Acceptance tests (backend controlled; prefer script kecil di `/app/backend/_cp5a3_budget_preview_test.py`):
   - PO-BUDGET-01..10 sesuai spec, termasuk:
     - multi-SPK distribution + rounding reconcile.
     - remaining-only/partial menggunakan allocation PO-stage (payload sudah berisi hasil PO-stage).
     - zero-write: snapshot count `spk_commitment_ledger` sebelum/sesudah.
     - consistency check: buat PO Draft+alloc kecil (terkontrol) → bandingkan summary endpoint vs preview payload setara.

**Stop-gate POC**: endpoint + tests lulus sebelum lanjut UI.

### Phase 2 — V1 App Development (Frontend reactive preview)
**User stories (V1 UI)**
1. Sebagai buyer, saya melihat blok **Kontrol Budget SPK** pada PO baru bahkan sebelum Save.
2. Sebagai buyer, saat saya ubah Qty/Harga/Diskon, preview budget langsung update (tanpa Save).
3. Sebagai buyer, saat saya tarik RO (dengan SPK), preview otomatis muncul dan sesuai allocation PO-stage.
4. Sebagai buyer, bila item hanya Non-SPK, UI menampilkan empty-state yang jelas (tanpa error).
5. Sebagai buyer, UI tidak flicker; request lama tidak boleh overwrite hasil terbaru.

**Frontend (React) — new component + integrate**
1. Buat komponen baru `frontend/src/components/PoBudgetSummaryPreview.jsx`:
   - Props: `{ lines, editable, allocMap, isNew }` (+ optional `refreshKey`).
   - Debounce 250–500ms; gunakan AbortController + request sequence guard.
   - Payload builder:
     - Untuk line unsaved: gunakan `l._inheritPreview.allocations` sebagai SPK allocation PO-stage.
     - Untuk line saved (Draft edit): gunakan `allocMap[l.id]` (from `useDocAllocations`) sebagai allocation.
     - Hitung `non_spk_qty` dari summary (`summary.non_spk_qty`) dan kirim agar backend bisa reconcile (tetap backend yang distribute).
     - Kirim qty/price/discount/tax dari line (basis sama seperti commitment).
   - Render:
     - Loading ringan “Memperbarui…” tanpa menghapus hasil lama.
     - Empty state: “Belum ada alokasi SPK pada item PO.” / “PO ini tidak memiliki alokasi budget SPK.”
     - Table compact: SPK, Budget, Commitment, PO Ini, Sisa Proyeksi, Status.
     - Mapping status: ok→Within Budget, warning→Warning, block→Over Budget (presentation only; value canonical tetap dari backend).
2. Integrasi di `frontend/src/pages/Po.jsx`:
   - Setelah strip `Kontrol Harga`, render strip/card `Kontrol Budget SPK` menggunakan komponen baru untuk **editable** (isNew || editing).
   - Untuk read-only saved view tetap gunakan `PoBudgetSummary` existing.
3. UI sanity checks (manual):
   - tarik RO ber-SPK → preview muncul.
   - ubah Qty/Harga/Diskon → preview update.
   - pastikan tidak ada UUID tampil.

### Phase 3 — Testing & Validation
**User stories (regression)**
1. Sebagai user, fitur RO→PO inheritance tetap berjalan.
2. Sebagai user, SPK allocation modal masih berfungsi untuk PO saved.
3. Sebagai user, price control/histori harga tetap tampil normal.
4. Sebagai user, proses save PO + attachment-before-save tidak terdampak.
5. Sebagai user, approval/commitment behavior (Approved-only) tetap sama.

**Checks**
1. Jalankan backend acceptance script (10/10 PASS) dan catat bukti zero-write.
2. Jalankan `CI=true yarn build` (PASS).
3. Smoke UI di preview URL: lihat Kontrol Harga + Kontrol Budget SPK tampil rapi.

## 3) Next Actions
1. Implement backend refactor + endpoint preview-budget (no writes).
2. Buat script test controlled + jalankan PO-BUDGET-01..10.
3. Implement frontend `PoBudgetSummaryPreview` + wiring di `Po.jsx`.
4. Run `CI=true yarn build`.
5. Buat 1 commit lokal `CP5A-3: pre-save SPK budget preview` dan laporkan: SHA, file berubah, hasil test/build, QA manual tersisa.

## 4) Success Criteria
- Endpoint `POST /api/spk-allocations/po/preview-budget` mengembalikan per-SPK preview yang:
  - memakai `tax-inclusive total` dan `_distribute` (reconcile eksak).
  - memakai `effective_policy` + `evaluate_budget` (status ok/warning/block).
  - existing commitment hanya dari ledger valid; tidak double count draft.
  - **zero write** terverifikasi.
- UI PO editable menampilkan **Kontrol Budget SPK** sebelum save dan reaktif terhadap perubahan.
- Tidak ada UUID/internal id tampil.
- `CI=true yarn build` berhasil.
- Tidak ada push/PR dan tidak memulai CP5B.
