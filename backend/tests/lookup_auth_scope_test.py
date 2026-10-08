"""Regression shared lookup + auth (bug dropdown master kosong / Not authenticated pada 4 modul Persediaan).
Backend dev/staging, tenant QA sementara via /saas/register (tidak menyentuh data tenant lain).
Membuktikan: auth lookup (401 tanpa/expired token), refresh cookie konsisten dengan login, single-session tetap,
tenant isolation, division scope (termasuk gudang per divisi), permission (denied <=> 403) TIDAK berubah."""
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import receipt_control_test as T
import requests
from dotenv import dotenv_values
from vendor_invoice_test import PW, U

call, check, API = T.call, T.check, T.API
STOCK = "divisions,contacts,warehouses,projects,units,items,uoms,item_categories"
NAMES = STOCK.split(",")
SESSION_REPLACED = "Sesi Anda telah berakhir karena akun ini login di perangkat lain."


def ids(batch, name):
    return {r["id"] for r in (batch.get("data") or {}).get(name) or []}


def cookie_attrs(resp, name):
    for h in resp.raw.headers.getlist("set-cookie") if hasattr(resp.raw.headers, "getlist") else []:
        if h.startswith(name + "="):
            parts = [p.strip().lower() for p in h.split(";")[1:]]
            return {"secure": "secure" in parts, "samesite": next((p.split("=")[1] for p in parts if p.startswith("samesite=")), None)}
    return None


def mk_user(role, divs=None, overrides=None):
    email = f"lk_{role}_{uuid.uuid4().hex[:6]}@example.com"
    _, u = call("POST", "users", {"email": email, "password": PW, "name": f"QA {role}", "role": role}, 200)
    body = {"overrides": overrides or {}}
    if divs is not None:
        body["division_override"] = {"mode": "selected", "divisions": divs}
    if divs is not None or overrides:
        call("PUT", f"access/users/{u['id']}", body, 200)
    return email


# Tolak semua alasan izin lookup "units" (lihat LOOKUP_REASONS) -> units harus denied, lainnya tetap sesuai role.
DENY_UNITS = {f"{m}.{a}": "deny" for m in ("mro", "ro", "po", "mi", "loan") for a in ("create", "edit")}
DENY_UNITS.update({"units.view": "deny"})


