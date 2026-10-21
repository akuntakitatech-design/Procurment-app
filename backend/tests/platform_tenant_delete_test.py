"""Integrasi: Hapus Tenant dua tahap (soft delete -> pulihkan / hapus permanen) oleh Platform Super Admin.

Memakai tenant sekali pakai yang dibuat oleh test ini sendiri lalu dihapus permanen; tenant lain tidak disentuh.
Tenant default (DEFAULT_TENANT_ID) hanya diuji penolakannya (tidak ada penulisan karena guard berjalan lebih dulu).

Env:
  TEST_API_URL            default http://127.0.0.1:8000/api
  TEST_PLATFORM_TOKEN     access token Platform Super Admin (opsional), atau
  PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD untuk login
  DEFAULT_TENANT_ID       default tenant-pt-real
"""
import os
import sys
import uuid

import requests

API = os.environ.get("TEST_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
DEFAULT_TENANT_ID = os.environ.get("DEFAULT_TENANT_ID", "tenant-pt-real")
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
passed = 0


def check(ok, msg, extra=None):
    global passed
    if not ok:
        raise AssertionError(f"{msg} | {extra!r}")
    passed += 1
    print(f"PASS: {msg}")


def platform_session():
    s = requests.Session()
    token = os.environ.get("TEST_PLATFORM_TOKEN")
    if not token:
        r = s.post(f"{API}/auth/login", json={"email": os.environ["PLATFORM_ADMIN_EMAIL"],
                                              "password": os.environ["PLATFORM_ADMIN_PASSWORD"]}, timeout=60)
        check(r.status_code == 200 and r.json().get("is_platform_admin"), "Login Platform Super Admin", r.status_code)
        token = r.json()["token"]
    s.headers["Authorization"] = f"Bearer {token}"
    me = s.get(f"{API}/auth/me", timeout=60)
    check(me.status_code == 200 and me.json().get("is_platform_admin"), "Sesi Platform Super Admin valid", me.status_code)
    return s


def login(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code == 200:
        s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s, r


def main():
    P = platform_session()
    run = uuid.uuid4().hex[:8]

    # ---- tenant default dilindungi (guard sebelum penulisan apa pun) ----
    r = P.get(f"{API}/platform/tenants/{DEFAULT_TENANT_ID}/delete-preview", timeout=120)
    check(r.status_code == 200 and r.json().get("protected") and not r.json().get("deletable"),
          "Preview tenant default: protected, tidak dapat dihapus", r.text[:200])
    r = P.post(f"{API}/platform/tenants/{DEFAULT_TENANT_ID}/delete", json={"confirm_code": "X", "reason": "uji guard"}, timeout=60)
    check(r.status_code == 409, "Hapus tenant default ditolak 409", r.status_code)
    r = P.post(f"{API}/platform/tenants/{DEFAULT_TENANT_ID}/purge", json={"confirm_code": "X"}, timeout=60)
    check(r.status_code == 409, "Hapus permanen tenant default ditolak 409", r.status_code)
    r = P.get(f"{API}/platform/tenants/{DEFAULT_TENANT_ID}/cp0", timeout=120)
    check(r.status_code == 200 and r.json().get("is_default_tenant") is True, "Detail tenant default menandai is_default_tenant", r.status_code)

    # ---- tenant sekali pakai ----
    email = f"qa-del-{run}@example.com"
    password = f"QaDelete-{run}!"
    r = P.post(f"{API}/platform/tenants", json={
        "company_name": f"QA Hapus Tenant {run}", "workspace_slug": f"qa-del-{run}", "pic_name": "QA Hapus",
        "whatsapp": "+628120000000", "email": email, "notes": "Tenant uji otomatis fitur hapus tenant"}, timeout=120)
    check(r.status_code == 200 and r.json().get("ok"), "Tenant uji dibuat", r.text[:300])
    tid, code = r.json()["tenant_id"], r.json()["tenant_code"]
    token = r.json()["activation_url"].rstrip("/").split("/")[-1]
    r = requests.post(f"{API}/platform/activation/{token}/accept", json={"password": password}, timeout=60)
    check(r.status_code == 200, "Tenant Admin uji diaktivasi", r.text[:200])
    T, r = login(email, password)
    check(r.status_code == 200, "Login Tenant Admin uji", r.status_code)
    r = T.post(f"{API}/settings/company/logo", files={"file": ("logo.png", PNG, "image/png")}, timeout=120)
    check(r.status_code == 200 and str(r.json().get("logo_path", "")).startswith(f"procureflow/tenants/{tid}/"),
          "Upload logo -> objek storage di prefix tenant", r.text[:200])
    r = T.get(f"{API}/company/logo", timeout=120)
    check(r.status_code == 200 and r.content == PNG, "Logo terbaca dari storage", r.status_code)

    # ---- preview ----
    pv = P.get(f"{API}/platform/tenants/{tid}/delete-preview", timeout=180).json()
    check(pv.get("deletable") and not pv.get("purgeable") and pv.get("confirm_code") == code,
          "Preview: deletable, belum purgeable, confirm_code = kode tenant", pv)
    check(pv.get("users", 0) >= 1 and pv.get("total_documents", 0) > 0, "Preview menghitung user & dokumen tenant",
          (pv.get("users"), pv.get("total_documents")))
    check((pv.get("storage") or {}).get("objects", 0) >= 1, "Preview menghitung objek storage tenant", pv.get("storage"))

    # ---- tahap 1: soft delete ----
    r = P.post(f"{API}/platform/tenants/{tid}/purge", json={"confirm_code": code}, timeout=60)
    check(r.status_code == 409, "Hapus permanen sebelum soft delete ditolak 409", r.status_code)
    r = P.post(f"{API}/platform/tenants/{tid}/delete", json={"confirm_code": "SALAH", "reason": "uji"}, timeout=60)
    check(r.status_code == 400, "Kode konfirmasi salah ditolak 400", r.status_code)
    r = P.post(f"{API}/platform/tenants/{tid}/delete", json={"confirm_code": code, "reason": "x"}, timeout=60)
    check(r.status_code == 422, "Alasan < 3 karakter ditolak 422", r.status_code)
    r = P.post(f"{API}/platform/tenants/{tid}/delete", json={"confirm_code": code.lower(), "reason": "uji otomatis hapus"}, timeout=120)
    check(r.status_code == 200 and r.json().get("status") == "deleted", "Soft delete berhasil (kode tidak case-sensitive)", r.text[:200])
    r = P.post(f"{API}/platform/tenants/{tid}/delete", json={"confirm_code": code, "reason": "lagi"}, timeout=60)
    check(r.status_code == 409, "Soft delete ganda ditolak 409", r.status_code)
    r = T.get(f"{API}/auth/me", timeout=60)
    check(r.status_code == 401, "Sesi lama Tenant Admin dicabut (401)", r.status_code)
    T, r = login(email, password)
    check(r.status_code == 200, "Login tetap bisa untuk membaca status workspace", r.status_code)
    st = T.get(f"{API}/subscription/status", timeout=60).json()
    check(st.get("access_mode") == "locked" and st.get("status") == "deleted" and "dihapus" in (st.get("message") or ""),
          "Status langganan: locked/deleted dengan pesan dihapus", st)
    r = T.get(f"{API}/company/logo", timeout=60)
    check(r.status_code == 403 and r.json().get("code") == "SUBSCRIPTION_LOCKED", "API tenant terkunci (403)", r.status_code)
    det = P.get(f"{API}/platform/tenants/{tid}/cp0", timeout=120).json()
    check(det.get("status") == "deleted" and det.get("deleted_reason") == "uji otomatis hapus"
          and (det.get("deletion_history") or [{}])[-1].get("action") == "delete", "Detail: status, alasan & histori hapus", det.get("status"))
    dash = P.get(f"{API}/platform/dashboard", timeout=300).json()
    check(dash.get("deleted", 0) >= 1 and all(a.get("tenant_id") != tid for a in dash.get("attention") or []),
          "Dashboard: tenant terhapus dihitung di 'deleted' & tidak di Perlu Perhatian", dash.get("deleted"))

    # ---- pulihkan ----
    r = P.post(f"{API}/platform/tenants/{tid}/restore", json={"reason": "uji pulihkan"}, timeout=120)
    check(r.status_code == 200 and r.json().get("status") == "active", "Tenant dipulihkan ke status sebelumnya", r.text[:200])
    T, r = login(email, password)
    r = T.get(f"{API}/company/logo", timeout=60)
    check(r.status_code == 200 and r.content == PNG, "Setelah dipulihkan, data & file utuh dan akses kembali", r.status_code)
    r = P.post(f"{API}/platform/tenants/{tid}/restore", json={}, timeout=60)
    check(r.status_code == 409, "Pulihkan tenant yang tidak dihapus ditolak 409", r.status_code)

    # ---- tahap 2: hapus permanen ----
    r = P.post(f"{API}/platform/tenants/{tid}/delete", json={"confirm_code": code, "reason": "uji hapus permanen"}, timeout=120)
    check(r.status_code == 200, "Soft delete kedua sebelum purge", r.status_code)
    r = P.post(f"{API}/platform/tenants/{tid}/purge", json={"confirm_code": "SALAH"}, timeout=60)
    check(r.status_code == 400, "Purge dengan kode salah ditolak 400", r.status_code)
    r = P.post(f"{API}/platform/tenants/{tid}/purge", json={"confirm_code": code}, timeout=900)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    check(r.status_code == 200 and body.get("documents_deleted", 0) >= pv["total_documents"]
          and body.get("storage_objects_deleted", 0) >= 1, "Hapus permanen: dokumen & objek storage terhapus", body)
    print("  ringkasan purge:", {k: body.get(k) for k in ("documents_deleted", "storage_objects_deleted", "storage_bytes_deleted")})
    r = P.get(f"{API}/platform/tenants/{tid}/cp0", timeout=60)
    check(r.status_code == 404, "Tenant tidak ada lagi (404)", r.status_code)
    r = P.get(f"{API}/platform/tenants/{tid}/delete-preview", timeout=60)
    check(r.status_code == 404, "Preview tenant terhapus permanen 404", r.status_code)
    _, r = login(email, password)
    check(r.status_code == 401, "User tenant terhapus permanen tidak bisa login", r.status_code)
    lst = P.get(f"{API}/platform/tenants", timeout=300).json()
    check(all(t.get("id") != tid for t in lst), "Tenant hilang dari daftar platform")
    r = P.get(f"{API}/platform/tenants/{DEFAULT_TENANT_ID}/cp0", timeout=120)
    check(r.status_code == 200 and r.json().get("status") != "deleted", "Tenant default tetap utuh", r.status_code)

    print(f"\nTENANT_ID_UJI={tid} TENANT_CODE_UJI={code}")
    print(f"{passed} passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
