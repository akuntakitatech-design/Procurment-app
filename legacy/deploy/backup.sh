#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env tidak ditemukan"
  exit 1
fi

set -a
source .env
set +a

TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/$TS}"
mkdir -p "$BACKUP_DIR"

echo "==> Backup MongoDB"
docker compose exec -T mongodb mongodump \
  --username "$MONGO_ROOT_USERNAME" \
  --password "$MONGO_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --db "$DB_NAME" \
  --archive --gzip > "$BACKUP_DIR/mongodb.archive.gz"

echo "==> Backup attachment volume"
docker run --rm --volumes-from procurement-backend \
  -v "$BACKUP_DIR:/backup" alpine:3.20 \
  sh -c 'if [ -d /app/data/uploads ]; then tar -czf /backup/local-attachments.tar.gz -C /app/data/uploads .; fi'

cat > "$BACKUP_DIR/manifest.txt" <<EOF
created_at=$TS
database=$DB_NAME
storage_driver=${STORAGE_DRIVER:-local}
EOF

echo "Backup selesai: $BACKUP_DIR"
