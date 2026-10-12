#!/usr/bin/env bash
# P7 — jalankan backend TERISOLASI (1 worker, entrypoint production) untuk benchmark terhadap DB uji volume P7.
# Pakai: bash scripts/perf_p7_backend.sh start [src_backend_dir] | stop      (port default 8031, DB default proc_perf_itest)
# Menolak DB yang bukan *_itest. Tidak menyentuh backend preview (8001) / sandbox / production.
set -u
CMD=${1:-start}; SRC=${2:-/app/backend}; DB=${P7_DB:-proc_perf_itest}; PORT=${P7_PORT:-8031}
case "$DB" in *_itest) ;; *) echo "menolak DB $DB"; exit 2 ;; esac
LOG=/root/perf/p7_backend_${PORT}.log
pid_on_port() { ss -ltnp | grep ":${PORT} " | grep -o "pid=[0-9]*" | head -1 | cut -d= -f2; }
if [ "$CMD" = stop ]; then
  P=$(pid_on_port); [ -n "$P" ] && ps -p "$P" -o cmd= | grep -q production_bootstrap && kill "$P" && echo "stopped $P"; exit 0
fi
mkdir -p /root/perf/uploads
cd "$SRC"
DATABASE_URL="$(python /app/backend/scripts/itest_url.py "$DB")" DB_NAME=$DB PORT=$PORT STORAGE_DRIVER=local STORAGE_LOCAL_PATH=/root/perf/uploads \
  ALLOW_DEMO_SEED=false WRITE_TEST_CREDENTIALS=false PROCUREFLOW_ENTRY=bootstrap setsid python production_bootstrap.py > "$LOG" 2>&1 < /dev/null &
for _ in $(seq 1 120); do curl -fsS "http://127.0.0.1:${PORT}/api/_healthcheck" >/dev/null 2>&1 && break; sleep 1; done
P=$(pid_on_port)
ps -p "$P" -o cmd= | grep -q production_bootstrap || { echo "PID check gagal"; tail -20 "$LOG"; exit 1; }
echo "backend pid $P src=$SRC db=$DB port=$PORT"
