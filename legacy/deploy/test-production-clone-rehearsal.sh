#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROD_DIR="${PROD_DIR:-/opt/procurement}"
ENV_FILE="${HOME}/.procurement-saas-staging.env"
COMPOSE_FILE="$ROOT_DIR/deploy/production-clone-rehearsal.compose.yml"
PROJECT_NAME="procurement-release-rehearsal"
REHEARSAL_DB="procurement_release_rehearsal"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/tmp/procurement-release-rehearsal-${TS}"
PRE_COUNTS="/tmp/procurement-release-pre-${TS}.json"
POST_COUNTS="/tmp/procurement-release-post-${TS}.json"
MISSING_TENANT="/tmp/procurement-release-missing-tenant-${TS}.json"

if [ ! -d "$PROD_DIR" ] || [ ! -f "$PROD_DIR/.env" ]; then
  echo "==> FAIL: production directory/.env tidak ditemukan di $PROD_DIR"
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "==> FAIL: $ENV_FILE tidak ditemukan"
  exit 1
fi

cleanup() {
  docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
mkdir -p "$BACKUP_DIR"

echo "================================================================"
echo "==> RELEASE REHEARSAL DARI CLONE DATA PRODUCTION"
echo "==> Production hanya dibaca untuk backup; tidak direstart/tidak dimigrasi"
echo "==> Semua restore dan migration berjalan pada database disposable"
echo "================================================================"

echo "==> 1/7 Membuat snapshot production"
(
  cd "$PROD_DIR"
  BACKUP_DIR="$BACKUP_DIR" bash deploy/backup.sh
)

if [ ! -s "$BACKUP_DIR/mongodb.archive.gz" ] || [ ! -f "$BACKUP_DIR/manifest.txt" ]; then
  echo "==> FAIL: snapshot MongoDB tidak lengkap"
  exit 1
fi
PROD_DB="$(sed -n 's/^database=//p' "$BACKUP_DIR/manifest.txt" | head -n1)"
if [ -z "$PROD_DB" ]; then
  echo "==> FAIL: nama database production tidak ditemukan di manifest"
  exit 1
fi

echo "==> 2/7 Menyalakan MongoDB rehearsal disposable"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d rehearsal-mongodb

echo "==> 3/7 Restore snapshot ke database rehearsal"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T rehearsal-mongodb \
  mongorestore --archive --gzip \
  --nsFrom="${PROD_DB}.*" --nsTo="${REHEARSAL_DB}.*" \
  < "$BACKUP_DIR/mongodb.archive.gz"

echo "==> Simpan jumlah dokumen sebelum migration"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T rehearsal-mongodb \
  mongosh --quiet --eval "const d=db.getSiblingDB('${REHEARSAL_DB}'); const o={}; d.getCollectionNames().sort().forEach(c=>o[c]=d.getCollection(c).countDocuments({})); print(JSON.stringify(o));" \
  | tail -n1 > "$PRE_COUNTS"

if [ -f "$BACKUP_DIR/local-attachments.tar.gz" ]; then
  echo "==> Restore attachment snapshot ke volume rehearsal"
  ATTACHMENT_EXPECTED="$(tar -tzf "$BACKUP_DIR/local-attachments.tar.gz" | awk 'substr($0,length($0),1)!="/" {n++} END{print n+0}')"
  docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm -T \
    -v "$BACKUP_DIR:/backup:ro" rehearsal-files \
    sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} +; tar -xzf /backup/local-attachments.tar.gz -C /target'
  ATTACHMENT_ACTUAL="$(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm -T rehearsal-files sh -c 'find /target -type f | wc -l' | tail -n1 | tr -d '[:space:]')"
  if [ "$ATTACHMENT_ACTUAL" != "$ATTACHMENT_EXPECTED" ]; then
    echo "==> FAIL: jumlah attachment clone berbeda (backup=$ATTACHMENT_EXPECTED clone=$ATTACHMENT_ACTUAL)"
    exit 1
  fi
  echo "PASS: $ATTACHMENT_ACTUAL attachment berhasil direstore ke clone"
