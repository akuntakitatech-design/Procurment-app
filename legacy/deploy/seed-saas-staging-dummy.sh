#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="procurement-saas-staging"
COMPOSE_FILE="$ROOT_DIR/deploy/saas-staging.compose.yml"
ENV_FILE="${HOME}/.procurement-saas-staging.env"
SEED_FILE="$ROOT_DIR/backend/staging_dummy_seed.py"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> FAIL: $ENV_FILE belum ada. Jalankan deploy/start-saas-staging.sh dulu."
  exit 1
fi

if [ ! -f "$SEED_FILE" ]; then
  echo "==> FAIL: $SEED_FILE tidak ditemukan. Jalankan git fetch/reset branch staging terlebih dahulu."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$ROOT_DIR"

# Seed tidak perlu membangun ulang image. Build/restart staging dilakukan oleh
# start-saas-staging.sh. Di sini kita hanya memastikan backend + Mongo aktif,
# lalu menyalin script seed terbaru ke container staging.
echo "==> Memastikan private SaaS staging aktif"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d mongodb backend

echo "==> Menunggu backend staging siap"
for i in $(seq 1 45); do
  if docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T backend \
      curl -fsS http://127.0.0.1:8000/docs >/dev/null 2>&1; then
    break
  fi
  if [ "$i" -eq 45 ]; then
    echo "==> FAIL: backend staging belum siap"
    exit 1
  fi
  sleep 2
done

echo "==> Menyiapkan script dummy terbaru di container staging"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" cp \
  "$SEED_FILE" backend:/tmp/staging_dummy_seed.py >/dev/null

echo "==> Mengisi data dummy staging (tanpa menghapus data existing)"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T \
  -e ALLOW_STAGING_DUMMY_SEED=true \
  backend python /tmp/staging_dummy_seed.py

echo
echo "==> PASS: dummy staging selesai"
echo "==> Production /opt/procurement tidak disentuh."
