#!/usr/bin/env python3
"""Fixture UAT Stock Opname — Staff Divisi Asset TANPA akses harga + Approver Asset DENGAN akses harga.

Idempotent & reproducible (aman dijalankan berulang): user/master dicari berdasarkan email/kode lalu
DISAMAKAN ke kondisi baku (role, izin, cakupan divisi, password) — tidak pernah membuat duplikat.
Hanya untuk database TEST (proc_sandbox / *itest* / *_test). Menolak berjalan terhadap DB lain.

Tidak ada password di repository:
  - Admin       : UAT_ADMIN_EMAIL + UAT_ADMIN_PASSWORD (wajib, dari environment)
  - Staff/Approver: UAT_STAFF_PASSWORD / UAT_APPROVER_PASSWORD; bila kosong dibuat acak lalu ditulis ke
    UAT_CRED_OUT (default /app/memory/uat_stock_opname_credentials.md — folder memory/ di-.gitignore, chmod 600).
    Password tidak pernah dicetak ke stdout.

Pakai (preview sandbox, dari /app/backend):
  UAT_ADMIN_EMAIL=... UAT_ADMIN_PASSWORD=... python scripts/uat_fixture_stock_opname.py
Opsi env: UAT_API_URL (default http://localhost:8001/api), UAT_DATABASE_URL (default DATABASE_URL di backend/.env),
          UAT_KEEP_OPNAME=1 (jangan batalkan Opname aktif di gudang UAT), UAT_ALLOW_REMOTE=1 (API bukan localhost).
"""
import datetime as _dt
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

SAFE_DB = re.compile(r"^(proc_sandbox|.*itest.*|.*_test)$")
STAFF_EMAIL = "uat.staff.asset@sandbox.test"
APPROVER_EMAIL = "uat.approver.asset@sandbox.test"
DIV_ASSET = ("DIV-AST", "Asset")
DIV_OPS = ("DIV-OPS", "Operasional")
WH_ASSET = ("UAT-GA", "Gudang UAT Asset")
WH_OPS = ("UAT-GO", "Gudang UAT Operasional")
STAFF_OVERRIDES = {
    # operasional Stock Opname (hitung, review, ajukan, cetak, lampiran) — TANPA approve/post & TANPA harga
    "opname.view": "allow", "opname.create": "allow", "opname.edit": "allow", "opname.print": "allow",
    "opname.cancel": "allow", "opname.post": "deny", "opname.delete": "deny",
    "adjustment.view": "allow", "transfer.view": "allow", "loan.view": "allow",
    "upload_attachment": "allow", "export": "allow",
    "view_purchase_price": "deny", "edit_purchase_price": "deny", "view_all_warehouse": "deny",
}
APPROVER_OVERRIDES = {
    "opname.view": "allow", "opname.create": "allow", "opname.edit": "allow", "opname.print": "allow",
    "opname.cancel": "allow", "opname.post": "allow",
    "adjustment.view": "allow", "transfer.view": "allow", "loan.view": "allow",
    "upload_attachment": "allow", "export": "allow", "view_purchase_price": "allow", "view_all_warehouse": "deny",
}


def _db_name(url):
    return (urlparse((url or "").replace("mariadb://", "mysql://")).path or "/").lstrip("/").split("?")[0]


def assert_safe_target(api_url, db_url):
    name = _db_name(db_url)
    if not SAFE_DB.match(name or ""):
        raise SystemExit(f"DITOLAK: database '{name or '?'}' bukan database test (proc_sandbox / *itest* / *_test)")
    host = urlparse(api_url).hostname or ""
    if host not in ("localhost", "127.0.0.1") and os.environ.get("UAT_ALLOW_REMOTE") != "1":
        raise SystemExit(f"DITOLAK: API {host} bukan backend lokal (set UAT_ALLOW_REMOTE=1 bila disengaja)")
    return name


class Api:
    def __init__(self, base, session):
        self.base, self.s = base.rstrip("/"), session

    def __call__(self, method, path, body=None, ok=(200,)):
        r = self.s.request(method, f"{self.base}/{path}", json=body, timeout=30)
        if ok and r.status_code not in ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            return {}


def _rows(x):
    return x.get("items", x.get("rows", [])) if isinstance(x, dict) else (x or [])