def main():
    # ---------------- Tenant B (dibuat dulu; T.setup mengganti sesi global)
    T.setup()
    sc, bB = call("GET", f"lookup-batch?names={STOCK}")
    check("Tenant B: lookup-batch 200", sc == 200, sc)
    b_ids = {n: ids(bB, n) for n in NAMES}

    # ---------------- Tenant A (sesi bersih: jangan bawa token/cookie tenant B ke login tenant A)
    T.S.headers.pop("Authorization", None)
    T.S.cookies.clear()
    M = T.setup()
    u = uuid.uuid4().hex[:5]
    dA = M["div"]
    dB = call("POST", "master/divisions", {"code": f"LB{u}", "name": f"Divisi Lain {u}"}, 200)[1]
    # Paket starter: maks 2 gudang -> pakai 2 gudang fixture, set divisi masing-masing.
    whA, whB = M["wh"], M["wh2"]
    for wh, dv in ((whA, dA), (whB, dB)):
        call("PUT", f"master/warehouses/{wh['id']}", {"code": wh["code"], "name": wh["name"], "division_id": dv["id"], "is_active": True}, 200)
    itB = call("POST", "master/items", {"code": f"LI{u}", "name": "Barang Div Lain", "unit": "PCS", "is_active": True,
                                        "category_id": M["cat"]["id"], "division_id": dB["id"], "base_uom_id": M["uom"]["id"]}, 200)[1]
    prB = call("POST", "master/projects", {"code": f"LP{u}", "name": "Project Div Lain", "division_id": dB["id"]}, 200)[1]

    sc, bA = call("GET", f"lookup-batch?names={STOCK}")
    check("Admin A: lookup-batch 200 + denied kosong", sc == 200 and bA.get("denied") == [], (sc, bA.get("denied")))
    check("Admin A: master STOCK_REFS terisi (divisi/gudang/project/barang/satuan)",
          all(len(bA["data"][n]) > 0 for n in ("divisions", "warehouses", "projects", "items", "uoms")))
    check("Tenant isolation: tenant A tidak melihat satu pun master tenant B",
          all(not (ids(bA, n) & b_ids[n]) for n in NAMES), {n: len(ids(bA, n) & b_ids[n]) for n in NAMES})
    sc, wB = call("GET", "lookup/warehouses")
    check("Tenant isolation: /lookup/warehouses A tanpa gudang B", sc == 200 and not ({r["id"] for r in wB} & b_ids["warehouses"]))

    # ---------------- Auth pada lookup
    r = requests.get(f"{API}/lookup-batch", params={"names": STOCK})
    check("Tanpa token: /lookup-batch 401 Not authenticated (bukan 200 [])", r.status_code == 401 and r.json().get("detail") == "Not authenticated", r.status_code)
    r = requests.get(f"{API}/lookup/warehouses")
    check("Tanpa token: /lookup/warehouses 401", r.status_code == 401)
    secret = dotenv_values("/app/backend/.env").get("JWT_SECRET")
    adm_email = (call("GET", "auth/me")[1] or {}).get("email")
    tokA = requests.post(f"{API}/auth/login", json={"email": adm_email, "password": "TestPass123!"}).json().get("token")
    T.S.cookies.clear()
    T.S.headers.update({"Authorization": f"Bearer {tokA}"})
    claims = jwt.decode(tokA, secret, algorithms=["HS256"])
    expired = jwt.encode({**claims, "exp": datetime.now(timezone.utc) - timedelta(minutes=5)}, secret, algorithm="HS256")
    r = requests.get(f"{API}/lookup-batch", params={"names": STOCK}, headers={"Authorization": f"Bearer {expired}"})
    check("Token expired: /lookup-batch 401 Token expired", r.status_code == 401 and r.json().get("detail") == "Token expired")

    # ---------------- Refresh: cookie konsisten dengan login + retry pulih + single session
    for proto in ("https", "http"):
        S = requests.Session()
        lr = S.post(f"{API}/auth/login", json={"email": adm_email, "password": "TestPass123!"}, headers={"X-Forwarded-Proto": proto})
        # Cookie Secure tidak dikirim requests via http://localhost -> kirim refresh cookie hasil login secara eksplisit.
        rr = requests.post(f"{API}/auth/refresh", headers={"X-Forwarded-Proto": proto}, cookies={"refresh_token": lr.cookies.get("refresh_token") or ""})
        la, ra = cookie_attrs(lr, "refresh_token"), cookie_attrs(rr, "refresh_token")
        check(f"Refresh ({proto}): 200 + token baru", rr.status_code == 200 and bool(rr.json().get("token")))
        check(f"Refresh ({proto}): atribut cookie refresh = login (Secure/SameSite)", la is not None and la == ra, (la, ra))
        new_tok = rr.json().get("token")
        r2 = requests.get(f"{API}/lookup-batch", params={"names": STOCK}, headers={"Authorization": f"Bearer {new_tok}"})
        check(f"Refresh ({proto}): token hasil refresh -> lookup-batch 200 terisi", r2.status_code == 200 and len(r2.json()["data"]["warehouses"]) > 0)
    old = requests.Session()
    old.post(f"{API}/auth/login", json={"email": adm_email, "password": "TestPass123!"})
    newer = requests.Session()
    nl = newer.post(f"{API}/auth/login", json={"email": adm_email, "password": "TestPass123!"})
    rr = old.post(f"{API}/auth/refresh")
    check("Single session: refresh sesi lama ditolak session_replaced", rr.status_code == 401 and rr.json().get("detail") == SESSION_REPLACED, rr.status_code)
    r3 = requests.get(f"{API}/lookup-batch", params={"names": "warehouses"}, headers={"Authorization": f"Bearer {nl.json().get('token')}"})
    check("Single session: sesi terbaru tetap valid", r3.status_code == 200)
    r4 = old.post(f"{API}/auth/refresh")
    check("Refresh tanpa/invalid cookie tetap 401 (kredensial invalid)", r4.status_code == 401)
    nr = requests.post(f"{API}/auth/refresh")
    check("Refresh tanpa cookie: 401 No refresh token", nr.status_code == 401 and nr.json().get("detail") == "No refresh token")
    T.S.cookies.clear()  # cookie access_token lama diprioritaskan backend -> pakai Bearer sesi terbaru saja
    T.S.headers.update({"Authorization": f"Bearer {nl.json().get('token')}"})

    # ---------------- Division scope (gudang/barang/project per divisi)
    wh_email = mk_user("warehouse", [dA["id"]])
    W = U(wh_email)
    sc, bW = W("GET", f"lookup-batch?names={STOCK}")
    check("User divisi A: lookup-batch 200", sc == 200, sc)
    check("Division scope: gudang divisi lain tidak terlihat", whB["id"] not in ids(bW, "warehouses") if "warehouses" in bW.get("data", {}) else True)
    check("Division scope: barang divisi lain tidak terlihat", itB["id"] not in ids(bW, "items") if "items" in bW.get("data", {}) else True)
    check("Division scope: project divisi lain tidak terlihat", prB["id"] not in ids(bW, "projects") if "projects" in bW.get("data", {}) else True)
    check("Division scope: gudang divisi sendiri tetap terlihat (bila diizinkan)", whA["id"] in ids(bW, "warehouses") if "warehouses" in bW.get("data", {}) else "warehouses" in bW.get("denied", []))
    sc, iw = W("GET", "lookup/warehouses")
    check("Division scope /lookup/warehouses konsisten dengan batch", (sc == 200 and {r["id"] for r in iw} == ids(bW, "warehouses")) or (sc == 403 and "warehouses" in bW["denied"]), sc)

    # ---------------- Permission: denied di batch <=> 403 di individual; data denied tidak pernah dikirim
    roles_checked, any_denied, any_denied_units = 0, False, False
    for role, ov in (("warehouse", None), ("finance", None), ("warehouse", DENY_UNITS)):
        try:
            email = mk_user(role, overrides=ov)
        except KeyError as exc:  # batas user paket tercapai -> profil dilewati (dicek oleh roles_checked)
            print(f"SKIP {role}: {exc}")
            continue
        role = role + ("+deny_units" if ov else "")
        C = U(email)
        sc, b = C("GET", f"lookup-batch?names={STOCK}")
        if sc != 200:
            continue
        roles_checked += 1
        denied = set(b.get("denied") or [])
        any_denied = any_denied or bool(denied)
        if role.endswith("+deny_units"):
            any_denied_units = "units" in denied
        check(f"Permission [{role}]: nama denied tidak ada di data", not (denied & set((b.get("data") or {}).keys())), denied)
        for n in NAMES:
            isc, _ = C("GET", f"lookup/{n}")
            check(f"Permission [{role}] {n}: batch {'denied' if n in denied else 'allowed'} == individual {isc}",
                  (n in denied and isc == 403) or (n not in denied and isc == 200), isc)
    check("Permission: 3 profil izin diuji", roles_checked == 3, roles_checked)
    check("Permission: profil tanpa izin Unit -> 'units' denied (bukan [] 200)", any_denied_units, None)
    print(f"INFO roles_checked={roles_checked} any_denied={any_denied}")

    failed = [n for n, ok in T.RESULTS if not ok]
    print(f"\n{len(T.RESULTS) - len(failed)}/{len(T.RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
