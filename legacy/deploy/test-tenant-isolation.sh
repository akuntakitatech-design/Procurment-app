#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/tenant-isolation-test.compose.yml"
PROJECT_NAME="procurement-tenant-test"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Menyiapkan environment test terpisah (TIDAK memakai database production)"
cleanup

echo "==> Menjalankan simulasi Tenant A vs Tenant B"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up \
  --build \
  --abort-on-container-exit \
  --exit-code-from tenant-test-runner

echo "==> PASS: tenant isolation test selesai"
