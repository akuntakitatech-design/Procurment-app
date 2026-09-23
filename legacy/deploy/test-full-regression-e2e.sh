#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

run_step() {
  local n="$1" total="$2" label="$3" script="$4"
  echo
  echo "================================================================"
  echo "==> ${n}/${total} ${label}"
  echo "================================================================"
  bash "$script"
}

TOTAL=16

echo "==> FULL REGRESSION + E2E PT REAL PROCUREMENT"
echo "==> Semua integration test memakai stack/database disposable masing-masing"
echo "==> Production /opt/procurement dan database staging utama tidak disentuh"

run_step 1  "$TOTAL" "Multi-tenant regression"              deploy/test-multi-tenant-regression.sh
run_step 2  "$TOTAL" "Division visibility"                  deploy/test-division-visibility.sh
run_step 3  "$TOTAL" "MRO -> RO -> PO flow integrity"       deploy/test-procurement-flow-integrity.sh
run_step 4  "$TOTAL" "Approval state"                       deploy/test-approval-state.sh
run_step 5  "$TOTAL" "DO receipt integrity"                 deploy/test-do-receipt-integrity.sh
run_step 6  "$TOTAL" "DO condition/discrepancy"             deploy/test-do-receipt-condition.sh
run_step 7  "$TOTAL" "Loan & Return"                        deploy/test-loan-return-integrity.sh
run_step 8  "$TOTAL" "Loan & Return alternate UOM"          deploy/test-loan-return-uom-integrity.sh
run_step 9  "$TOTAL" "Stock Adjustment"                     deploy/test-stock-adjustment-integrity.sh
run_step 10 "$TOTAL" "Stock Opname"                         deploy/test-stock-opname-integrity.sh
run_step 11 "$TOTAL" "Master Data"                          deploy/test-master-data-integrity.sh
run_step 12 "$TOTAL" "Document / Attachment / Print"        deploy/test-document-attachment-print.sh
run_step 13 "$TOTAL" "Report & Control"                     deploy/test-report-control.sh
run_step 14 "$TOTAL" "Item-warehouse stock mutation guard"  deploy/test-item-warehouse-guard.sh
run_step 15 "$TOTAL" "Final UX production build + SPA smoke" deploy/test-final-ux.sh
run_step 16 "$TOTAL" "Integrated Business + Warehouse E2E"  deploy/test-full-e2e.sh

echo
echo "================================================================"
echo "==> PASS: FULL REGRESSION + E2E SELESAI"
echo "==> Branch siap masuk release review / pre-production review."
echo "==> Production belum diubah, belum merge, dan belum deploy."
echo "================================================================"
