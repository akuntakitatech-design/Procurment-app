"""Disposable integration test for SaaS tenant registration and platform administration."""
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient


API = os.environ.get("TEST_API_URL", "http://tenant-test-api:8000/api").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://tenant-test-mongodb:27017")
DB_NAME = os.environ.get("DB_NAME", "procurement_saas_registration_test")
PLATFORM_EMAIL = os.environ.get("PLATFORM_ADMIN_EMAIL", "platform-test@example.test")
PLATFORM_PASSWORD = os.environ.get("PLATFORM_ADMIN_PASSWORD", "PlatformTest!123")
OWNER_PASSWORD = "OwnerTenant!123"
INVITED_PASSWORD = "InvitedUser!123"
TEST_EMAIL_DOMAIN = os.environ.get("TEST_EMAIL_DOMAIN", "akuntakita.com")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            r = requests.get(f"{base}/docs", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend test tidak siap dalam 75 detik")


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Login {email} gagal: HTTP {r.status_code} {r.text}")
    token = r.json().get("token")
    check(bool(token), f"Token login tersedia untuk {email}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s, r.json()


def register(payload, expected=200):
    r = requests.post(f"{API}/saas/register", json=payload, timeout=30)
    if r.status_code != expected:
        body = (r.text or "").strip()
        print(
            f"REGISTER DEBUG: expected={expected} actual={r.status_code} body={body[:2000]}",
            file=sys.stderr,
        )
        raise AssertionError(
            f"Registrasi diharapkan HTTP {expected}, aktual HTTP {r.status_code}; body={body[:1000]}"
        )
    print(f"PASS: Registrasi mengembalikan HTTP {expected}")
    return r


def main():
    wait_api()
    run_id = uuid.uuid4().hex[:10]
    company_a = f"PT SaaS A {run_id}"
    company_b = f"PT SaaS B {run_id}"
    slug_a = f"saas-a-{run_id}"
    slug_b = f"saas-b-{run_id}"
    email_a = f"owner-a-{run_id}@{TEST_EMAIL_DOMAIN}"
    email_b = f"owner-b-{run_id}@{TEST_EMAIL_DOMAIN}"

    mongo = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    db = mongo[DB_NAME]
    mongo.admin.command("ping")

    try:
        cfg = requests.get(f"{API}/saas/public-config", timeout=15)
        check(cfg.status_code == 200, "Public config SaaS dapat dibaca")
        cfgj = cfg.json()
        check(cfgj.get("registration_enabled") is True, "Registrasi tenant aktif pada environment test")
        plan_codes = {p.get("code") for p in cfgj.get("plans", [])}
        check({"starter", "business"}.issubset(plan_codes), "Paket Starter dan Business tersedia")

        default_tenant = db.tenants.find_one({"id": "tenant-pt-real"}) or {}
        check(bool(re.fullmatch(r"PRC-\d{6,}", default_tenant.get("tenant_code", ""))), "Tenant existing mendapat Kode Tenant permanen")

        legacy = requests.post(
            f"{API}/auth/register",
            json={"email": f"legacy-{run_id}@{TEST_EMAIL_DOMAIN}", "password": OWNER_PASSWORD, "name": "Legacy"},
            timeout=15,
        )
        check(legacy.status_code == 410, "Registrasi user legacy diblokir")

        payload_a = {
            "company_name": company_a,
            "pic_name": "Owner Tenant A",
            "email": email_a,
            "whatsapp": "081234567001",
            "workspace_slug": slug_a,
            "plan_code": "starter",
            "password": OWNER_PASSWORD,
            "address": "Alamat Tenant A",
            "terms_accepted": True,
        }
        payload_b = {
            "company_name": company_b,
            "pic_name": "Owner Tenant B",
            "email": email_b,
            "whatsapp": "081234567002",
            "workspace_slug": slug_b,
            "plan_code": "business",
            "password": OWNER_PASSWORD,
            "address": "Alamat Tenant B",
            "terms_accepted": True,
        }

        reg_a = register(payload_a).json()
        reg_b = register(payload_b).json()
        tenant_a = reg_a["tenant_id"]
        tenant_b = reg_b["tenant_id"]
        tenant_code_a = reg_a.get("tenant_code")
        tenant_code_b = reg_b.get("tenant_code")
        company_id_a = reg_a["company_id"]
        check(tenant_a != tenant_b, "Setiap registrasi mendapat tenant_id berbeda")
        check(
            bool(re.fullmatch(r"PRC-\d{6,}", tenant_code_a or ""))
            and bool(re.fullmatch(r"PRC-\d{6,}", tenant_code_b or ""))
            and tenant_code_a != tenant_code_b,
            "Setiap registrasi mendapat Kode Tenant permanen yang unik",
        )
        check(reg_a["workspace"] == slug_a and reg_b["workspace"] == slug_b, "Workspace slug tersimpan sesuai registrasi")
        check(reg_a["plan"]["code"] == "starter" and reg_b["plan"]["code"] == "business", "Paket tenant tersimpan sesuai pilihan")

        duplicate_slug = dict(payload_b)
        duplicate_slug["email"] = f"other-{run_id}@{TEST_EMAIL_DOMAIN}"
        duplicate_slug["company_name"] = f"PT Other {run_id}"
        rdup = register(duplicate_slug, expected=409)
        check("workspace" in rdup.text.lower(), "Duplicate workspace ditolak dengan pesan yang relevan")

        duplicate_email = dict(payload_a)
        duplicate_email["workspace_slug"] = f"another-{run_id}"
        rdup_email = register(duplicate_email, expected=409)
        check("email" in rdup_email.text.lower(), "Duplicate email Owner ditolak")

        owner_a, user_a = login(email_a, OWNER_PASSWORD)
        owner_b, user_b = login(email_b, OWNER_PASSWORD)

        raw_owner_a = db.users.find_one({"email": email_a}, {"_id": 0, "password_hash": 0}) or {}
        raw_owner_b = db.users.find_one({"email": email_b}, {"_id": 0, "password_hash": 0}) or {}
        actual_a = user_a.get("tenant_id")
        actual_b = user_b.get("tenant_id")
        raw_tenant_a = raw_owner_a.get("tenant_id")
        raw_tenant_b = raw_owner_b.get("tenant_id")
        if not (actual_a == tenant_a and actual_b == tenant_b):
            print(
                "OWNER TENANT DEBUG: "
                f"expected_a={tenant_a} raw_a={raw_tenant_a} login_a={actual_a}; "
                f"expected_b={tenant_b} raw_b={raw_tenant_b} login_b={actual_b}",
                file=sys.stderr,
            )
            raise AssertionError(
                "Login Owner membawa tenant_id yang salah; lihat OWNER TENANT DEBUG untuk membedakan bug persistensi vs login"
            )
        check(True, "Login Owner membawa tenant_id yang benar")

        ta = owner_a.get(f"{API}/tenant/current", timeout=15)
        tb = owner_b.get(f"{API}/tenant/current", timeout=15)
        check(ta.status_code == 200 and tb.status_code == 200, "Owner dapat membaca tenant/current")
        check(ta.json().get("id") == tenant_a and tb.json().get("id") == tenant_b, "tenant/current terisolasi sesuai Owner")
        check(ta.json().get("tenant_code") == tenant_code_a and tb.json().get("tenant_code") == tenant_code_b, "Owner melihat Kode Tenant miliknya sendiri")
        check(ta.json().get("plan", {}).get("code") == "starter", "Tenant A memakai paket Starter")
        check(tb.json().get("plan", {}).get("code") == "business", "Tenant B memakai paket Business")

        lifecycle_initial = owner_a.get(f"{API}/subscription/status", timeout=15)
        check(lifecycle_initial.status_code == 200, "Owner dapat membaca status lifecycle langganan")
        check(lifecycle_initial.json().get("tenant_id") == tenant_a and lifecycle_initial.json().get("status") == "trial", "Status awal registrasi terbaca sebagai trial tenant sendiri")

        iso = owner_a.get(f"{API}/tenant/isolation-status", timeout=15)
        check(iso.status_code == 200 and iso.json().get("raw_reference_count") == 0, "SaaS layer tidak menambah raw DB bypass")

        second_email = f"user2-{run_id}@{TEST_EMAIL_DOMAIN}"
        invite = owner_a.post(
            f"{API}/invitations",
            json={
                "name": "User Kedua",
                "email": second_email,
                "role": "warehouse",
                "scope": "limited",
                "divisions": [],
                "warehouses": [],
                "expires_hours": 72,
            },
            timeout=15,
        )
        check(invite.status_code == 200, "Admin tenant dapat membuat undangan user")
        invitej = invite.json()
        invite_code = invitej.get("code")
        check(bool(re.fullmatch(r"INV-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", invite_code or "")), "Kode undangan kuat dan mudah dibaca")
        check(invitej.get("tenant_id") == tenant_a and invitej.get("tenant_code") == tenant_code_a, "Undangan terikat ke tenant pembuat")

        list_a = owner_a.get(f"{API}/invitations", timeout=15)
        list_b = owner_b.get(f"{API}/invitations", timeout=15)
        check(list_a.status_code == 200 and any(x.get("code") == invite_code for x in list_a.json()), "Tenant A melihat undangannya sendiri")
        check(list_b.status_code == 200 and all(x.get("code") != invite_code for x in list_b.json()), "Tenant B tidak melihat undangan Tenant A")

        public_invite = requests.get(f"{API}/invitations/public/{invite_code}", timeout=15)
        check(public_invite.status_code == 200, "Link undangan publik dapat divalidasi")
        check(public_invite.json().get("tenant_code") == tenant_code_a, "Halaman undangan menampilkan Kode Tenant yang benar")
        check(public_invite.json().get("email_hint") != second_email, "Endpoint publik tidak membocorkan email lengkap")

        accept = requests.post(
            f"{API}/invitations/public/{invite_code}/accept",
            json={"password": INVITED_PASSWORD},
            timeout=15,
        )
        check(accept.status_code == 200, "Penerima dapat mengaktifkan akun dari undangan")
        repeat_accept = requests.post(
            f"{API}/invitations/public/{invite_code}/accept",
            json={"password": INVITED_PASSWORD},
            timeout=15,
        )
        check(repeat_accept.status_code == 410, "Kode undangan hanya dapat dipakai sekali")

        invited_session, invited_user = login(second_email, INVITED_PASSWORD)
        check(invited_user.get("tenant_id") == tenant_a, "User hasil undangan login ke tenant yang benar")
        invited_current = invited_session.get(f"{API}/tenant/current", timeout=15)
        check(invited_current.status_code == 200 and invited_current.json().get("id") == tenant_a, "Session user undangan tetap terisolasi pada Tenant A")
        raw_second = db.users.find_one({"email": second_email})
        check(raw_second and raw_second.get("tenant_id") == tenant_a, "User hasil undangan tersimpan pada tenant Owner")
        check(raw_second and raw_second.get("company_id") == company_id_a, "User hasil undangan mewarisi company tenant yang benar")

        cancel_email = f"cancel-{run_id}@{TEST_EMAIL_DOMAIN}"
        cancel_invite = owner_a.post(
            f"{API}/invitations",
            json={"name": "User Batal", "email": cancel_email, "role": "warehouse", "scope": "limited", "expires_hours": 24},
            timeout=15,
        )
        check(cancel_invite.status_code == 200, "Admin dapat membuat undangan kedua")
        cancelj = cancel_invite.json()
        cancelled = owner_a.post(f"{API}/invitations/{cancelj.get('id')}/cancel", timeout=15)
        check(cancelled.status_code == 200 and cancelled.json().get("status") == "cancelled", "Admin dapat membatalkan undangan aktif")
        cancelled_public = requests.get(f"{API}/invitations/public/{cancelj.get('code')}", timeout=15)
        check(cancelled_public.status_code == 410, "Undangan yang dibatalkan tidak dapat digunakan")

        platform, platform_user = login(PLATFORM_EMAIL, PLATFORM_PASSWORD)
        check(platform_user.get("is_platform_admin") is True, "Akun Platform Super Admin terpisah dari tenant")
        summary = platform.get(f"{API}/platform/summary", timeout=15)
        check(summary.status_code == 200, "Super Admin dapat membaca ringkasan platform")
        tenants = platform.get(f"{API}/platform/tenants", timeout=20)
        check(tenants.status_code == 200, "Super Admin dapat membaca daftar tenant")
        tenant_rows = {x.get("id"): x for x in tenants.json()}
        check(tenant_a in tenant_rows and tenant_b in tenant_rows, "Daftar Super Admin memuat Tenant A dan Tenant B")
        check(tenant_rows[tenant_a].get("tenant_code") == tenant_code_a, "Daftar Tenant menampilkan Kode Tenant permanen")

        detail = platform.get(f"{API}/platform/tenants/{tenant_a}", timeout=20)
        check(detail.status_code == 200, "Super Admin dapat membuka detail tenant")
        detailj = detail.json()
        detail_emails = {x.get("email") for x in detailj.get("users", [])}
        check({email_a, second_email}.issubset(detail_emails), "Detail Tenant memuat daftar user tenant")
        check(all("password_hash" not in x for x in detailj.get("users", [])), "Detail Tenant tidak membocorkan password hash")
        check(any(x.get("action") == "tenant.registered" for x in detailj.get("audit_logs", [])), "Detail Tenant memuat audit registrasi")
        check(any(x.get("action") == "invite.accepted" for x in detailj.get("audit_logs", [])), "Aktivitas Platform mencatat aktivasi undangan")

        platform_invites = platform.get(f"{API}/platform/tenants/{tenant_a}/invitations", timeout=15)
        check(platform_invites.status_code == 200, "Super Admin dapat memonitor undangan tenant")
        platform_codes = {x.get("code"): x.get("status") for x in platform_invites.json()}
        check(platform_codes.get(invite_code) == "used", "Platform melihat undangan yang sudah dipakai")
        check(platform_codes.get(cancelj.get("code")) == "cancelled", "Platform melihat undangan yang dibatalkan")

        # Subscription lifecycle: reminder, grace period, expiry, and tenant-scoped notification.
        near_end = datetime.now(timezone.utc) + timedelta(days=2)
        db.tenants.update_one(
            {"id": tenant_a},
            {"$set": {"subscription.status": "active", "subscription.ends_at": near_end.isoformat()},
             "$unset": {"subscription.grace_ends_at": "", "subscription.expired_at": "", "subscription.reminders_sent": "", "subscription.last_reminder_at": "", "subscription.last_reminder_type": ""}},
        )
        near_status = owner_a.get(f"{API}/subscription/status", timeout=15)
        check(near_status.status_code == 200 and near_status.json().get("status") == "active", "Langganan aktif dengan jatuh tempo dekat tetap aktif")
        check(near_status.json().get("days_remaining") in {1, 2, 3} and near_status.json().get("show_banner") is True, "Lifecycle menghitung sisa hari dan banner jatuh tempo")
        owner_notifications = owner_a.get(f"{API}/notifications", timeout=15)
        other_notifications = owner_b.get(f"{API}/notifications", timeout=15)
        check(owner_notifications.status_code == 200 and any(x.get("category") == "subscription" for x in owner_notifications.json()), "Reminder langganan masuk ke notifikasi tenant")
        check(other_notifications.status_code == 200 and all(x.get("tenant_id") != tenant_a for x in other_notifications.json()), "Reminder langganan tidak bocor ke tenant lain")
        raw_lifecycle = db.tenants.find_one({"id": tenant_a}) or {}
        sub_lifecycle = raw_lifecycle.get("subscription") or {}
        check(bool(sub_lifecycle.get("last_reminder_at")) and bool(sub_lifecycle.get("last_reminder_type")), "Database menyimpan reminder terakhir langganan")

        past_end = datetime.now(timezone.utc) - timedelta(hours=1)
        grace_end = datetime.now(timezone.utc) + timedelta(days=2)
        db.tenants.update_one(
            {"id": tenant_a},
            {"$set": {"subscription.status": "active", "subscription.ends_at": past_end.isoformat(), "subscription.grace_ends_at": grace_end.isoformat()}},
        )
        grace_status = owner_a.get(f"{API}/subscription/status", timeout=15)
        check(grace_status.status_code == 200 and grace_status.json().get("status") == "grace", "Langganan otomatis masuk masa tenggang setelah jatuh tempo")

        db.tenants.update_one(
            {"id": tenant_a},
            {"$set": {"subscription.status": "grace", "subscription.grace_ends_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}},
        )
        expired_status = owner_a.get(f"{API}/subscription/status", timeout=15)
        check(expired_status.status_code == 200 and expired_status.json().get("status") == "expired", "Langganan otomatis menjadi expired setelah masa tenggang")
        expired_raw = db.tenants.find_one({"id": tenant_a}) or {}
        check(bool((expired_raw.get("subscription") or {}).get("expired_at")), "Database menyimpan waktu expired langganan")

        subscription_overview = platform.get(f"{API}/platform/subscriptions/overview", timeout=20)
        check(subscription_overview.status_code == 200, "Platform Admin dapat membaca Subscription Notification Center")
        overview_items = {x.get("tenant_id"): x for x in subscription_overview.json().get("items", [])}
        check(overview_items.get(tenant_a, {}).get("status") == "expired", "Platform melihat status expired tenant secara terpusat")
        check(any(x.get("tenant_id") == tenant_a for x in subscription_overview.json().get("attention", [])), "Tenant expired masuk daftar perlu perhatian")

        # Expired subscription must block new invitation because the subscription is inactive.
        expired_invite = owner_a.post(
            f"{API}/invitations",
            json={"name": "User Saat Expired", "email": f"expired-{run_id}@{TEST_EMAIL_DOMAIN}", "role": "warehouse", "scope": "limited", "expires_hours": 24},
            timeout=15,
        )
        check(expired_invite.status_code == 403, "Tenant expired tidak dapat membuat undangan user")

        # Renew first, then test quota separately so the expected blocker is unambiguous.
        renewed_until = datetime.now(timezone.utc) + timedelta(days=30)
        patch = platform.patch(
            f"{API}/platform/tenants/{tenant_a}",
            json={
                "subscription_status": "active",
                "subscription_ends_at": renewed_until.isoformat(),
                "max_users": 2,
                "notes": "Limit integration test",
            },
            timeout=15,
        )
        check(patch.status_code == 200, "Super Admin dapat memperpanjang langganan dan override limit tenant")
        check(patch.json().get("limits", {}).get("max_users") == 2, "Override max_users tersimpan")
        check(any(x.get("action") == "tenant.update" for x in patch.json().get("audit_logs", [])), "Perubahan tenant tercatat di audit log")

        renewed_status = owner_a.get(f"{API}/subscription/status", timeout=15)
        check(renewed_status.status_code == 200 and renewed_status.json().get("status") == "active", "Tenant kembali aktif setelah langganan diperpanjang")

        add_third = owner_a.post(
            f"{API}/users",
            json={"email": f"user3-{run_id}@{TEST_EMAIL_DOMAIN}", "name": "User Ketiga", "role": "warehouse", "password": "UserTest!123"},
            timeout=15,
        )
        check(add_third.status_code == 409, "Backend menolak user baru saat limit tenant tercapai")

        full_invite = owner_a.post(
            f"{API}/invitations",
            json={"name": "User Keempat", "email": f"user4-{run_id}@{TEST_EMAIL_DOMAIN}", "role": "warehouse", "scope": "limited", "expires_hours": 24},
            timeout=15,
        )
        check(full_invite.status_code == 409, "Admin tidak dapat membuat undangan baru saat kuota user sudah penuh")

        raw_a = db.tenants.find_one({"id": tenant_a})
        raw_b = db.tenants.find_one({"id": tenant_b})
        check(raw_a and raw_b, "Tenant hasil registrasi benar-benar tersimpan")
        check(raw_a.get("isolation_ready") is False and raw_b.get("isolation_ready") is False, "Tenant baru tidak ditandai isolation_ready sebelum release gate")
        check(db.companies.count_documents({"tenant_id": tenant_a}) == 1, "Tenant A mendapat company awal")
        check(db.users.count_documents({"tenant_id": tenant_a, "role": "admin"}) == 1, "Tenant A mendapat Owner/Admin awal")
        check(db.settings.count_documents({"tenant_id": tenant_a}) >= 5, "Tenant A mendapat setting awal sendiri")
        check(db.settings.count_documents({"tenant_id": tenant_b}) >= 5, "Tenant B mendapat setting awal sendiri")

        print("\nRESULT: PASS - Registrasi tenant, Kode Tenant, Invite User, subscription expiry/reminder, quota, audit dan Super Admin berjalan terisolasi.")
        return 0
    finally:
        mongo.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