fi

echo "==> 4/7 Build + start backend feature terhadap clone"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build rehearsal-backend

READY=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 http://127.0.0.1:18082/docs >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "==> FAIL: backend rehearsal tidak sehat"
  docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs --tail=200 rehearsal-backend || true
  exit 1
fi

echo "==> 5/7 Validasi jumlah dokumen sesudah migration"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T rehearsal-mongodb \
  mongosh --quiet --eval "const d=db.getSiblingDB('${REHEARSAL_DB}'); const o={}; d.getCollectionNames().sort().forEach(c=>o[c]=d.getCollection(c).countDocuments({})); print(JSON.stringify(o));" \
  | tail -n1 > "$POST_COUNTS"

python3 - "$PRE_COUNTS" "$POST_COUNTS" <<'PY'
import json, sys
pre=json.load(open(sys.argv[1]))
post=json.load(open(sys.argv[2]))
shrunk={k:(v,post.get(k,0)) for k,v in pre.items() if post.get(k,0) < v}
if shrunk:
    raise SystemExit(f"FAIL: jumlah dokumen berkurang setelah migration: {shrunk}")
print(f"PASS: {len(pre)} collection existing tidak kehilangan dokumen")
PY

echo "==> 6/7 Validasi tenant ownership hasil backfill"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T rehearsal-mongodb \
  mongosh --quiet --eval "const d=db.getSiblingDB('${REHEARSAL_DB}'); const g=new Set(['tenants','plans','tenant_migrations','login_attempts','platform_audit_logs']); const o={}; d.getCollectionNames().sort().forEach(c=>{if(!g.has(c)&&!c.startsWith('system.')) o[c]=d.getCollection(c).countDocuments({tenant_id:{\$exists:false}})}); print(JSON.stringify(o));" \
  | tail -n1 > "$MISSING_TENANT"

python3 - "$PRE_COUNTS" "$MISSING_TENANT" <<'PY'
import json, sys
pre=json.load(open(sys.argv[1]))
missing=json.load(open(sys.argv[2]))
bad={k:v for k,v in missing.items() if k in pre and v}
if bad:
    raise SystemExit(f"FAIL: dokumen production masih tanpa tenant_id: {bad}")
print("PASS: seluruh dokumen production tenant-scoped memiliki tenant_id")
PY

OWNERSHIP="$(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T rehearsal-mongodb \
  mongosh --quiet --eval "const d=db.getSiblingDB('${REHEARSAL_DB}'); print(d.users.countDocuments({\$or:[{tenant_id:{\$exists:false}},{company_id:{\$exists:false}}]}));" | tail -n1 | tr -d '\r')"
if [ "$OWNERSHIP" != "0" ]; then
  echo "==> FAIL: masih ada user tanpa tenant_id/company_id: $OWNERSHIP"
  exit 1
fi
echo "PASS: ownership user lengkap"

TENANT_OK="$(docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T rehearsal-mongodb \
  mongosh --quiet --eval "const d=db.getSiblingDB('${REHEARSAL_DB}'); print(d.tenants.countDocuments({id:'tenant-pt-real',status:'active'}));" | tail -n1 | tr -d '\r')"
if [ "$TENANT_OK" != "1" ]; then
  echo "==> FAIL: tenant default PT REAL tidak terbentuk aktif"
  exit 1
fi
echo "PASS: tenant default PT REAL aktif"

echo "==> 7/7 Rehearsal selesai"
echo "================================================================"
echo "==> PASS: PRODUCTION CLONE MIGRATION REHEARSAL"
echo "==> Snapshot: $BACKUP_DIR"
echo "==> Production tidak diubah, tidak direstart, tidak dideploy"
echo "================================================================"
