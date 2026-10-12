"""Cetak DATABASE_URL untuk schema test terisolasi (default proc_itest).

Host/port dari backend/.env; user/password test dari file lokal di luar repo (ITEST_ENV_FILE, default
/root/.procureflow_itest.env: ITEST_DB_USER=..., ITEST_DB_PASSWORD=...). Tidak ada kredensial di repo.
Menolak schema yang bukan *_itest. Pakai:
    DATABASE_URL="$(python scripts/itest_url.py proc_itest)" bash scripts/run_regression_itest.sh
"""
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse


def _read(path):
    out = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


name = sys.argv[1] if len(sys.argv) > 1 else "proc_itest"
if not name.endswith("_itest"):
    sys.exit("schema harus *_itest")
env = _read(Path(__file__).resolve().parent.parent / ".env")
cred = _read(os.environ.get("ITEST_ENV_FILE", "/root/.procureflow_itest.env"))
u = urlparse(env["DATABASE_URL"])
netloc = u.netloc
if cred.get("ITEST_DB_USER"):
    host = u.hostname + (f":{u.port}" if u.port else "")
    netloc = f"{quote(cred['ITEST_DB_USER'])}:{quote(cred.get('ITEST_DB_PASSWORD', ''))}@{host}"
print(urlunparse(u._replace(netloc=netloc, path="/" + name)))
