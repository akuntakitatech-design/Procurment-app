#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> 1/5 database proxy tenant isolation"
bash deploy/test-tenant-isolation.sh

echo
echo "==> 2/5 real HTTP API tenant isolation"
bash deploy/test-tenant-api-isolation.sh

echo
echo "==> 3/5 stock tenant isolation"
bash deploy/test-tenant-stock-isolation.sh

echo
echo "==> 4/5 SaaS registration + ownership/quota"
bash deploy/test-saas-registration.sh

echo
echo "==> 5/5 tenant security hardening"
bash deploy/test-tenant-security-hardening.sh

echo
echo "==> PASS: seluruh multi-tenant regression test selesai"
