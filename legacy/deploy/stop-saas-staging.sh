#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="procurement-saas-staging"
COMPOSE_FILE="$ROOT_DIR/deploy/saas-staging.compose.yml"
ENV_FILE="${HOME}/.procurement-saas-staging.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Credential staging tidak ditemukan: $ENV_FILE"
  exit 1
fi

docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down --remove-orphans

echo "==> SaaS staging berhenti. Database staging tetap tersimpan."
echo "Untuk menghapus seluruh data staging juga, jalankan:"
echo "docker compose -p $PROJECT_NAME --env-file $ENV_FILE -f $COMPOSE_FILE down -v --remove-orphans"
