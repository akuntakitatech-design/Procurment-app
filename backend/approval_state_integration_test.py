"""Disposable integration test for MRO/RO/PO approval lifecycle state."""
import os
import sys
import time
import uuid

import requests
from pymongo import MongoClient


API = os.environ.get("TEST_API_URL", "http://approval-test-api:8000/api").rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "approval-admin@example.test")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ApprovalAdmin!123")
MONGO_URL = os.environ.get("TEST_MONGO_URL", "mongodb://approval-test-mongodb:27017")
DB_NAME = os.environ.get("TEST_DB_NAME", "procurement_approval_state_test")


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
    check(r.status_code == 200, f"Login {email} berhasil")
    token = r.json().get("token")
    check(bool(token), f"Token {email} tersedia")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def create_master(session, name, payload):
    r = session.post(f"{API}/master/{name}", json=payload, timeout=15)
    if r.status_code != 200:
        raise AssertionError(f"Gagal membuat master {name}: HTTP {r.status_code} {r.text}")
    return r.json()


def create_user(admin, email, password, division_id):
    r = admin.post(
        f"{API}/users",
        json={
            "email": email,
            "password": password,
            "name": email.split("@")[0],
            "role": "manager",
            "scope": "limited",
            "divisions": [division_id],
            "warehouses": [],
        },
        timeout=15,
    )
    check(r.status_code == 200, f"User approver {email} dibuat")
    return r.json()


def configure_approval(email1, email2):
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
    db = client[DB_NAME]
    for _ in range(30):
        cfg = db.settings.find_one({"id": "approval_modules"})
        if cfg:
            break
        time.sleep(1)
    else:
        raise AssertionError("Setting approval_modules belum tersedia")

    modules = {
        "mro": {
            "enabled": True,
            "levels": [
                {"level": 1, "email": email1},
                {"level": 2, "email": email2},
            ],
        },
        "ro": {
            "enabled": True,
            "levels": [{"level": 1, "email": email1}],
        },
        "po": {
            "enabled": True,
            "levels": [
                {"level": 1, "email": email1},
                {"level": 2, "email": email2},
            ],
        },
    }
    db.settings.update_one({"_id": cfg["_id"]}, {"$set": {"modules": modules}})
    client.close()


def task_for(session, document_id, status=None):
    r = session.get(f"{API}/approvals/inbox", timeout=15)
    check(r.status_code == 200, "Inbox approval dapat dibaca")
    for row in r.json():
        if row.get("document_id") == document_id and (status is None or row.get("status") == status):
            return row
    return None


