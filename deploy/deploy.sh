#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env belum ada. Copy deploy.env.example menjadi .env lalu isi secret production."
  exit 1
fi

echo "==> Pull source terbaru"
git pull --ff-only

echo "==> Validasi Docker Compose"
docker compose config -q

echo "==> Build images (container lama tetap berjalan selama build)"
docker compose build --pull

echo "==> Start/update services"
docker compose up -d --remove-orphans

echo "==> Status"
docker compose ps

echo "==> Smoke test frontend"
FRONTEND_ADDR="$(docker compose port frontend 80 | tail -n 1)"
if [[ -z "$FRONTEND_ADDR" ]]; then
  echo "ERROR: port frontend tidak ditemukan."
  docker compose logs --tail=100 frontend
  exit 1
fi
BASE_URL="http://${FRONTEND_ADDR}"

INDEX_HTML=""
for _ in $(seq 1 30); do
  if INDEX_HTML="$(curl -fsS --max-time 5 "$BASE_URL/")"; then
    break
  fi
  sleep 1
done

if [[ -z "$INDEX_HTML" ]]; then
  echo "ERROR: frontend tidak merespons setelah deployment."
  docker compose logs --tail=100 frontend
  exit 1
fi

MAIN_JS="$(printf '%s' "$INDEX_HTML" | grep -oE 'src="[^"]+\.js"' | head -n 1 | cut -d'"' -f2 || true)"
if [[ -z "$MAIN_JS" ]]; then
  echo "ERROR: file JavaScript utama tidak ditemukan di index.html."
  exit 1
fi

if ! curl -fsS --max-time 10 -o /dev/null "${BASE_URL}${MAIN_JS}"; then
  echo "ERROR: JavaScript utama gagal diakses: ${MAIN_JS}"
  docker compose logs --tail=100 frontend
  exit 1
fi

echo "OK: index.html dan ${MAIN_JS} dapat diakses."
echo "Deployment selesai."
