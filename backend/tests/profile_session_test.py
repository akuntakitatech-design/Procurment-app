"""Profil Saya + Ganti Password + Satu Sesi Aktif per User (token_version). Throwaway tenants, localhost:8001."""
import os
import sys
import uuid
from urllib.parse import unquote, urlparse

import requests

import receipt_control_test as T

check, API = T.check, T.API
PW, PW2 = "TestPass123!", "BaruSekali#2026"
MSG = "Sesi Anda telah berakhir karena akun ini login di perangkat lain."


class C:
    """Klien API terpisah (perangkat/browser berbeda) — header Bearer saja, tanpa cookie bersama."""
    def __init__(self, email=None, password=PW, token=None):
        self.S = requests.Session()
        self.token = token
        if email:
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": password})
            self.login_status = r.status_code
            self.token = r.json().get("token") if r.status_code == 200 else None

    def __call__(self, method, path, body=None):
        r = requests.request(method, f"{API}/{path}", json=body, headers={"Authorization": f"Bearer {self.token}"})
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}


def register(prefix):
    u = uuid.uuid4().hex[:8]
    email = f"{prefix}_{u}@example.com"
    r = requests.post(f"{API}/saas/register", json={"company_name": f"PS {u}", "pic_name": "QA", "email": email, "whatsapp": "+628123456789",
                                                  "workspace_slug": f"{prefix}-{u}", "plan_code": "starter", "password": PW,
                                                  "address": "x", "terms_accepted": True})
    return email, r.status_code


def db_contains(text):
    env = {}
    for line in open(os.path.join(os.path.dirname(__file__), "..", ".env")):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip().strip('"')
    url = urlparse(env.get("DATABASE_URL", ""))
    import pymysql
    con = pymysql.connect(host=url.hostname or "127.0.0.1", port=url.port or 3306, user=unquote(url.username or ""),
                          password=unquote(url.password or ""), database=(url.path or "/").lstrip("/") or env.get("DB_NAME"))
    try:
        with con.cursor() as cur:
            hits = 0
            for table in ("users", "audit_logs"):
                cur.execute(f"SELECT COUNT(*) FROM `{table}` WHERE doc LIKE %s", (f"%{text}%",))
                hits += cur.fetchone()[0]
            return hits
    finally:
        con.close()


