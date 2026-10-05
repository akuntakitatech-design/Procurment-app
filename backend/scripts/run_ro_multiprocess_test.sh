#!/usr/bin/env bash
# RO concurrency lintas proses: 2 proses backend (port berbeda) terhadap SATU database test
# KOSONG (bukan production), lalu tests/ro_multiprocess_concurrency_test.py.
#
# Pakai (dari /app/backend):
#   DATABASE_URL=mysql://user:pass@127.0.0.1:3306/procurement_test bash scripts/run_ro_multiprocess_test.sh
# Opsional: BACKEND_DIR=<dir backend lain> (mis. worktree commit lama untuk baseline),
#           PORTS="8013 8014", KEEP_DB=1.
set -uo pipefail
cd "$(dirname "$0")/.."
TEST_DIR="$(pwd)"
: "${DATABASE_URL:?DATABASE_URL (MariaDB test kosong) wajib diisi}"
case "$DATABASE_URL" in *prod*) echo "Menolak menjalankan terhadap DB yang tampak production"; exit 2;; esac
BACKEND_DIR="${BACKEND_DIR:-$TEST_DIR}"
read -r -a PORTS <<< "${PORTS:-8013 8014}"
ADMIN_EMAIL="${ADMIN_EMAIL_MP:-admin-mp@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD_MP:-Mp-Admin-12345!}"

reset_db() {
  python - "$DATABASE_URL" <<'EOF'
import sys, pymysql
from urllib.parse import urlparse, unquote
u = urlparse(sys.argv[1].replace("mariadb://", "mysql://"))
conn = pymysql.connect(host=u.hostname, port=u.port or 3306, user=unquote(u.username or ""), password=unquote(u.password or ""), database=u.path.lstrip("/"))
with conn.cursor() as cur:
    cur.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'")
    names = [r[0] for r in cur.fetchall()]
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    for n in names: cur.execute(f"DROP TABLE IF EXISTS `{n}`")
conn.commit(); conn.close()
print(f"[reset] {len(names)} tabel dihapus")
EOF
}

start_one() {
  local port="$1"
  env -i PATH="$PATH" HOME="$HOME" \
    DATABASE_URL="$DATABASE_URL" DB_NAME=procurement_mp DB_AUTO_SCHEMA=true PORT="$port" \
    JWT_SECRET=mp-secret-0123456789abcdef0123456789abcdef \
    ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    DEFAULT_TENANT_ID=tenant-mp DEFAULT_COMPANY_ID=company-mp DEFAULT_TENANT_SLUG=mp \
    DEFAULT_TENANT_NAME="PT MP" DEFAULT_TENANT_MAX_USERS=25 \
    ENABLE_PUBLIC_TENANT_REGISTRATION=false DISABLE_LEGACY_USER_SELF_REGISTER=true \
    ALLOW_DEMO_SEED=false WRITE_TEST_CREDENTIALS=false \
    STORAGE_DRIVER=local STORAGE_LOCAL_PATH="/tmp/mp-uploads-$port" FRONTEND_URL=http://localhost:3000 \
    COOKIE_SECURE=false PROCUREFLOW_ENTRY=bootstrap MAX_UPLOAD_MB=1 \
    bash -c "cd '$BACKEND_DIR' && exec python production_bootstrap.py" >"/tmp/mp-backend-$port.log" 2>&1 &
  echo $!
}

wait_up() {
  for _ in $(seq 1 90); do
    curl -fsS "http://127.0.0.1:$1/api/_healthcheck" >/dev/null 2>&1 && return 0; sleep 1
  done
  echo "backend $1 tidak siap"; tail -20 "/tmp/mp-backend-$1.log"; return 1
}

reset_db
PIDS=()
# proses pertama dulu (membuat skema/admin), lalu proses kedua
PIDS+=("$(start_one "${PORTS[0]}")"); wait_up "${PORTS[0]}" || exit 1
for p in "${PORTS[@]:1}"; do PIDS+=("$(start_one "$p")"); wait_up "$p" || exit 1; done
URLS=$(printf "http://127.0.0.1:%s/api," "${PORTS[@]}"); URLS="${URLS%,}"
echo "backend PIDs: ${PIDS[*]}  urls: $URLS  dir: $BACKEND_DIR"
LOCK_DSN="$DATABASE_URL" API_URLS="$URLS" ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  timeout 600 python "$TEST_DIR/tests/ro_multiprocess_concurrency_test.py"; RC=$?
for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null; done; wait 2>/dev/null
[ "${KEEP_DB:-0}" = "1" ] || reset_db
exit $RC