def main():
    wait_api()
    run = uuid.uuid4().hex[:8]
    admin = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    division = create_master(admin, "divisions", {"code": f"AP{run}", "name": f"Approval Divisi {run}"})
    warehouse = create_master(admin, "warehouses", {"code": f"AW{run}", "name": f"Approval Gudang {run}", "division_id": division["id"]})
    supplier = create_master(admin, "suppliers", {"code": f"AS{run}", "name": f"Approval Supplier {run}"})
    item = create_master(admin, "items", {"code": f"AI{run}", "name": f"Approval Item {run}", "unit": "pcs", "division_id": division["id"]})

    email1 = f"approver1-{run}@example.test"
    email2 = f"approver2-{run}@example.test"
    password1 = "ApproverOne!123"
    password2 = "ApproverTwo!123"
    create_user(admin, email1, password1, division["id"])
    create_user(admin, email2, password2, division["id"])
    approver1 = login(email1, password1)
    approver2 = login(email2, password2)
    configure_approval(email1, email2)
    check(True, "Approval MRO/RO/PO dikonfigurasi untuk pengujian")

    # MRO: two-level sequential approval, wrong assignee blocked, approved cannot re-submit.
    mro = admin.post(
        f"{API}/mro",
        json={
            "date": "2026-09-18",
            "division_id": division["id"],
            "default_warehouse_id": warehouse["id"],
            "requester": "Approval Tester",
            "lines": [{"item_id": item["id"], "qty": 5, "unit": "pcs", "warehouse_id": warehouse["id"]}],
        },
        timeout=15,
    )
    check(mro.status_code == 200, "MRO approval test dibuat")
    mro_id = mro.json()["id"]
    mro_submit = admin.post(f"{API}/mro/{mro_id}/submit", timeout=15)
    check(mro_submit.status_code == 200 and mro_submit.json().get("status") == "Waiting Approval", "MRO masuk Waiting Approval")
    check(admin.post(f"{API}/mro/{mro_id}/submit", timeout=15).status_code == 409, "MRO Waiting Approval tidak dapat disubmit ulang")

    mro_task1 = task_for(approver1, mro_id, "Pending")
    check(mro_task1 is not None, "Level 1 MRO muncul di approver pertama")
    wrong = approver2.post(f"{API}/approvals/{mro_task1['id']}/approve", json={"note": "tidak berhak"}, timeout=15)
    check(wrong.status_code == 403, "Approver level lain tidak dapat mengambil approval Level 1")
    first = approver1.post(f"{API}/approvals/{mro_task1['id']}/approve", json={"note": "L1 OK"}, timeout=15)
    check(first.status_code == 200 and first.json().get("status") == "Waiting Approval", "MRO tetap Waiting Approval setelah Level 1")
    mro_task2 = task_for(approver2, mro_id, "Pending")
    check(mro_task2 is not None, "Level 2 MRO aktif setelah Level 1")
    second = approver2.post(f"{API}/approvals/{mro_task2['id']}/approve", json={"note": "L2 OK"}, timeout=15)
    check(second.status_code == 200 and second.json().get("approval_status") == "Approved", "MRO Approved setelah seluruh level selesai")
    check(admin.post(f"{API}/mro/{mro_id}/submit", timeout=15).status_code == 409, "MRO Approved tidak dapat disubmit ulang")

    # RO: rejected must be edited first. After revision it can be submitted again; cancelling
    # while waiting must close the task and stale approval must be unusable.
    ro = admin.post(
        f"{API}/ro",
        json={
            "date": "2026-09-18",
            "division_id": division["id"],
            "default_warehouse_id": warehouse["id"],
            "requester": "Approval Tester",
            "lines": [{"item_id": item["id"], "qty": 2, "unit": "pcs", "warehouse_id": warehouse["id"]}],
        },
        timeout=15,
    )
    check(ro.status_code == 200, "RO approval test dibuat")
    ro_id = ro.json()["id"]
    check(admin.post(f"{API}/ro/{ro_id}/submit", timeout=15).status_code == 200, "RO disubmit ke approval")
    ro_task = task_for(approver1, ro_id, "Pending")
    reject = approver1.post(f"{API}/approvals/{ro_task['id']}/reject", json={"reason": "Perlu revisi"}, timeout=15)
    check(reject.status_code == 200 and reject.json().get("status") == "Rejected", "RO berubah Rejected")
    check(admin.post(f"{API}/ro/{ro_id}/submit", timeout=15).status_code == 409, "RO Rejected wajib direvisi sebelum submit ulang")

    ro_detail = admin.get(f"{API}/ro/{ro_id}", timeout=15).json()
    revise = admin.put(
        f"{API}/transactions/ro/{ro_id}",
        json={
            "date": ro_detail.get("date") or "2026-09-18",
            "division_id": division["id"],
            "default_warehouse_id": warehouse["id"],
            "requester": "Approval Tester - Revisi",
            "notes": "Sudah direvisi",
            "lines": [{"item_id": item["id"], "qty": 2, "unit": "pcs", "warehouse_id": warehouse["id"]}],
        },
        timeout=15,
    )
    check(revise.status_code == 200 and revise.json().get("approval_reset") is True, "Edit RO me-reset approval ke Draft")
    resubmit = admin.post(f"{API}/ro/{ro_id}/submit", timeout=15)
    check(resubmit.status_code == 200 and resubmit.json().get("status") == "Waiting Approval", "RO hasil revisi dapat disubmit ulang")
    ro_task_after = task_for(approver1, ro_id, "Pending")
    check(ro_task_after is not None, "Approval baru dibuat setelah revisi RO")
    cancelled = admin.post(f"{API}/ro/{ro_id}/cancel", json={"reason": "Batalkan saat approval"}, timeout=15)
    check(cancelled.status_code == 200, "RO Waiting Approval dapat dibatalkan")
    stale = approver1.post(f"{API}/approvals/{ro_task_after['id']}/approve", json={"note": "stale"}, timeout=15)
    check(stale.status_code == 409, "Approval stale tidak dapat memproses RO yang sudah dibatalkan")

    # PO: two-level approval and final Approved state.
    po = admin.post(
        f"{API}/po",
        json={
            "date": "2026-09-18",
            "division_id": division["id"],
            "supplier_id": supplier["id"],
            "default_warehouse_id": warehouse["id"],
            "currency": "IDR",
            "lines": [{"item_id": item["id"], "qty": 3, "unit": "pcs", "warehouse_id": warehouse["id"], "price": 1000, "discount": 0, "tax": 0}],
        },
        timeout=15,
    )
    check(po.status_code == 200 and po.json().get("status") == "Draft", "PO dibuat sebagai Draft")
    po_id = po.json()["id"]
    po_submit = admin.post(f"{API}/po/{po_id}/submit", timeout=15)
    check(po_submit.status_code == 200 and po_submit.json().get("status") == "Waiting Approval", "PO masuk Waiting Approval")
    check(admin.post(f"{API}/po/{po_id}/submit", timeout=15).status_code == 409, "PO Waiting Approval tidak dapat disubmit ulang")
    po_task1 = task_for(approver1, po_id, "Pending")
    check(po_task1 is not None, "PO Level 1 tersedia")
    po_l1 = approver1.post(f"{API}/approvals/{po_task1['id']}/approve", json={"note": "PO L1 OK"}, timeout=15)
    check(po_l1.status_code == 200 and po_l1.json().get("status") == "Waiting Approval", "PO menunggu Level 2 setelah Level 1")
    po_task2 = task_for(approver2, po_id, "Pending")
    check(po_task2 is not None, "PO Level 2 tersedia")
    po_l2 = approver2.post(f"{API}/approvals/{po_task2['id']}/approve", json={"note": "PO L2 OK"}, timeout=15)
    check(po_l2.status_code == 200 and po_l2.json().get("status") == "Approved", "PO menjadi Approved setelah Level 2")
    check(admin.post(f"{API}/po/{po_id}/submit", timeout=15).status_code == 409, "PO Approved tidak dapat disubmit ulang")

    print("\nRESULT: PASS - approval sequential, assignee, reject/revise, cancel stale-task, dan status MRO/RO/PO konsisten.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\nRESULT: FAIL - {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