def ensure_master(api, coll, code, payload):
    found = [r for r in _rows(api("GET", f"master/{coll}?q={code}")) if str(r.get("code") or "").upper() == code.upper()]
    if found:
        cur = found[0]
        patch = {k: v for k, v in payload.items() if cur.get(k) != v}
        if patch:
            api("PUT", f"master/{coll}/{cur['id']}", {**cur, **patch})
        return {**cur, **patch}, False
    return api("POST", f"master/{coll}", {"code": code, **payload}), True


def ensure_user(api, email, name, password, overrides, division_id):
    users = [u for u in _rows(api("GET", "users")) if (u.get("email") or "").lower() == email]
    if len(users) > 1:
        raise RuntimeError(f"Duplikat user {email} terdeteksi ({len(users)})")
    body = {"name": name, "role": "warehouse", "is_active": True, "password": password, "divisions": [division_id],
            "warehouses": [], "scope": "limited"}
    if users:
        uid, created = users[0]["id"], False
        api("PUT", f"users/{uid}", body)
    else:
        uid, created = api("POST", "users", {"email": email, **body})["id"], True
    api("PUT", f"access/users/{uid}", {"overrides": overrides,
                                        "division_override": {"mode": "selected", "divisions": [division_id]}})
    return uid, created


def ensure_opening(api, wh, div, item, qty, cost):
    rows = api("GET", f"item-warehouse?warehouse_id={wh}&item_id={item}")
    if rows and float(rows[0].get("current_stock") or 0) > 0:
        return False
    api("POST", "adjustments", {"date": _dt.date.today().isoformat(), "warehouse_id": wh, "division_id": div,
                                "adj_type": "Opening", "reason": "UAT FIXTURE OPENING", "notes": "UAT FIXTURE OPENING",
                                "lines": [{"item_id": item, "adjustment": qty, "reason": "UAT FIXTURE",
                                           "approved_unit_cost": cost, "warehouse_id": wh}]})
    return True


def run(api, staff_pw, approver_pw, keep_opname=False):
    """Samakan kondisi fixture. `api` = Api ber-token admin tenant. Return ringkasan (tanpa password)."""
    out = {"created": [], "updated": []}

    def note(kind, created):
        out["created" if created else "updated"].append(kind)
    div_a, c = ensure_master(api, "divisions", DIV_ASSET[0], {"name": DIV_ASSET[1]}); note("division:Asset", c)
    div_o, c = ensure_master(api, "divisions", DIV_OPS[0], {"name": DIV_OPS[1]}); note("division:Operasional", c)
    cat, c = ensure_master(api, "item_categories", "UAT-KAT", {"name": "Kategori UAT"}); note("category", c)
    uom, c = ensure_master(api, "uoms", "UAT-PCS", {"name": "Pcs UAT"}); note("uom", c)
    wa, c = ensure_master(api, "warehouses", WH_ASSET[0], {"name": WH_ASSET[1], "division_id": div_a["id"], "is_active": True}); note("warehouse:UAT-GA", c)
    wo, c = ensure_master(api, "warehouses", WH_OPS[0], {"name": WH_OPS[1], "division_id": div_o["id"], "is_active": True}); note("warehouse:UAT-GO", c)
    ref = {"category_id": cat["id"], "base_uom_id": uom["id"], "unit": "PCS", "is_active": True}
    items = {}
    for code, name, div in (("UAT-BRG01", "Filter UAT Asset", div_a), ("UAT-BRG02", "Baut UAT Asset", div_a),
                            ("UAT-BRG03", "Oli UAT Operasional", div_o)):
        items[code], c = ensure_master(api, "items", code, {"name": name, "division_id": div["id"], **ref}); note(f"item:{code}", c)
    if not keep_opname:  # kondisi baku: tidak ada Opname aktif di gudang UAT
        for o in _rows(api("GET", "opname?page_size=500")):
            if o.get("warehouse_id") in (wa["id"], wo["id"]) and o.get("status") in ("Counting", "Review", "Waiting Approval"):
                api("POST", f"opname/{o['id']}/workflow", {"action": "cancel", "reason": "Reset fixture UAT"})
                out["updated"].append(f"opname-cancelled:{o.get('no')}")
    for wh, div, code, qty, cost in ((wa, div_a, "UAT-BRG01", 50, 1000), (wa, div_a, "UAT-BRG02", 200, 250),
                                     (wo, div_o, "UAT-BRG03", 40, 5000)):
        if ensure_opening(api, wh["id"], div["id"], items[code]["id"], qty, cost):
            out["created"].append(f"opening:{code}@{wh['code']}")
    sid, c = ensure_user(api, STAFF_EMAIL, "UAT Staff Asset (tanpa harga)", staff_pw, STAFF_OVERRIDES, div_a["id"]); note("user:staff", c)
    aid, c = ensure_user(api, APPROVER_EMAIL, "UAT Approver Asset (harga)", approver_pw, APPROVER_OVERRIDES, div_a["id"]); note("user:approver", c)
    out.update({"staff_id": sid, "approver_id": aid, "division_asset": div_a["id"], "division_ops": div_o["id"],
                "wh_asset": wa["id"], "wh_ops": wo["id"], "items": {k: v["id"] for k, v in items.items()}})
    return out


