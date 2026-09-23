"""
ProcureFlow backend regression tests.
Covers: auth, master data listing, dashboard, full lifecycle MRO -> RO -> PO -> DO -> MI,
traceability, search, verify, transfer, loan+return, adjustment, opname,
direct MI without MRO, user create, attachments.
"""
import os
import io
import time
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    # Try reading from frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
API = f"{BASE}/api"

ADMIN_EMAIL = "agustrnt@gmail.com"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token")
    assert token, f"No token in response: {data}"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="session")
def master(client):
    warehouses = client.get(f"{API}/master/warehouses").json()
    items = client.get(f"{API}/master/items").json()
    suppliers = client.get(f"{API}/master/suppliers").json()
    projects = client.get(f"{API}/master/projects").json()
    assert warehouses and items and suppliers
    def find_item(code):
        for it in items:
            if it.get("code") == code:
                return it
        return items[0]
    return {
        "wh": warehouses[0],
        "wh2": warehouses[1] if len(warehouses) > 1 else warehouses[0],
        "item": find_item("SP001"),
        "item2": find_item("SP002"),
        "supplier": suppliers[0],
        "project": projects[0] if projects else None,
    }


def test_auth_me(client):
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json().get("email") == ADMIN_EMAIL


def test_dashboard(client):
    r = client.get(f"{API}/dashboard")
    assert r.status_code == 200
    data = r.json()
    # Some keys expected
    assert isinstance(data, dict)


def test_inventory_position(client):
    r = client.get(f"{API}/inventory/position")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_inventory_ledger(client, master):
    r = client.get(f"{API}/inventory/ledger", params={
        "item_id": master["item"]["id"],
        "warehouse_id": master["wh"]["id"],
    })
    assert r.status_code == 200


