#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_NAME="procurement-saas-staging"
COMPOSE_FILE="$ROOT_DIR/deploy/saas-staging.compose.yml"
ENV_FILE="${HOME}/.procurement-saas-staging.env"

rand_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
  fi
}

if [ ! -f "$ENV_FILE" ]; then
  JWT_SECRET="$(rand_secret)"
  PLATFORM_PASSWORD="Staging-$(rand_secret | cut -c1-18)!"
  ADMIN_PASSWORD="Bootstrap-$(rand_secret | cut -c1-18)!"
  cat > "$ENV_FILE" <<EOF
SAAS_STAGING_JWT_SECRET=${JWT_SECRET}
SAAS_STAGING_ADMIN_EMAIL=bootstrap-staging@akuntakita.com
SAAS_STAGING_ADMIN_PASSWORD=${ADMIN_PASSWORD}
SAAS_STAGING_PLATFORM_EMAIL=platform-staging@akuntakita.com
SAAS_STAGING_PLATFORM_PASSWORD=${PLATFORM_PASSWORD}
EOF
  chmod 600 "$ENV_FILE"
  echo "==> Credential staging dibuat di $ENV_FILE"
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "==> Menyalakan private SaaS staging"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

echo "==> Menunggu frontend staging siap"
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18080/api/saas/public-config >/tmp/procurement-saas-staging-public-config.json 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "==> FAIL: staging belum siap"
    docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
    exit 1
  fi
  sleep 2
done

echo
printf '%s\n' "==> PASS: private SaaS staging siap"
printf '%s\n' "URL VPS lokal : http://127.0.0.1:18080"
printf '%s\n' "Platform email : ${SAAS_STAGING_PLATFORM_EMAIL}"
printf '%s\n' "Platform password: ${SAAS_STAGING_PLATFORM_PASSWORD}"
echo
printf '%s\n' "Dari PC/laptop, buka SSH tunnel ke VPS lalu akses http://localhost:18080"
printf '%s\n' "Staging ini memakai database dan volume sendiri; produksi PT REAL tidak disentuh."
