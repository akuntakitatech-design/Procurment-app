#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/deploy/approval-state-test.compose.yml"
PROJECT="procurement-approval-state-test"

cleanup() {
  docker compose -p "$PROJECT" -f "$COMPOSE" down -v --remove-orphans || true
}
trap cleanup EXIT

cd "$ROOT"
cleanup

echo "==> Build approval state test"
docker compose -p "$PROJECT" -f "$COMPOSE" build --pull

echo "==> Jalankan approval state test"
docker compose -p "$PROJECT" -f "$COMPOSE" up --abort-on-container-exit --exit-code-from approval-test-runner

echo "==> PASS: procurement approval state test selesai"
