#!/usr/bin/env bash
# Menjalankan seluruh *_test.py berbasis HTTP API milik aplikasi terhadap backend MariaDB
# (bukan Mongo) memakai database KOSONG terpisah, lalu merangkum hasilnya.
#
# Pakai (dari /app/backend):
#   DATABASE_URL=mysql://user:pass@127.0.0.1:3306/proc_itest bash scripts/run_integrity_tests_mariadb.sh
# Opsional: TEST_PORT (default 8012), KEEP_DB=1 untuk tidak mengosongkan DB di akhir,
#           ONLY="a_test.py b_test.py" untuk menjalankan sebagian saja.
set -uo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?DATABASE_URL (MariaDB kosong untuk test) wajib diisi}"
PORT="${TEST_PORT:-8012}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin-itest@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Itest-Admin-12345!}"
LOG=/tmp/itest-backend-${PORT}.log
UPLOADS=/tmp/itest-uploads-${PORT}

TESTS=(
  division_visibility_integration_test.py
  do_receipt_condition_test.py
  do_receipt_integrity_test.py
  document_attachment_print_integrity_test.py
  full_e2e_integrity_test.py
  item_warehouse_guard_integrity_test.py
  loan_return_integrity_test.py
  loan_return_uom_integrity_test.py
  master_data_integrity_test.py
  procurement_flow_integrity_test.py
  report_control_integrity_test.py
  stock_adjustment_integrity_test.py
  stock_opname_integrity_test.py
)

# Tenant id default per test (mengikuti compose asli di deploy/*.compose.yml; sebagian test memeriksa prefix storage tenant)
tenant_for() {
  case "$1" in
    document_attachment_print_integrity_test.py) echo tenant-document-test ;;
    *) echo tenant-itest ;;
  esac
}

start_backend() {
  local tenant="${1:-tenant-itest}"
  rm -rf "$UPLOADS"; mkdir -p "$UPLOADS"
  env -i PATH="$PATH" HOME="$HOME" \
    DATABASE_URL="$DATABASE_URL" DB_NAME=procurement_itest DB_AUTO_SCHEMA=true PORT="$PORT" \
    JWT_SECRET=itest-secret-0123456789abcdef0123456789abcdef \
    ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    DEFAULT_TENANT_ID="$tenant" DEFAULT_COMPANY_ID="company-${tenant#tenant-}" DEFAULT_TENANT_SLUG=itest \
    DEFAULT_TENANT_NAME="PT ITEST" DEFAULT_TENANT_MAX_USERS=25 \
    ENABLE_PUBLIC_TENANT_REGISTRATION=false DISABLE_LEGACY_USER_SELF_REGISTER=true \
    ALLOW_DEMO_SEED=false WRITE_TEST_CREDENTIALS=false \
    STORAGE_DRIVER=local STORAGE_LOCAL_PATH="$UPLOADS" FRONTEND_URL=http://localhost:3000 \
    COOKIE_SECURE=false PROCUREFLOW_ENTRY=bootstrap MAX_UPLOAD_MB=1 \
    python production_bootstrap.py >"$LOG" 2>&1 &
  BACKEND_PID=$!
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${PORT}/api/_healthcheck" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "backend test tidak siap; lihat $LOG"; tail -30 "$LOG"; return 1
}

stop_backend() { kill "$BACKEND_PID" 2>/dev/null; wait "$BACKEND_PID" 2>/dev/null; }

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

if [ -n "${ONLY:-}" ]; then read -r -a TESTS <<< "$ONLY"; fi

PASS=(); FAIL=()
for t in "${TESTS[@]}"; do
  echo "=================== $t ==================="
  reset_db
  start_backend "$(tenant_for "$t")" || { FAIL+=("$t (backend gagal start)"); continue; }
  if TEST_API_URL="http://127.0.0.1:${PORT}/api" ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
     timeout 600 python "$t" > "/tmp/itest-${t%.py}.log" 2>&1; then
    echo "PASS $t"; PASS+=("$t")
  else
    echo "FAIL $t"; tail -15 "/tmp/itest-${t%.py}.log"; FAIL+=("$t")
  fi
  stop_backend
done
[ "${KEEP_DB:-0}" = "1" ] || reset_db

echo
echo "================ RINGKASAN ================"
echo "PASS: ${#PASS[@]}"; for p in "${PASS[@]}"; do echo "  ok   $p"; done
echo "FAIL: ${#FAIL[@]}"; for f in "${FAIL[@]}"; do echo "  FAIL $f"; done
[ "${#FAIL[@]}" -eq 0 ]
