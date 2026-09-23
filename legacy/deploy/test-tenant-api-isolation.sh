#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/tenant-api-isolation-test.compose.yml"
PROJECT_NAME="procurement-tenant-api-test"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Menyiapkan environment API test terpisah"
cleanup

echo "==> Menjalankan real backend + simulasi Tenant A vs Tenant B"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from tenant-api-test-runner

echo "==> PASS: API tenant isolation test selesai"
