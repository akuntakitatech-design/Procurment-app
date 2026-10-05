# Inventory Valuation Hardening — Plan (baseline `aab5ed4`)

## 1) Objectives
- Make moving weighted average valuation **end-to-end safe + auditable** for all warehouse stock modules in scope: Transfer, Loan, Adjustment, Stock Opname, Opening Valuation, Reversal/Cancellation, Backdate safety, Concurrency/Atomicity, Reconciliation.
- Enforce: **no negative inventory**, **no hidden re-costing**, **immutable historical cost snapshots**, **no normal-path estimated valuation**.
- Deliver as **incremental local commits per checkpoint**, final reconciliation + regression + `CI=true yarn build`.

## 2) Implementation Steps

### Phase 1 — Core POC (isolation) for the valuation engine hard parts
User stories:
1. As an accountant, I need concurrent postings on the same pool to serialize so stock/value never goes negative.
2. As an auditor, I need a single posting attempt to be idempotent so double-click/retry doesn’t double-post value.
3. As a controller, I need reversals to post compensating entries referencing original cost snapshots.
4. As an admin, I need transfers to carry value exactly so there is no P/L.
5. As QA, I need backdated postings blocked to avoid mid-history moving average corruption.

Steps:
1. **Web research (best practice)**: confirm recommended patterns for moving-average valuation with MariaDB/InnoDB concurrency (row locks / optimistic version / idempotency keys) and reversal accounting patterns.
2. Create a minimal isolated test harness (python in `/tmp`) that calls backend functions (or hits API) to simulate:
   - concurrent OUT (two issues) on same item/warehouse
   - idempotent retry
   - reversal of a movement using original valuation snapshot
   - transfer OUT/IN value carry
3. Refactor valuation core:
   - Implement `post_movement(...) -> result dict` as the only engine.
   - Keep `post_ledger(...) -> running` wrapper for backward compatibility.
4. Add optimistic concurrency + atomicity:
   - Add `_ver` to `item_warehouse` docs.
   - Use `find_one_and_update(..., $inc: {_ver:1}, for_update semantics)` or transaction-level lock to serialize per pool.
   - Make stock_ledger + valuation_ledger + item_warehouse update atomic (single transaction block).
5. Add idempotency:
   - Define `source_key` (doc_type+doc_id+line_id+direction or a canonical string).
   - Enforce uniqueness by checking existing `valuation_ledger` by `source_key` before posting; if exists return prior result.
6. Remove normal-path `valuation_estimated`:
   - Change default behavior: IN without explicit cost source => **hard-block** with clear error.
   - Leave `valuation_estimated` only for legacy diagnostics if encountered, not created going forward.

Deliverable: core POC script passes and first checkpoint commit.

### Phase 2 — V1 App development (checkpoint-driven hardening)

#### Checkpoint 1 — Concurrency / Atomicity (commit)
User stories:
1. As a warehouse operator, I cannot accidentally post negative stock when another operator issues stock simultaneously.
2. As finance, I need stock_ledger + valuation_ledger + item_warehouse to always reconcile after any post.
3. As the system, I must reject IN postings without valid cost sources.
4. As the system, I must reject duplicate post attempts for the same doc line.
5. As QA, I can reproduce concurrency and see only one succeeds.

Steps:
- Implement transaction wrapper in DB layer usage (use `MariaDatabase._transaction()`), applied inside `post_movement`.
- Add backdate guard plumbing to `post_movement` (but enforce later checkpoint): accept `txn_at/txn_date` param.
- Ensure all callers pass `line_id` consistently; patch missing `line_id` in mutation flows.

#### Checkpoint 2 — Reversal / Cancellation (commit)
User stories:
1. As an auditor, I can see original valuation entries remain and reversals are compensating entries.
2. As an operator, I cannot reverse the same document twice.
3. As inventory control, reversal is blocked if it would cause negative stock.
4. As finance, reversal uses **original cost snapshot**, not current avg.
5. As admin, delete/edit flows remain functional but now valuation-safe.

Steps:
- Build `reverse_document_valuation(doc_id, reason, user)`:
  - Find original `valuation_ledger` rows for doc_id not reversed.
  - Post compensating movements through `post_movement` using stored `value_in/value_out` snapshots.
  - Mark originals `reversed=true` + link reversal ids.
  - Idempotent guard: if already reversed return ok.
- Wire `transaction_mutation_layer._reverse_ledgers` to delegate to the new valuation reversal (and stop direct item_warehouse qty-only updates).
- Wire `loan_return_mutation_layer._reverse` similarly.
- Add DO/MI reversal safety: block reversal if stock would go negative.

#### Checkpoint 3 — Transfer valuation (commit)
User stories:
1. As finance, transfer does not create profit/loss and carries exact value.
2. As a warehouse user, transfer posts as one logical operation (no half-post).
3. As an auditor, transfer reversal references the original transfer value.
4. As QA, total company inventory value is conserved after transfer.
5. As a dev, transfer edit/delete uses the same valuation-safe engine.

Steps:
- Transfer OUT: post OUT using current avg_before snapshot.
- Transfer IN: pass `value_in=source_transfer_value` (not unit_cost_in) so destination receives exact carrying value.
- Atomic app-level safety: if IN fails after OUT, compensate by reversing OUT within same request (or single DB transaction if feasible across both pools).
- Transfer reversal: reverse both legs using original snapshot values; ensure atomic.

#### Checkpoint 4 — Adjustment + Stock Opname valuation (commit)
User stories:
1. As stock control, negative adjustments use current avg snapshot.
2. As accounting, positive adjustments require approved cost when avg not available.
3. As a supervisor, overriding default cost requires a reason and is audited.
4. As an opname approver, posting creates valuation entries once and never duplicates on reopen.
5. As a limited user, I do not see cost inputs without permission.

