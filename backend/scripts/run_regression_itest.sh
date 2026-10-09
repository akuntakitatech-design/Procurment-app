#!/usr/bin/env bash
# Regresi backend/tests/*.py (API + DB) terhadap backend TERISOLASI memakai database KOSONG khusus test
# (mis. proc_itest) — bukan DB preview/sandbox dan bukan production. Single-instance (flock).
#
# Pakai (dari /app/backend):
#   DATABASE_URL=mysql://user:pass@127.0.0.1:3306/proc_itest bash scripts/run_regression_itest.sh
# Opsional: TEST_PORT (default 8013), ONLY="a_test.py b_test.py", KEEP_DB=1, ITEST_LOCK=/path/lock
# Nilai lain (JWT, registrasi tenant, dsb.) diambil dari backend/.env; storage dipaksa lokal ke folder sementara.
set -uo pipefail
cd "$(dirname "$0")/.."

: "${DATABASE_URL:?DATABASE_URL (MariaDB kosong khusus test) wajib diisi}"
DBN="${DATABASE_URL##*/}"; DBN="${DBN%%\?*}"
case "$DBN" in
  *itest*|*_test) ;;
  *) echo "Menolak berjalan: database '$DBN' bukan database test terisolasi (*itest* / *_test)"; exit 2 ;;
esac

PORT="${TEST_PORT:-8013}"
LOG="/tmp/itest-reg-backend-${PORT}.log"
UPLOADS="/tmp/itest-reg-uploads-${PORT}"
PY="${PYTHON:-python}"

exec 9>"${ITEST_LOCK:-/tmp/procureflow-itest.lock}"
flock -n 9 || { echo "Runner test terisolasi lain sedang berjalan (lock)"; exit 1; }

TESTS=(
  stock_opname_workflow_test.py
  stock_opname_cas_retry_test.py
  stock_opname_freeze_coverage_test.py
  adjustment_multi_warehouse_test.py
  loan_multi_warehouse_test.py
  loan_return_attachment_legacy_test.py
  transfer_multi_warehouse_test.py
  transfer_shared_guard_regression_test.py
  valuation_hardening_test.py
  opening_inventory_valuation_test.py
  opening_correction_test.py
  receipt_control_test.py
  transaction_input_validation_test.py
  inventory_value_asof_test.py
  stock_summary_parity_test.py
  master_item_stock_test.py
  stock_info_test.py
  master_tenant_isolation_test.py
  stock_opname_uat_fixture_test.py
)
if [ -n "${ONLY:-}" ]; then read -r -a TESTS <<< "$ONLY"; fi

reset_db() {
  "$PY" - "$DATABASE_URL" <<'EOF'
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
print(f"[reset {u.path.lstrip('/')}] {len(names)} tabel dihapus")
EOF
}

reset_db
rm -rf "$UPLOADS"; mkdir -p "$UPLOADS"
DATABASE_URL="$DATABASE_URL" DB_NAME="$DBN" PORT="$PORT" STORAGE_DRIVER=local STORAGE_LOCAL_PATH="$UPLOADS" \
  ALLOW_DEMO_SEED=false WRITE_TEST_CREDENTIALS=false ENABLE_PUBLIC_TENANT_REGISTRATION=true \
  PROCUREFLOW_ENTRY=bootstrap "$PY" production_bootstrap.py >"$LOG" 2>&1 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null; wait $BACKEND_PID 2>/dev/null' EXIT
for _ in $(seq 1 90); do
  curl -fsS "http://127.0.0.1:${PORT}/api/_healthcheck" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/api/_healthcheck" >/dev/null 2>&1 || { echo "backend test tidak siap; lihat $LOG"; tail -30 "$LOG"; exit 1; }
grep -m1 "Database:" "$LOG"

PASS=(); FAIL=()
for t in "${TESTS[@]}"; do
  out="/tmp/itest-reg-${t%.py}.log"
  (cd tests && TEST_API_URL="http://127.0.0.1:${PORT}/api" TEST_DATABASE_URL="$DATABASE_URL" TEST_DB_NAME="$DBN" \
     TEST_STORAGE_DRIVER=local TEST_STORAGE_LOCAL_PATH="$UPLOADS" API_BASE="http://127.0.0.1:${PORT}" \
     DATABASE_URL="$DATABASE_URL" DB_NAME="$DBN" STORAGE_DRIVER=local STORAGE_LOCAL_PATH="$UPLOADS" timeout 900 "$PY" "$t" > "$out" 2>&1)
  rc=$?
  summary=$(grep -E "[0-9]+/[0-9]+ passed|Tests passed: [0-9]+/[0-9]+|TOTAL [0-9]+/[0-9]+" "$out" | tail -1)
  if [ $rc -eq 0 ]; then PASS+=("$t  ${summary}"); echo "PASS $t  ${summary}"
  else FAIL+=("$t  ${summary}"); echo "FAIL $t (exit=$rc) ${summary}"; grep -E "^FAIL|Error|Traceback" "$out" | head -15; fi
done

kill $BACKEND_PID 2>/dev/null; wait $BACKEND_PID 2>/dev/null; trap - EXIT
[ "${KEEP_DB:-0}" = "1" ] || reset_db
rm -rf "$UPLOADS"

echo
echo "================ RINGKASAN REGRESI (${DBN}) ================"
echo "PASS: ${#PASS[@]}"; for p in "${PASS[@]}"; do echo "  ok   $p"; done
echo "FAIL: ${#FAIL[@]}"; for f in "${FAIL[@]}"; do echo "  FAIL $f"; done
[ "${#FAIL[@]}" -eq 0 ]
