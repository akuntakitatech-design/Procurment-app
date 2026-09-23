#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "================================================================"
echo "==> PT REAL PROCUREMENT - PRE-PRODUCTION RELEASE GATE"
echo "==> Production tidak di-merge dan tidak di-deploy oleh script ini"
echo "================================================================"

echo
echo "==> GATE 1/2: Full Regression + E2E"
bash deploy/test-full-regression-e2e.sh

echo
echo "==> GATE 2/2: Production Clone Migration Rehearsal"
bash deploy/test-production-clone-rehearsal.sh

echo
echo "================================================================"
echo "==> GO: PRE-PRODUCTION RELEASE GATE PASS"
echo "==> Regression, UOM Loan/Return, migration clone, ownership,"
echo "==> document counts, dan attachment clone sudah tervalidasi."
echo "==> Production masih belum diubah / belum deploy."
echo "================================================================"