def main():
    backend = Path(__file__).resolve().parents[1]
    env_db = next((ln.split("=", 1)[1].strip().strip('"') for ln in open(backend / ".env") if ln.startswith("DATABASE_URL=")), "")
    api_url = os.environ.get("UAT_API_URL", "http://localhost:8001/api")
    name = assert_safe_target(api_url, os.environ.get("UAT_DATABASE_URL") or env_db)
    em, pw = os.environ.get("UAT_ADMIN_EMAIL"), os.environ.get("UAT_ADMIN_PASSWORD")
    if not em or not pw:
        raise SystemExit("UAT_ADMIN_EMAIL dan UAT_ADMIN_PASSWORD wajib diisi (environment), tidak disimpan di repo")
    s = requests.Session()
    r = s.post(f"{api_url.rstrip('/')}/auth/login", json={"email": em, "password": pw}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"Login admin gagal ({r.status_code})")
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    cred_out = Path(os.environ.get("UAT_CRED_OUT", "/app/memory/uat_stock_opname_credentials.md"))
    staff_pw, appr_pw = os.environ.get("UAT_STAFF_PASSWORD"), os.environ.get("UAT_APPROVER_PASSWORD")
    if (not staff_pw or not appr_pw) and cred_out.exists():  # pakai ulang password tersimpan -> kondisi konsisten
        txt = cred_out.read_text()
        staff_pw = staff_pw or (re.search(rf"{re.escape(STAFF_EMAIL)} \| (\S+) \|", txt) or [None, None])[1]
        appr_pw = appr_pw or (re.search(rf"{re.escape(APPROVER_EMAIL)} \| (\S+) \|", txt) or [None, None])[1]
    staff_pw = staff_pw or ("Uat-" + secrets.token_urlsafe(12))
    appr_pw = appr_pw or ("Uat-" + secrets.token_urlsafe(12))
    res = run(Api(api_url, s), staff_pw, appr_pw, keep_opname=os.environ.get("UAT_KEEP_OPNAME") == "1")
    cred_out.parent.mkdir(parents=True, exist_ok=True)
    cred_out.write_text(
        f"# Kredensial UAT Stock Opname — DB TEST `{name}` (dibuat oleh scripts/uat_fixture_stock_opname.py)\n\n"
        "| Peran | Email | Password | Catatan |\n|---|---|---|---|\n"
        f"| Staff Asset TANPA harga | {STAFF_EMAIL} | {staff_pw} | hitung/review/ajukan; tanpa approve; divisi Asset |\n"
        f"| Approver Asset DENGAN harga | {APPROVER_EMAIL} | {appr_pw} | approve & posting; divisi Asset |\n\n"
        f"Gudang: {WH_ASSET[0]} (Asset), {WH_OPS[0]} (Operasional, harus DITOLAK untuk dua user di atas).\n")
    os.chmod(cred_out, 0o600)
    print(f"Fixture UAT siap pada DB '{name}'. Dibuat: {len(res['created'])}, disamakan: {len(res['updated'])}.")
    print("  dibuat   :", ", ".join(res["created"]) or "-")
    print("  disamakan:", ", ".join(res["updated"]) or "-")
    print(f"  kredensial staff/approver ditulis ke {cred_out} (chmod 600, tidak dicetak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
