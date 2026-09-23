#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/backup-folder"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$(cd "$1" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "ERROR: .env tidak ditemukan"
  exit 1
fi

set -a
source .env
set +a

if [[ -f "$BACKUP_DIR/mongodb.archive.gz" ]]; then
  echo "==> Restore MongoDB"
  docker compose exec -T mongodb mongorestore \
    --username "$MONGO_ROOT_USERNAME" \
    --password "$MONGO_ROOT_PASSWORD" \
    --authenticationDatabase admin \
    --db "$DB_NAME" \
    --archive --gzip --drop < "$BACKUP_DIR/mongodb.archive.gz"
fi

if [[ -f "$BACKUP_DIR/local-attachments.tar.gz" ]]; then
  echo "==> Restore attachment volume"
  docker run --rm --volumes-from procurement-backend \
    -v "$BACKUP_DIR:/backup:ro" alpine:3.20 \
    sh -c 'mkdir -p /app/data/uploads && rm -rf /app/data/uploads/* && tar -xzf /backup/local-attachments.tar.gz -C /app/data/uploads'
fi

echo "Restore selesai. Restart service..."
docker compose restart backend frontend
