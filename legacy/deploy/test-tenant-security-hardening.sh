#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/tenant-security-hardening-test.compose.yml"
PROJECT_NAME="procurement-tenant-security-hardening-test"
LOG_FILE="/tmp/tenant-security-hardening-test.log"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
rm -f "$LOG_FILE"

echo "==> Menjalankan tenant security hardening test pada disposable environment"
set +e
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from tenant-security-test-runner \
  2>&1 | tee "$LOG_FILE"
TEST_EXIT=${PIPESTATUS[0]}
set -e

if [ "$TEST_EXIT" -ne 0 ]; then
  echo
  echo "==> FAIL: tenant security hardening test gagal (exit $TEST_EXIT)"
  echo "==> Ringkasan error:"
  grep -E 'RESULT:|FAIL|AssertionError|Traceback|ERROR|PASS:' "$LOG_FILE" | tail -120 || true
  exit "$TEST_EXIT"
fi

echo "==> PASS: tenant security hardening test selesai"
