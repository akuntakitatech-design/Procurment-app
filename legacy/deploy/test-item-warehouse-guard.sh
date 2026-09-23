#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/item-warehouse-guard-test.compose.yml"
ENV_FILE="${HOME}/.procurement-saas-staging.env"
PROJECT_NAME="procurement-item-warehouse-guard-test"
LOG_FILE="/tmp/procurement-item-warehouse-guard-test.log"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> FAIL: $ENV_FILE tidak ditemukan"
  exit 1
fi

cleanup() {
  docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Menyiapkan item-warehouse stock mutation guard test terpisah"
echo "==> Database test: procurement_item_warehouse_guard_test"
echo "==> Production dan database staging utama tidak disentuh"
cleanup
rm -f "$LOG_FILE"

set +e
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from item-warehouse-guard-runner \
  2>&1 | tee "$LOG_FILE"
TEST_EXIT=${PIPESTATUS[0]}
set -e

if [ "$TEST_EXIT" -ne 0 ]; then
  echo
  echo "==> FAIL: Item-warehouse guard test gagal (exit $TEST_EXIT)"
  echo "==> Ringkasan error:"
  grep -E 'RESULT:|FAIL|AssertionError|Traceback|ERROR|Exception|PASS:' "$LOG_FILE" | tail -250 || true
  exit "$TEST_EXIT"
fi

echo
echo "==> PASS: Item-warehouse stock mutation guard test selesai"
echo "==> Production /opt/procurement tidak disentuh."
