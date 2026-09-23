#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/procurement-flow-integrity-test.compose.yml"
PROJECT_NAME="procurement-flow-integrity-test"
LOG_FILE="/tmp/procurement-flow-integrity-test.log"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Menyiapkan procurement flow integrity test terpisah"
cleanup
rm -f "$LOG_FILE"

set +e
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from flow-test-runner \
  2>&1 | tee "$LOG_FILE"
TEST_EXIT=${PIPESTATUS[0]}
set -e

if [ "$TEST_EXIT" -ne 0 ]; then
  echo
  echo "==> FAIL: procurement flow integrity test gagal (exit $TEST_EXIT)"
  echo "==> Ringkasan error:"
  grep -E 'RESULT:|FAIL|AssertionError|Traceback|ERROR|Exception|PASS:' "$LOG_FILE" | tail -240 || true
  exit "$TEST_EXIT"
fi

echo "==> PASS: procurement flow integrity test selesai"
