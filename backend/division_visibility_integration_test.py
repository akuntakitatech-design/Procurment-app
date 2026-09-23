"""Focused integration test for procurement division visibility.

Validates that limited users only see MRO/RO/PO in assigned divisions while the Purchasing role
keeps cross-division visibility. Also validates create guards for limited users.
"""
import os
import sys
import time
import uuid

import requests


API = os.environ.get("TEST_API_URL", "http://division-test-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "division-admin@example.test")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "DivisionAdmin!123")
USER_PASSWORD = "DivisionUser!123"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def wait_api():
    base = API[:-4] if API.endswith("/api") else API
    for _ in range(75):
        try:
            if requests.get(f"{base}/docs", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError("Backend division test tidak siap dalam 75 detik")


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    check(r.status_code == 200, f"Login berhasil untuk {email}")
    token = r.json().get("token")
    check(bool(token), f"Token tersedia untuk {email}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def create_master(session, name, payload):
    r = session.post(f"{API}/master/{name}", json=payload, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Create master {name} gagal: HTTP {r.status_code} {r.text}")
    return r.json()


def create_user(session, payload):
    r = session.post(f"{API}/users", json=payload, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Create user gagal: HTTP {r.status_code} {r.text}")
    return r.json()


def create_doc(session, module, division_id, label):
    body = {
        "date": "2026-09-18",
        "division_id": division_id,
        "requester": label,
        "notes": f"Division visibility {label}",
        "lines": [],
    }
    if module == "po":
        body.update({"supplier_id": "", "currency": "IDR", "supplier_notes": "", "internal_notes": ""})
    r = session.post(f"{API}/{module}", json=body, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Create {module.upper()} gagal: HTTP {r.status_code} {r.text}")
    return r.json()


def ids(rows):
    return {x.get("id") for x in rows or []}


def main():
    wait_api()
    run_id = uuid.uuid4().hex[:8]
    admin = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    div_a = create_master(admin, "divisions", {"code": f"A{run_id}", "name": f"Division A {run_id}"})
    div_b = create_master(admin, "divisions", {"code": f"B{run_id}", "name": f"Division B {run_id}"})
    check(div_a.get("id") != div_b.get("id"), "Dua divisi test berhasil dibuat")

    limited_email = f"limited-{run_id}@example.test"
    purchasing_email = f"purchasing-{run_id}@example.test"
    create_user(admin, {
        "email": limited_email,
        "password": USER_PASSWORD,
        "name": "Limited Division User",
        "role": "warehouse",
        "scope": "limited",
        "divisions": [div_a["id"]],
        "warehouses": [],
        "permissions": ["view", "create", "edit", "delete", "submit"],
        "is_active": True,
    })
    create_user(admin, {
        "email": purchasing_email,
        "password": USER_PASSWORD,
        "name": "Purchasing Cross Division",
        "role": "purchasing",
        "scope": "limited",
        "divisions": [div_a["id"]],
        "warehouses": [],
        "permissions": ["view", "create", "edit", "delete", "submit", "view_purchase_price"],
        "is_active": True,
    })

    created = {}
    for module in ("mro", "ro", "po"):
        created[(module, "a")] = create_doc(admin, module, div_a["id"], f"{module.upper()} A")
        created[(module, "b")] = create_doc(admin, module, div_b["id"], f"{module.upper()} B")
    check(True, "Dokumen MRO/RO/PO dua divisi berhasil dibuat")

    limited = login(limited_email, USER_PASSWORD)
    for module in ("mro", "ro", "po"):
        listing = limited.get(f"{API}/{module}", timeout=15)
        check(listing.status_code == 200, f"Limited user dapat membuka daftar {module.upper()}")
        visible = ids(listing.json())
        check(created[(module, "a")]["id"] in visible, f"{module.upper()} divisi sendiri terlihat")
        check(created[(module, "b")]["id"] not in visible, f"{module.upper()} divisi lain disembunyikan")

        own = limited.get(f"{API}/{module}/{created[(module, 'a')]['id']}", timeout=15)
        foreign = limited.get(f"{API}/{module}/{created[(module, 'b')]['id']}", timeout=15)
        check(own.status_code == 200, f"Detail {module.upper()} divisi sendiri dapat dibuka")
        check(foreign.status_code == 403, f"Detail {module.upper()} divisi lain ditolak backend")

        forbidden_body = {
            "date": "2026-09-18",
            "division_id": div_b["id"],
            "requester": "Forbidden",
            "lines": [],
        }
        if module == "po":
            forbidden_body.update({"supplier_id": "", "currency": "IDR"})
        forbidden = limited.post(f"{API}/{module}", json=forbidden_body, timeout=15)
        check(forbidden.status_code == 403, f"Limited user tidak dapat membuat {module.upper()} untuk divisi lain")

    purchasing = login(purchasing_email, USER_PASSWORD)
    for module in ("mro", "ro", "po"):
        listing = purchasing.get(f"{API}/{module}", timeout=15)
        check(listing.status_code == 200, f"Purchasing dapat membuka daftar {module.upper()}")
        visible = ids(listing.json())
        check(
            created[(module, "a")]["id"] in visible and created[(module, "b")]["id"] in visible,
            f"Purchasing dapat melihat {module.upper()} lintas divisi",
        )
        foreign = purchasing.get(f"{API}/{module}/{created[(module, 'b')]['id']}", timeout=15)
        check(foreign.status_code == 200, f"Purchasing dapat membuka detail {module.upper()} divisi lain")

    print("\nRESULT: PASS - Visibility MRO/RO/PO terisolasi per divisi dan Purchasing tetap lintas divisi.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
