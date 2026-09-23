#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/saas-registration-test.compose.yml"
PROJECT_NAME="procurement-saas-registration-test"
LOG_FILE="/tmp/saas-registration-test.log"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Menyiapkan environment SaaS registration test terpisah"
cleanup
rm -f "$LOG_FILE"

echo "==> Menjalankan registrasi tenant + Invite User + subscription expiry/reminder + Super Admin + limit user"
set +e
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from saas-registration-test-runner \
  2>&1 | tee "$LOG_FILE"
TEST_EXIT=${PIPESTATUS[0]}
set -e

if [ "$TEST_EXIT" -ne 0 ]; then
  echo
  echo "==> FAIL: SaaS registration test gagal (exit $TEST_EXIT)"
  echo "==> Ringkasan error:"
  grep -E 'REGISTER DEBUG|OWNER TENANT DEBUG|RESULT:|FAIL|AssertionError|Traceback|ERROR|Exception|DuplicateKey|PASS:' "$LOG_FILE" | tail -220 || true
  exit "$TEST_EXIT"
fi

echo "==> PASS: SaaS registration + invitation + subscription lifecycle test selesai"