def main():
    email, sc = register("ps")
    check("Registrasi tenant uji", sc == 200, sc)

    # ---------------- Single active session
    A = C(email)
    check("1. Client A login berhasil", A.login_status == 200 and bool(A.token))
    sc, me = A("GET", "auth/me")
    check("2. Client A request authenticated berhasil", sc == 200 and me.get("email") == email, sc)
    tenant_id = me.get("tenant_id")
    A_tab2 = C(token=A.token)
    sc, _ = A_tab2("GET", "auth/me")
    check("10. Multi-tab (token sama) tetap berjalan", sc == 200, sc)
    B = C(email)
    check("3. Client B login (user sama) berhasil", B.login_status == 200 and B.token != A.token)
    sc, _ = B("GET", "auth/me")
    check("4. Client B request berhasil", sc == 200, sc)
    sc, r = A("GET", "auth/me")
    check("5. Client A request berikutnya -> 401", sc == 401, sc)
    check("6. Pesan 401 Bahasa Indonesia sesuai requirement", r.get("detail") == MSG, r)
    sc, r = A("GET", "po")
    check("13. Direct API dengan token lama ditolak", sc == 401 and r.get("detail") == MSG, (sc, r))
    sc, _ = A_tab2("GET", "auth/me")
    check("10b. Tab lain dengan token lama ikut berakhir", sc == 401, sc)
    # refresh token sesi lama juga ditolak
    rr = requests.post(f"{API}/auth/login", json={"email": email, "password": PW})
    stale_refresh = rr.cookies.get("refresh_token")
    B = C(email)  # login lagi -> refresh token di atas menjadi usang
    if stale_refresh:
        r = requests.post(f"{API}/auth/refresh", cookies={"refresh_token": stale_refresh})
        check("Refresh token sesi lama ditolak", r.status_code == 401 and r.json().get("detail") == MSG, (r.status_code, r.text[:120]))

    # user lain di tenant yang sama tidak saling invalidate
    sc, u2 = B("POST", "users", {"email": f"ps2_{uuid.uuid4().hex[:6]}@example.com", "password": PW, "name": "QA Dua", "role": "manager"})
    check("Buat user kedua", sc == 200, (sc, u2))
    U2 = C(u2.get("email"))
    sc, _ = U2("GET", "auth/me")
    sc_b, _ = B("GET", "auth/me")
    check("8. Login user berbeda tidak saling invalidate", sc == 200 and sc_b == 200, (sc, sc_b))
    # tenant lain tidak saling invalidate
    email_t2, _ = register("ps-t")
    X = C(email_t2)
    sc_x, _ = X("GET", "auth/me")
    sc_b, _ = B("GET", "auth/me")
    sc_u2, _ = U2("GET", "auth/me")
    check("9. Tenant berbeda tidak saling invalidate", sc_x == 200 and sc_b == 200 and sc_u2 == 200, (sc_x, sc_b, sc_u2))

    # logout: token lama tidak boleh dipakai lagi; logout dengan token usang tidak mematikan sesi baru
    sc, _ = U2("POST", "auth/logout")
    sc2, r = U2("GET", "auth/me")
    check("11. Logout membuat token lama invalid", sc == 200 and sc2 == 401, (sc, sc2))
    U2b = C(u2.get("email"))
    sc, _ = U2("POST", "auth/logout")  # token usang
    sc2, _ = U2b("GET", "auth/me")
    check("11b. Logout dari token usang tidak memutus sesi aktif yang baru", sc2 == 200, sc2)

    # ---------------- Profil Saya
    sc, prof = B("GET", "profile")
    check("Profil: user dapat membuka profil sendiri", sc == 200 and prof.get("email") == email and "password_hash" not in prof, prof)
    sc, r = B("PUT", "profile", {"name": "QA Profil Baru"})
    check("Profil: ubah nama berhasil", sc == 200 and r.get("name") == "QA Profil Baru", (sc, r))
    sc, r = B("PUT", "profile", {"phone": "+62 812-3456-7890"})
    check("Profil: ubah telepon berhasil", sc == 200 and r.get("phone") == "+62 812-3456-7890", (sc, r))
    sc, r = B("PUT", "profile", {"phone": "abc"})
    check("Profil: telepon tidak valid ditolak", sc == 400, (sc, r))
    sc, r = B("PUT", "profile", {"email": u2.get("email")})
    check("Profil: email milik akun lain ditolak (409)", sc == 409, (sc, r))
    new_email = f"psbaru_{uuid.uuid4().hex[:6]}@example.com"
    sc, r = B("PUT", "profile", {"email": new_email})
    check("Profil: ubah email berhasil", sc == 200 and r.get("email") == new_email, (sc, r))
    for field, val in (("role", "admin"), ("permissions", ["view"]), ("permission_overrides", {"po.approve": "allow"}),
                       ("divisions", ["x"]), ("division_override", {"mode": "all"}), ("tenant_id", "tenant-lain"),
                       ("is_active", False), ("id", "u-baru")):
        sc, r = B("PUT", "profile", {"name": "QA Profil Baru", field: val})
        check(f"Profil: tidak dapat mengubah {field} melalui API profile", sc == 400, (sc, r))
    sc, me = B("GET", "auth/me")
    check("Profil: role/tenant/status tetap", me.get("role") == "admin" and me.get("tenant_id") == tenant_id and me.get("is_active", True) is True, me.get("role"))

    # ---------------- Ganti password
    sc, r = B("POST", "auth/change-password", {"current_password": "salah123", "new_password": PW2, "confirm_password": PW2})
    check("Password saat ini salah -> reject", sc == 400 and "salah" in r.get("detail", ""), (sc, r))
    sc, r = B("POST", "auth/change-password", {"current_password": PW, "new_password": PW2, "confirm_password": PW2 + "x"})
    check("Konfirmasi berbeda -> reject", sc == 400 and "Konfirmasi" in r.get("detail", ""), (sc, r))
    sc, r = B("POST", "auth/change-password", {"current_password": PW, "new_password": "pendek", "confirm_password": "pendek"})
    check("Password baru di bawah policy -> reject", sc == 400 and "minimal" in r.get("detail", ""), (sc, r))
    other = C(new_email)  # sesi lain (akan menggantikan B) -> B login ulang agar B = sesi aktif
    B = C(new_email)
    sc, r = B("POST", "auth/change-password", {"current_password": PW, "new_password": PW2, "confirm_password": PW2})
    check("Ganti password berhasil", sc == 200 and r.get("token") and r.get("message") == "Password berhasil diubah.", (sc, r))
    old_tok = B.token
    B.token = r.get("token")
    sc, _ = B("GET", "auth/me")
    check("12. Sesi current tetap valid setelah ganti password (token dirotasi)", sc == 200, sc)
    sc, _ = C(token=old_tok)("GET", "auth/me")
    check("12b. Token lama sebelum ganti password invalid", sc == 401, sc)
    sc, _ = other("GET", "auth/me")
    check("12c. Sesi lama lain tetap invalid", sc == 401, sc)
    check("Login dengan password lama gagal", C(new_email, PW).login_status == 401)
    NB = C(new_email, PW2)
    check("Login dengan password baru berhasil", NB.login_status == 200)

    # ---------------- Audit & kerahasiaan password
    sc, logs = NB("GET", f"audit?entity=user&entity_id={me['id']}")
    acts = [x.get("action") for x in (logs if isinstance(logs, list) else [])]
    check("Audit update_profile tercatat", "update_profile" in acts, acts)
    check("Audit change_password tercatat", "change_password" in acts, acts)
    cp = next((x for x in logs if x.get("action") == "change_password"), {})
    check("Audit change_password tanpa nilai password/hash", not cp.get("before") and not cp.get("after") and PW2 not in str(cp), cp)
    up = next((x for x in logs if x.get("action") == "update_profile" and "email" in (x.get("after") or {})), {})
    check("Audit update_profile menyimpan field berubah", (up.get("after") or {}).get("email") == new_email, up)
    try:
        hits = db_contains(PW2)
        check("Plaintext password tidak ada di DB (users/audit_logs)", hits == 0, hits)
    except Exception as e:  # noqa: BLE001
        check("Plaintext password tidak ada di DB (users/audit_logs)", False, repr(e))
    log_txt = ""
    for f in ("/var/log/supervisor/backend.out.log", "/var/log/supervisor/backend.err.log"):
        try:
            log_txt += open(f, errors="ignore").read()[-2_000_000:]
        except OSError:
            pass
    check("Plaintext password tidak muncul di log backend", PW2 not in log_txt)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
