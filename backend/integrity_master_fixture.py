"""Helper test integrasi: lengkapi field wajib Master Data.

Sejak aturan wajib isi Master Data (Barang: Kategori, Satuan Dasar, Divisi;
Supplier: Kategori Supplier; Kategori Barang & Satuan: kode manual), payload
fixture lama yang minimal tidak lagi diterima API. Helper ini mengisi field
wajib yang belum diisi test dengan master referensi fixture per sesi/tenant,
tanpa mengubah field yang sudah diisi test secara eksplisit.
"""
import uuid

_CACHE = {}


def _key(session):
    auth = session.headers.get("Authorization") or ""
    cookies = "|".join(sorted(f"{c.name}={c.value}" for c in session.cookies))
    return (id(session), auth, cookies)


def _post(session, api, name, payload):
    r = session.post(f"{api}/master/{name}", json=payload, timeout=20)
    if r.status_code != 200:
        raise AssertionError(f"Fixture master {name} gagal: HTTP {r.status_code} {r.text}")
    return r.json()


def _refs(session, api):
    key = _key(session)
    if key not in _CACHE:
        tag = uuid.uuid4().hex[:8].upper()
        cat = _post(session, api, "item_categories", {"code": f"FXK-{tag}", "name": f"Fixture Kategori {tag}", "is_active": True})
        uom = _post(session, api, "uoms", {"code": f"FXS-{tag}", "name": f"Fixture Satuan {tag}", "is_active": True})
        div = _post(session, api, "divisions", {"code": f"FXD-{tag}", "name": f"Fixture Divisi {tag}", "is_active": True})
        scat = _post(session, api, "supplier_categories", {"code": f"FXP-{tag}", "name": f"Fixture Kategori Supplier {tag}", "is_active": True})
        _CACHE[key] = {"category_id": cat["id"], "base_uom_id": uom["id"], "division_id": div["id"], "supplier_category_id": scat["id"]}
    return _CACHE[key]


def fill_required(session, api, name, payload):
    body = dict(payload or {})
    if name in ("item_categories", "uoms") and not str(body.get("code") or "").strip():
        body["code"] = f"{'KAT' if name == 'item_categories' else 'SAT'}-{uuid.uuid4().hex[:8].upper()}"
    if name == "items":
        refs = _refs(session, api)
        for k in ("category_id", "division_id", "base_uom_id"):
            if not body.get(k):
                body[k] = refs[k]
    if name == "suppliers" and not body.get("supplier_category_id"):
        body["supplier_category_id"] = _refs(session, api)["supplier_category_id"]
    return body
