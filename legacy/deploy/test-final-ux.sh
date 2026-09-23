#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="procurement-final-ux-test:local"
CONTAINER="procurement-final-ux-smoke"
PORT="18081"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }
require_text() {
  local file="$1" pattern="$2" label="$3"
  grep -Fq -- "$pattern" "$ROOT_DIR/$file" || fail "$label"
  pass "$label"
}

echo "==> Final UX frontend QA"
echo "==> Production /opt/procurement tidak disentuh"

require_text "frontend/src/App.js" 'AppErrorBoundary' "Error boundary aktif di root aplikasi"
require_text "frontend/src/components/Layout.jsx" 'lg:flex fixed lg:static' "Sidebar desktop tidak overlay konten"
require_text "frontend/src/components/Layout.jsx" 'lg:hidden' "Drawer/overlay mobile tersedia"
require_text "frontend/src/components/Layout.jsx" 'min-w-0 flex-1 overflow-hidden' "Area konten aman dari overflow layout"
require_text "frontend/src/components/PageHeader.jsx" 'overflow-x-auto' "Action header tetap usable pada layar kecil"
require_text "frontend/src/components/Combobox.jsx" 'max-w-[calc(100vw-2rem)]' "Dropdown combobox dibatasi viewport"
require_text "frontend/src/components/ItemLines.jsx" 'overflow-x-auto' "Tabel item dapat discroll horizontal"
require_text "frontend/src/components/DocList.jsx" 'overflow-x-auto' "Daftar transaksi dapat discroll horizontal"

cleanup

echo "==> Build image frontend production"
docker build -t "$IMAGE" "$ROOT_DIR/frontend"
pass "Frontend production build berhasil"

echo "==> Jalankan smoke container di 127.0.0.1:${PORT}"
# nginx production memang mem-proxy /api ke hostname service `backend`.
# Pada smoke test frontend standalone tidak ada compose backend, jadi sediakan
# resolusi dummy agar nginx dapat start. Endpoint /api tidak dipakai pada test ini.
docker run -d --rm --name "$CONTAINER" \
  --add-host backend:127.0.0.1 \
  -p "127.0.0.1:${PORT}:80" \
  "$IMAGE" >/dev/null

READY=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/" >/tmp/procurement-final-ux-index.html 2>/dev/null; then
    READY=1
    break
  fi
  if ! docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER"; then
    echo "==> Smoke container berhenti sebelum siap. Log terakhir:"
    docker logs "$CONTAINER" 2>&1 | tail -80 || true
    fail "Smoke container frontend berhenti saat startup"
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "==> Log smoke container:"
  docker logs "$CONTAINER" 2>&1 | tail -80 || true
  fail "Smoke container frontend tidak siap dalam 30 detik"
fi

curl -fsS "http://127.0.0.1:${PORT}/" | grep -qi '<div id="root"' || fail "Root SPA tidak dapat dimuat"
pass "Root SPA dapat dimuat"

for route in /mro/test /reports /inventory /settings; do
  curl -fsS "http://127.0.0.1:${PORT}${route}" | grep -qi '<div id="root"' || fail "Deep-link SPA gagal: ${route}"
done
pass "Deep-link BrowserRouter dilayani nginx dengan benar"

echo
echo "==> PASS: Final UX frontend QA selesai"
echo "==> Production /opt/procurement tidak disentuh."