Steps:
- Adjustment OUT: valued at avg_before; block insufficient stock.
- Adjustment IN: cost rules:
  - if pool has avg and qty>0: default cost=avg; allow override only with permission + reason.
  - if qty==0/no avg: approved cost mandatory; block missing/<=0.
- Minimal UI changes on Adjustment screen to capture: valuation basis, approved unit cost, reason when required; permission-gated.
- Opname shortage: OUT at avg_before snapshot.
- Opname surplus: IN with default avg if valid else require approved cost; reason on override.

#### Checkpoint 5 — Loan valuation (commit)
User stories:
1. As finance, loan issue/return never creates artificial gain/loss.
2. As a warehouse user, borrowing warehouse receives stock valued at original loan cost.
3. As an auditor, partial returns consume outstanding value deterministically.
4. As system, loan return cannot exceed outstanding qty/value.
5. As admin, loan cancellation/reversal uses original snapshots.

Steps:
- Inspect current behavior (it increases borrowing warehouse stock) and preserve it.
- On loan issue:
  - OUT uses avg_before; store snapshot cost+value on `loan_lines` (outstanding_qty/value fields).
  - IN uses `value_in` = loan carrying value.
- On loan return:
  - consume from outstanding deterministically (proportional by qty); use stored unit cost snapshot.
  - return postings use `value_in/value_out` based on original snapshot.
- Ensure edit/delete reversals use central reversal engine.

#### Checkpoint 6 — Backdated posting safety (commit)
User stories:
1. As finance, I cannot post a movement dated earlier than existing later movements in same pool.
2. As a user, I receive a clear error with the latest transaction reference.
3. As system, same-day ordering is deterministic.
4. As QA, backdate test reliably blocks.
5. As auditor, ledger sequence remains consistent.

Steps:
- In `post_movement`, compare `txn_at` vs latest valuation_ledger `at` for pool; block if earlier.
- Ensure all posting endpoints pass intended `date` field into `txn_at`.

#### Checkpoint 7 — Opening Inventory Valuation UI (commit)
User stories:
1. As admin/accounting, I can see existing qty per item/warehouse and set opening avg cost.
2. As admin, I can filter/search and track status (valued/unvalued).
3. As admin, I must enter cut-off date and understand this does not add stock.
4. As system, I cannot value zero-qty pools or duplicate openings.
5. As limited user, I cannot access the menu.

Steps:
- Add backend endpoint for **opening candidates** (item, warehouse, qty existing, base uom, status valued/unvalued).
- Frontend: add Settings submenu “Opening Inventory Valuation” under Warehouse/MI section.
- Build grid + filters + cut-off date + per-row post (batch only if backend supports safely).
- Permission-gate using existing `view_purchase_price`/admin-like.

#### Checkpoint 8 — Reconciliation + diagnostics + full regression (final commit)
User stories:
1. As QA, I can run reconcile report and see stock qty equals valuation qty for all pools.
2. As finance, I can detect invalid pools (qty<0, value<0, qty=0 value!=0).
3. As auditor, I can detect duplicate source_key and orphan valuation entries.
4. As dev, I can trace each valuation entry back to its document/line.
5. As release manager, build passes and prior procurement flows still work.

Steps:
- Extend `/reports/valuation-reconcile` to include value/avg checks + diagnostics list.
- Run E2E tests 1–15 in a throwaway tenant; record results; cleanup only generated docs.
- Run regression smoke on MRO→RO→PO→DO→MI and attachments patterns.
- Run `CI=true yarn build`.

## 3) Next Actions
1. Implement Phase 1 POC: refactor `post_movement` + concurrency + idempotency + no-estimated-IN.
2. Commit Checkpoint 1.
3. Implement reversal engine + wire delete/edit reversals; commit Checkpoint 2.
4. Proceed sequentially through checkpoints 3–8 with a commit each.

## 4) Success Criteria
- For all scoped modules: postings are atomic per pool, idempotent per source_key, reject negative stock, and never create normal-path `valuation_estimated`.
- Reversal/cancellation creates compensating valuation entries using original snapshots; double reversal prevented.
- Transfer and loan preserve total carrying value (no P/L) and carry exact value across warehouses.
- Backdated postings are blocked with clear error.
- Opening valuation UI functions with cut-off + safeguards; no qty mutation.
- Reconciliation reports `ok:true` after the required E2E tests; diagnostics are clean.
- No regression in existing procurement flows; `CI=true yarn build` passes.

## PO — Informasi Harga & Supplier saat Tarik RO (Status: COMPLETED, lokal, branch feature/po-ro-price-insight)
- Kolom "Harga" + tombol "Lihat Harga" di popup Tarik RO; popup "Informasi Harga & Supplier" (lazy, per baris RO).
- Backend read-only: GET /api/pull/ro-for-po/price-insight, GET /api/pull/ro-for-po/price-history (maks 5).
- Kontrak: resolver Kontrak Harga Vendor existing (batch `resolve_vendor_item_prices`, aturan identik `resolve_price`).
- Harga Beli Terakhir: PO Approved/Partially Received/Fully Received (tidak cancelled), net setelah diskon item, tanpa PPN, per satuan dasar.
- Pilih Supplier hanya mengubah supplier PO di form (belum simpan); Supplier Utama & kontrak tidak berubah.
- Test: tests/po_price_insight_test.py 25/25; regresi PO/RO/receipt/invoice + multi-proses lulus; CI=true yarn build sukses.
