#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/loan-return-uom-integrity-test.compose.yml"
ENV_FILE="${HOME}/.procurement-saas-staging.env"
PROJECT_NAME="procurement-loan-return-uom-integrity-test"
LOG_FILE="/tmp/procurement-loan-return-uom-integrity-test.log"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> FAIL: $ENV_FILE tidak ditemukan"
  exit 1
fi

cleanup() {
  docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Menyiapkan Loan & Return UOM integrity test terpisah"
echo "==> Database test: procurement_loan_return_uom_integrity_test"
echo "==> Production dan database staging utama tidak disentuh"
cleanup
rm -f "$LOG_FILE"

set +e
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from loan-return-uom-runner \
  2>&1 | tee "$LOG_FILE"
TEST_EXIT=${PIPESTATUS[0]}
set -e

if [ "$TEST_EXIT" -ne 0 ]; then
  echo
  echo "==> FAIL: Loan & Return UOM integrity test gagal (exit $TEST_EXIT)"
  echo "==> Ringkasan error:"
  grep -E 'RESULT:|FAIL|AssertionError|Traceback|ERROR|Exception|PASS:' "$LOG_FILE" | tail -260 || true
  exit "$TEST_EXIT"
fi

echo
echo "==> PASS: Loan & Return UOM integrity test selesai"
echo "==> Production /opt/procurement tidak disentuh."
