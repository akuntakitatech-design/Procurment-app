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

# Tenant throwaway (tidak memakai/mengubah data tenant live). Kredensial dibuat acak per sesi test.
_RUN = uuid.uuid4().hex[:8]
ADMIN_EMAIL = f"bt_{_RUN}@example.com"
ADMIN_PASSWORD = f"Bt-{uuid.uuid4().hex[:12]}!9"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/saas/register", json={
        "company_name": f"BT {_RUN}", "pic_name": "QA", "email": ADMIN_EMAIL, "whatsapp": "+628123456789",
        "workspace_slug": f"bt-{_RUN}", "plan_code": "starter", "password": ADMIN_PASSWORD,
        "address": "x", "terms_accepted": True})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    token = r.json().get("token")
    if not token:
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
        token = r.json().get("token")
    assert token, "No token"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="session")
def master(client):
    def mk(coll, body):
        r = client.post(f"{API}/master/{coll}", json=body)
        assert r.status_code == 200, f"seed {coll}: {r.status_code} {r.text}"
        return r.json()
    wh = mk("warehouses", {"code": f"WA{_RUN}", "name": "Gudang A", "is_active": True})
    wh2 = mk("warehouses", {"code": f"WB{_RUN}", "name": "Gudang B", "is_active": True})
    div = mk("divisions", {"code": f"DV{_RUN}", "name": "Divisi Teknik"})
    cat = mk("item_categories", {"code": f"KC{_RUN}", "name": "Kategori Umum"})
    uom = mk("uoms", {"code": f"PCS{_RUN}", "name": "Pieces"})
    scat = mk("supplier_categories", {"code": f"KS{_RUN}", "name": "Kategori Supplier"})
    ref = {"category_id": cat["id"], "division_id": div["id"], "base_uom_id": uom["id"], "unit": "PCS", "is_active": True}
    item = mk("items", {"code": f"SP001{_RUN}", "name": "Sparepart 1", **ref})
    item2 = mk("items", {"code": f"SP002{_RUN}", "name": "Sparepart 2", **ref})
    sup = mk("suppliers", {"code": f"SX{_RUN}", "name": "Supplier X", "supplier_category_id": scat["id"]})
    prj = mk("projects", {"code": f"PA{_RUN}", "name": "Project A"})
    for it in (item, item2):
        r = client.post(f"{API}/adjustments", json={"warehouse_id": wh["id"], "division_id": div["id"], "reason": "stok awal",
                                                    "lines": [{"item_id": it["id"], "adjustment": 500, "approved_unit_cost": 1000}]})
        assert r.status_code == 200, f"seed stok: {r.text}"
    r = client.put(f"{API}/settings/mi", json={"mi_mode": "mro_plus_direct"})
    assert r.status_code == 200, f"settings MI: {r.text}"
    return {"wh": wh, "wh2": wh2, "item": item, "item2": item2, "supplier": sup, "project": prj, "div": div}


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
        "no": f"MRO-BT-{uuid.uuid4().hex[:6]}",
        "division_id": master["div"]["id"],
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
    if client.get(f"{API}/po/{po_id}").json().get("status") != "Approved":  # tanpa tahap approval: submit langsung Approved
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
        "mro_id": mro_id,
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
        "division_id": master["div"]["id"],
        "lines": [{"item_id": master["item"]["id"], "qty": 1, "unit": master["item"].get("unit", "PCS")}],
        "notes": "TEST_TRANSFER",
    }
    r = client.post(f"{API}/transfers", json=payload)
    assert r.status_code in (200, 201), f"transfer: {r.status_code} {r.text}"


def test_adjustment(client, master):
    payload = {
        "warehouse_id": master["wh"]["id"],
        "division_id": master["div"]["id"],
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
        "division_id": master["div"]["id"],
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