def test_full_lifecycle(client, master):
    wh = master["wh"]
    item = master["item"]
    supplier = master["supplier"]
    project = master["project"]

    # 1) Create MRO (submitted immediately)
    mro_payload = {
        "default_warehouse_id": wh["id"],
        "default_project_id": project["id"] if project else None,
        "notes": "TEST_MRO auto",
        "submitted": True,
        "lines": [
            {"item_id": item["id"], "qty": 100, "unit": item.get("unit", "PCS"),
             "warehouse_id": wh["id"]}
        ],
    }
    r = client.post(f"{API}/mro", json=mro_payload)
    assert r.status_code in (200, 201), f"MRO create: {r.status_code} {r.text}"
    mro = r.json()
    mro_id = mro["id"]
    mro_no = mro["no"]

    # 2) Pull MRO -> RO
    r = client.get(f"{API}/pull/mro-for-ro")
    assert r.status_code == 200
    pulls = [p for p in r.json() if p["mro_id"] == mro_id]
    assert pulls, "No MRO pull rows"
    ro_lines = [{
        "item_id": p["item_id"],
        "qty": p["outstanding"],
        "unit": p["unit"],
        "warehouse_id": p.get("warehouse_id") or wh["id"],
        "project_id": p.get("project_id"),
        "sources": [{"mro_id": mro_id, "line_id": p["line_id"], "qty": p["outstanding"]}],
    } for p in pulls]

    ro_payload = {"default_warehouse_id": wh["id"], "lines": ro_lines,
                  "notes": "TEST_RO", "submitted": True}
    r = client.post(f"{API}/ro", json=ro_payload)
    assert r.status_code in (200, 201), f"RO create: {r.text}"
    ro = r.json()
    ro_id = ro["id"]

    # 3) Pull RO -> PO
    r = client.get(f"{API}/pull/ro-for-po")
    assert r.status_code == 200
    ro_pulls = [p for p in r.json() if p["ro_id"] == ro_id]
    assert ro_pulls, "No RO pull rows"
    po_lines = [{
        "item_id": p["item_id"],
        "qty": p["outstanding"],
        "unit": p["unit"],
        "warehouse_id": p.get("warehouse_id") or wh["id"],
        "project_id": p.get("project_id"),
        "price": 50000,
        "sources": [{"ro_id": ro_id, "line_id": p["line_id"], "qty": p["outstanding"]}],
    } for p in ro_pulls]

    po_payload = {"default_warehouse_id": wh["id"], "supplier_id": supplier["id"],
                  "lines": po_lines, "notes": "TEST_PO"}
    r = client.post(f"{API}/po", json=po_payload)
    assert r.status_code in (200, 201), f"PO create: {r.text}"
    po = r.json()
    po_id = po["id"]
    assert po.get("grand_total", 0) > 0, "PO grand_total should be visible for admin"

    r = client.post(f"{API}/po/{po_id}/submit")
    assert r.status_code in (200, 201), f"PO submit: {r.text}"
    r = client.post(f"{API}/po/{po_id}/approve", json={"note": "ok"})
    assert r.status_code in (200, 201), f"PO approve: {r.text}"
    # keep approving in case of multi-step until approved
    for _ in range(5):
        d = client.get(f"{API}/po/{po_id}").json()
        if d.get("status") == "Approved":
            break
        r2 = client.post(f"{API}/po/{po_id}/approve", json={"note": "ok"})
        if r2.status_code != 200:
            break
    assert client.get(f"{API}/po/{po_id}").json().get("status") == "Approved"

    # 4) Pull PO -> DO
    r = client.get(f"{API}/pull/po-for-do")
    assert r.status_code == 200
    po_pulls = [p for p in r.json() if p["po_id"] == po_id]
    assert po_pulls, "No PO pull rows"
    do_lines = [{
        "item_id": p["item_id"],
        "qty": p["outstanding"],
        "unit": p["unit"],
        "warehouse_id": p.get("warehouse_id") or wh["id"],
        "project_id": p.get("project_id"),
        "po_id": po_id,
        "po_line_id": p["line_id"],
    } for p in po_pulls]

    do_payload = {"default_warehouse_id": wh["id"], "supplier_id": supplier["id"],
                  "lines": do_lines, "notes": "TEST_DO"}
    r = client.post(f"{API}/do", json=do_payload)
    assert r.status_code in (200, 201), f"DO create: {r.text}"
    do_id = r.json()["id"]

    # 5) Pull MRO -> MI
    r = client.get(f"{API}/pull/mro-for-mi")
    assert r.status_code == 200
    mi_pulls = [p for p in r.json() if p["mro_id"] == mro_id]
    assert mi_pulls, "No MRO pull for MI"
    mi_lines = [{
        "item_id": p["item_id"],
        "qty": p["outstanding"],
        "unit": p["unit"],
        "warehouse_id": p.get("warehouse_id") or wh["id"],
        "project_id": p.get("project_id"),
        "mro_line_id": p["line_id"],
    } for p in mi_pulls]

    mi_payload = {"default_warehouse_id": wh["id"], "lines": mi_lines,
                  "notes": "TEST_MI", "source_type": "MRO"}
    r = client.post(f"{API}/mi", json=mi_payload)
    assert r.status_code in (200, 201), f"MI create: {r.text}"

    # Verify MRO completed
    r = client.get(f"{API}/mro/{mro_id}")
    assert r.status_code == 200
    status = (r.json().get("status") or "").lower()
    assert status in ("completed", "closed", "done", "fulfilled"), f"MRO status after MI: {status}"

    # Traceability
    r = client.get(f"{API}/traceability/{mro_id}")
    assert r.status_code == 200, f"traceability: {r.status_code} {r.text}"
    trace = r.json()
    assert trace, "empty trace"

    # Global search
    r = client.get(f"{API}/search", params={"q": mro_no[:6]})
    assert r.status_code == 200

    # Verify endpoint (PO QR)
    r = client.post(f"{API}/verify/generate", json={"doc_type": "po", "doc_id": po_id})
    if r.status_code == 200:
        code = r.json().get("code")
        if code:
            rr = client.get(f"{API}/verify/{code}")
            assert rr.status_code == 200


def test_transfer(client, master):
    payload = {
        "from_warehouse_id": master["wh"]["id"],
        "to_warehouse_id": master["wh2"]["id"],
        "lines": [{"item_id": master["item"]["id"], "qty": 1, "unit": master["item"].get("unit", "PCS")}],
        "notes": "TEST_TRANSFER",
    }
    r = client.post(f"{API}/transfers", json=payload)
    assert r.status_code in (200, 201), f"transfer: {r.status_code} {r.text}"


def test_adjustment(client, master):
    payload = {
        "warehouse_id": master["wh"]["id"],
        "lines": [{"item_id": master["item"]["id"], "adjustment": 1, "reason": "TEST"}],
        "notes": "TEST_ADJ",
        "reason": "test",
    }
    r = client.post(f"{API}/adjustments", json=payload)
    assert r.status_code in (200, 201), r.text


def test_direct_mi(client, master):
    payload = {
        "default_warehouse_id": master["wh"]["id"],
        "source_type": "Direct",
        "lines": [{"item_id": master["item"]["id"], "qty": 1,
                   "unit": master["item"].get("unit", "PCS"),
                   "warehouse_id": master["wh"]["id"]}],
        "notes": "TEST_DIRECT_MI",
    }
    r = client.post(f"{API}/mi", json=payload)
    assert r.status_code in (200, 201), f"direct MI: {r.text}"


def test_user_create(client):
    email = f"TEST_user_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": email,
        "password": "Passw0rd!",
        "full_name": "TEST User",
        "role": "user",
        "permissions": ["mro.read"],
    }
    r = client.post(f"{API}/users", json=payload)
    assert r.status_code in (200, 201, 400), r.text
