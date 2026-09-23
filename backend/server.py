from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks, Query
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')

from starlette.middleware.cors import CORSMiddleware
import os, uuid, logging
from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel

import auth as A
import storage as S

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("procureflow")

# ---------------------------------------------------------------------------
# Database: MariaDB melalui lapisan kompatibel-Motor (lihat mariadb_motor.py).
# Env DATABASE_URL=mysql://user:pass@host:3306/db . Untuk kompatibilitas mundur,
# jika DATABASE_URL kosong dan MONGO_URL terisi, MongoDB tetap bisa dipakai
# (berguna untuk pembandingan/validasi migrasi).
# ---------------------------------------------------------------------------
if os.environ.get("DATABASE_URL", "").strip():
    import mariadb_motor
    client = mariadb_motor.MariaClient(os.environ["DATABASE_URL"],
                                       auto_schema=os.environ.get("DB_AUTO_SCHEMA", "true").lower() not in ("0", "false", "no"),
                                       pool_size=int(os.environ.get("DATABASE_POOL_SIZE", "10")))
    db = client[os.environ.get("DB_NAME", "default")]
    DB_BACKEND = "mariadb"
else:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    DB_BACKEND = "mongodb"

app = FastAPI(title="ProcureFlow API")
api = APIRouter(prefix="/api")

# ---------------- helpers ----------------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def gid():
    return str(uuid.uuid4())

def clean(doc):
    if doc:
        doc.pop("_id", None)
    return doc

async def current_user(request: Request):
    return await A.get_current_user(request, db)

def is_global(user):
    return user.get("role") in ("admin", "director", "purchasing") or user.get("scope") == "global" or "view_all_division" in user.get("permissions", [])

def has_perm(user, perm):
    if user.get("role") == "admin":
        return True
    return perm in user.get("permissions", [])

def require(user, perm):
    if not has_perm(user, perm):
        raise HTTPException(status_code=403, detail=f"Tidak punya izin: {perm}")

async def audit(user, action, entity, entity_id, doc_no=None, before=None, after=None, reason=None):
    await db.audit_logs.insert_one({
        "id": gid(), "user": user.get("email"), "user_name": user.get("name"),
        "action": action, "entity": entity, "entity_id": entity_id, "doc_no": doc_no,
        "before": before, "after": after, "reason": reason, "at": now_iso(),
    })

async def notify(title, message, category, scope_division=None):
    await db.notifications.insert_one({
        "id": gid(), "title": title, "message": message, "category": category,
        "division": scope_division, "read": False, "at": now_iso(),
    })

async def next_number(doc_type):
    ym = datetime.now(timezone.utc)
    key = f"{doc_type}-{ym.year}-{ym.month:02d}"
    cfg = await db.settings.find_one({"id": "numbering"}) or {}
    fmt = (cfg.get("formats", {}) or {}).get(doc_type, f"{doc_type}/{{year}}/{{month}}/{{seq}}")
    res = await db.counters.find_one_and_update(
        {"id": key}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    seq = res["seq"] if res else 1
    return (fmt.replace("{year}", str(ym.year)).replace("{month}", f"{ym.month:02d}")
            .replace("{seq}", f"{seq:05d}").replace("{type}", doc_type))

# ---- allocation helpers ----
async def alloc_out(source_line_id, target_type):
    cur = db.allocations.aggregate([
        {"$match": {"source_line_id": source_line_id, "target_type": target_type}},
        {"$group": {"_id": None, "q": {"$sum": "$qty"}}}])
    r = await cur.to_list(1)
    return r[0]["q"] if r else 0

async def alloc_in(target_line_id, source_type):
    cur = db.allocations.aggregate([
        {"$match": {"target_line_id": target_line_id, "source_type": source_type}},
        {"$group": {"_id": None, "q": {"$sum": "$qty"}}}])
    r = await cur.to_list(1)
    return r[0]["q"] if r else 0

async def create_alloc(source_type, source_line_id, source_doc_id, target_type, target_line_id, target_doc_id, qty, item_id):
    await db.allocations.insert_one({
        "id": gid(), "source_type": source_type, "source_line_id": source_line_id,
        "source_doc_id": source_doc_id, "target_type": target_type,
        "target_line_id": target_line_id, "target_doc_id": target_doc_id,
        "qty": qty, "item_id": item_id, "at": now_iso()})

# ---- stock ledger ----
async def stock_balance(item_id, warehouse_id):
    iw = await db.item_warehouse.find_one({"item_id": item_id, "warehouse_id": warehouse_id})
    return (iw or {}).get("current_stock", 0)

async def post_ledger(doc_type, doc_no, doc_id, item_id, warehouse_id, qty_in, qty_out,
                      project_id=None, unit_id=None, division_id=None, user=None):
    bal = await stock_balance(item_id, warehouse_id)
    running = bal + qty_in - qty_out
    await db.stock_ledger.insert_one({
        "id": gid(), "doc_type": doc_type, "doc_no": doc_no, "doc_id": doc_id,
        "item_id": item_id, "warehouse_id": warehouse_id, "qty_in": qty_in, "qty_out": qty_out,
        "running_balance": running, "project_id": project_id, "unit_id": unit_id,
        "division_id": division_id, "user": (user or {}).get("email") if user else None,
        "at": now_iso()})
    await db.item_warehouse.update_one(
        {"item_id": item_id, "warehouse_id": warehouse_id},
        {"$set": {"item_id": item_id, "warehouse_id": warehouse_id, "current_stock": running}},
        upsert=True)
    return running

# =================================================================
# AUTH
# =================================================================
class RegisterIn(BaseModel):
    email: str
    password: str
    name: str

class LoginIn(BaseModel):
    email: str
    password: str

@api.post("/auth/register")
async def register(body: RegisterIn, request: Request, response: Response):
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    uid = gid()
    doc = {"id": uid, "email": email, "password_hash": A.hash_password(body.password),
           "name": body.name, "role": "warehouse", "divisions": [], "warehouses": [],
           "permissions": ["view", "create"], "scope": "limited", "is_active": True,
           "token_version": 0, "signature_url": None, "created_at": now_iso()}
    await db.users.insert_one(doc)
    A.set_auth_cookies(response, A.create_access_token(uid, email, 0), A.create_refresh_token(uid, 0), request)
    clean(doc); doc.pop("password_hash", None)
    doc["token"] = A.create_access_token(uid, email, 0)
    return doc

@api.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    email = body.email.lower().strip()
    ip = request.client.host if request.client else "?"
    ident = f"{ip}:{email}"
    la = await db.login_attempts.find_one({"identifier": ident})
    if la and la.get("count", 0) >= 5:
        last = datetime.fromisoformat(la["last"])
        if (datetime.now(timezone.utc) - last).total_seconds() < 900:
            raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi 15 menit.")
    user = await db.users.find_one({"email": email})
    if not user or not A.verify_password(body.password, user.get("password_hash", "")):
        await db.login_attempts.update_one({"identifier": ident},
            {"$set": {"identifier": ident, "email": email, "last": now_iso()}, "$inc": {"count": 1}}, upsert=True)
        raise HTTPException(status_code=401, detail="Email atau password salah")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Akun nonaktif")
    await db.login_attempts.delete_many({"identifier": ident})
    tv = user.get("token_version", 0)
    A.set_auth_cookies(response, A.create_access_token(user["id"], email, tv), A.create_refresh_token(user["id"], tv), request)
    clean(user); user.pop("password_hash", None)
    user["token"] = A.create_access_token(user["id"], email, tv)
    return user

@api.post("/auth/logout")
async def logout(request: Request, response: Response):
    A.clear_auth_cookies(response, request)
    return {"ok": True}

@api.get("/auth/me")
async def me(user=Depends(current_user)):
    return user

@api.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    import jwt as _jwt
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = _jwt.decode(token, A.get_jwt_secret(), algorithms=[A.JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
        u = await db.users.find_one({"id": payload["sub"]})
        if not u or payload.get("ver", 0) != u.get("token_version", 0):
            raise HTTPException(status_code=401, detail="Session expired")
        A.set_auth_cookies(response, A.create_access_token(u["id"], u["email"], u.get("token_version", 0)),
                           A.create_refresh_token(u["id"], u.get("token_version", 0)))
        return {"ok": True, "token": A.create_access_token(u["id"], u["email"], u.get("token_version", 0))}
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# =================================================================
# USERS & ACCESS
# =================================================================
ALL_PERMISSIONS = ["view","create","edit","delete","submit","approve","reject","cancel","close",
                   "print","export","upload_attachment","view_all_division","view_all_warehouse",
                   "view_purchase_price","edit_purchase_price","override_qty","direct_mi",
                   "stock_adjustment","post_stock_opname"]

ROLE_DEFAULTS = {
    "admin": ALL_PERMISSIONS,
    "director": ALL_PERMISSIONS,
    "manager": ["view","create","edit","submit","approve","reject","cancel","close","print","export","view_all_division","view_all_warehouse","view_purchase_price"],
    "purchasing": ["view","create","edit","submit","cancel","print","export","upload_attachment","view_all_division","view_all_warehouse","view_purchase_price","edit_purchase_price"],
    "warehouse": ["view","create","edit","submit","print","upload_attachment","direct_mi"],
}

@api.get("/users")
async def list_users(user=Depends(current_user)):
    require(user, "view")
    return await db.users.find({}, {"password_hash": 0, "_id": 0}).to_list(1000)

@api.post("/users")
async def create_user(body: dict, user=Depends(current_user)):
    require(user, "create")
    email = body["email"].lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email sudah terdaftar")
    uid = gid(); role = body.get("role", "warehouse")
    doc = {"id": uid, "email": email, "password_hash": A.hash_password(body.get("password", "changeme123")),
           "name": body.get("name", email), "role": role,
           "divisions": body.get("divisions", []), "warehouses": body.get("warehouses", []),
           "permissions": body.get("permissions", ROLE_DEFAULTS.get(role, [])),
           "scope": body.get("scope", "limited"), "is_active": body.get("is_active", True),
           "token_version": 0, "signature_url": body.get("signature_url"), "created_at": now_iso()}
    await db.users.insert_one(doc)
    await audit(user, "create", "user", uid, email)
    clean(doc); doc.pop("password_hash", None)
    return doc

@api.put("/users/{uid}")
async def update_user(uid: str, body: dict, user=Depends(current_user)):
    require(user, "edit")
    upd = {k: v for k, v in body.items() if k in ("name","role","divisions","warehouses","permissions","scope","is_active","signature_url")}
    if body.get("password"):
        upd["password_hash"] = A.hash_password(body["password"])
    await db.users.update_one({"id": uid}, {"$set": upd})
    await audit(user, "edit", "user", uid)
    return await db.users.find_one({"id": uid}, {"password_hash": 0, "_id": 0})

@api.delete("/users/{uid}")
async def delete_user(uid: str, user=Depends(current_user)):
    require(user, "delete")
    await db.users.update_one({"id": uid}, {"$set": {"is_active": False}})
    await audit(user, "delete", "user", uid)
    return {"ok": True}

@api.get("/permissions/catalog")
async def perm_catalog(user=Depends(current_user)):
    return {"permissions": ALL_PERMISSIONS, "role_defaults": ROLE_DEFAULTS}

# =================================================================
# MASTER DATA (generic CRUD)
# =================================================================
MASTER_COLLECTIONS = {
    "divisions": db.divisions, "warehouses": db.warehouses, "projects": db.projects,
    "units": db.units, "suppliers": db.suppliers, "items": db.items,
}

def _mc(name):
    if name not in MASTER_COLLECTIONS:
        raise HTTPException(status_code=404, detail="Master tidak ditemukan")
    return MASTER_COLLECTIONS[name]

@api.get("/master/{name}")
async def master_list(name: str, user=Depends(current_user), q: Optional[str] = None, active_only: bool = False):
    col = _mc(name)
    query = {"is_active": True} if active_only else {}
    docs = await col.find(query, {"_id": 0}).sort("created_at", -1).to_list(3000)
    if name == "items" and not is_global(user) and user.get("divisions"):
        docs = [d for d in docs if d.get("division_id") in user["divisions"]]
    if q:
        ql = q.lower()
        docs = [d for d in docs if ql in str(d.get("code","")).lower() or ql in str(d.get("name","")).lower()
                or ql in str(d.get("part_number","")).lower() or ql in str(d.get("alias","")).lower()]
    return docs

@api.post("/master/{name}")
async def master_create(name: str, body: dict, user=Depends(current_user)):
    require(user, "create")
    col = _mc(name)
    if body.get("code") and await col.find_one({"code": body["code"]}):
        raise HTTPException(status_code=400, detail="Kode sudah dipakai")
    doc = {**body, "id": gid(), "is_active": body.get("is_active", True), "created_at": now_iso()}
    doc.pop("_id", None)
    await col.insert_one(doc)
    await audit(user, "create", name, doc["id"], doc.get("code"))
    return clean(doc)

@api.put("/master/{name}/{rid}")
async def master_update(name: str, rid: str, body: dict, user=Depends(current_user)):
    require(user, "edit")
    col = _mc(name)
    body.pop("id", None); body.pop("_id", None)
    await col.update_one({"id": rid}, {"$set": body})
    await audit(user, "edit", name, rid)
    return clean(await col.find_one({"id": rid}))

@api.delete("/master/{name}/{rid}")
async def master_delete(name: str, rid: str, user=Depends(current_user)):
    require(user, "delete")
    await _mc(name).update_one({"id": rid}, {"$set": {"is_active": False}})
    await audit(user, "delete", name, rid)
    return {"ok": True}

@api.get("/item-warehouse")
async def item_warehouse_list(user=Depends(current_user), warehouse_id: Optional[str] = None, item_id: Optional[str] = None):
    query = {}
    if warehouse_id: query["warehouse_id"] = warehouse_id
    if item_id: query["item_id"] = item_id
    rows = await db.item_warehouse.find(query, {"_id": 0}).to_list(5000)
    items = {i["id"]: i for i in await db.items.find({}, {"_id": 0}).to_list(5000)}
    whs = {w["id"]: w for w in await db.warehouses.find({}, {"_id": 0}).to_list(2000)}
    for r in rows:
        it = items.get(r["item_id"], {})
        r["item_code"] = it.get("code"); r["item_name"] = it.get("name")
        r["unit"] = it.get("unit"); r["division_id"] = it.get("division_id")
        r["warehouse_name"] = whs.get(r["warehouse_id"], {}).get("name")
        cur = r.get("current_stock", 0); mn = r.get("min_stock", 0); mx = r.get("max_stock", 0)
        r["status"] = ("Out of Stock" if cur <= 0 else "Low Stock" if cur <= mn else
                       "Overstock" if mx and cur > mx else "Normal")
        r["suggested_order"] = max(0, (mx or 0) - cur)
    return rows

@api.post("/item-warehouse")
async def item_warehouse_set(body: dict, user=Depends(current_user)):
    require(user, "edit")
    existing = await db.item_warehouse.find_one({"item_id": body["item_id"], "warehouse_id": body["warehouse_id"]})
    await db.item_warehouse.update_one(
        {"item_id": body["item_id"], "warehouse_id": body["warehouse_id"]},
        {"$set": {"item_id": body["item_id"], "warehouse_id": body["warehouse_id"],
                  "min_stock": body.get("min_stock", 0), "max_stock": body.get("max_stock", 0),
                  "current_stock": body.get("current_stock", (existing or {}).get("current_stock", 0))}},
        upsert=True)
    return {"ok": True}

import doc_procurement  # noqa: E402,F401
import doc_warehouse    # noqa: E402,F401
import doc_reports      # noqa: E402,F401

@api.get("/_healthcheck")
async def _healthcheck():
    return {"message": "Success", "db": DB_BACKEND}

@api.get("/_system")
async def _system(request: Request):
    return {"ok": True, "db": DB_BACKEND, "storage": S.STORAGE_DRIVER,
            "cookieSecure": A.is_secure_request(request), "cookieSecureSetting": A.COOKIE_SECURE_SETTING,
            "requestProto": request.headers.get("x-forwarded-proto") or request.url.scheme}

app.include_router(api)
_cors_origins = [o.strip().rstrip("/") for o in (os.environ.get("CORS_ORIGINS") or os.environ.get("FRONTEND_URL", "http://localhost:3000")).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_credentials=True,
                   allow_origins=_cors_origins,
                   allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup():
    if DB_BACKEND == "mariadb":
        await db.ping()
        logger.info("Database: MariaDB (%s)", os.environ.get("DATABASE_URL", "").split("@")[-1])
    await A.seed_admin(db)
    try:
        await db.users.create_index("email", unique=True)
        await db.login_attempts.create_index("identifier")
        await db.stock_ledger.create_index([("item_id",1),("warehouse_id",1)])
        await db.allocations.create_index("source_line_id")
        await db.allocations.create_index("target_line_id")
    except Exception as e:
        logger.warning(f"index: {e}")
    try:
        S.init_storage()
    except Exception as e:
        logger.warning(f"storage init: {e}")
    await seed_defaults()
    await write_test_credentials()

async def seed_defaults():
    if await db.divisions.count_documents({}) == 0:
        for c, n in [("SPR","Sparepart"),("CON","Consumable"),("AST","Asset"),("ATK","ATK"),("GEN","General")]:
            await db.divisions.insert_one({"id": gid(), "code": c, "name": n, "is_active": True, "created_at": now_iso()})
    if await db.settings.find_one({"id": "numbering"}) is None:
        await db.settings.insert_one({"id": "numbering", "formats": {
            "MRO":"MRO/{year}/{month}/{seq}","RO":"RO/{year}/{month}/{seq}","PO":"PO/{year}/{month}/{seq}",
            "DO":"DO/{year}/{month}/{seq}","MI":"MI/{year}/{month}/{seq}","TRF":"TRF/{year}/{month}/{seq}",
            "LOAN":"LOAN/{year}/{month}/{seq}","RET":"RET/{year}/{month}/{seq}","ADJ":"ADJ/{year}/{month}/{seq}",
            "OPN":"OPN/{year}/{month}/{seq}"}})
    if await db.settings.find_one({"id": "approval_rules"}) is None:
        await db.settings.insert_one({"id": "approval_rules", "rules": [
            {"max": 10000000, "approvers": ["manager"]},
            {"max": 50000000, "approvers": ["manager","director"]},
            {"max": None, "approvers": ["manager","director"]}]})
    if await db.settings.find_one({"id": "company"}) is None:
        await db.settings.insert_one({"id": "company", "name": "PT. Perusahaan Anda",
                                      "address": "Alamat perusahaan", "logo_url": None, "damaged_method": "method1"})
    await seed_demo()

async def seed_demo():
    if await db.items.count_documents({}) > 0:
        return
    divs = {d["name"]: d["id"] for d in await db.divisions.find({}, {"_id": 0}).to_list(50)}
    whs = []
    for c, n, loc in [("GDA", "Gudang A - Pusat", "Jakarta"), ("GDB", "Gudang B - Proyek", "Bandung")]:
        wid = gid(); whs.append(wid)
        await db.warehouses.insert_one({"id": wid, "code": c, "name": n, "location": loc, "pic": "PIC " + c, "is_active": True, "created_at": now_iso()})
    for c, n, pic in [("SUP01", "PT Sumber Makmur", "Budi"), ("SUP02", "CV Teknik Jaya", "Andi")]:
        await db.suppliers.insert_one({"id": gid(), "code": c, "name": n, "contact": pic, "phone": "021-000", "is_active": True, "created_at": now_iso()})
    for c, n in [("PRJ01", "Proyek Tol Trans"), ("PRJ02", "Maintenance 2026")]:
        await db.projects.insert_one({"id": gid(), "code": c, "name": n, "status": "Aktif", "is_active": True, "created_at": now_iso()})
    for c, n, plate, typ in [("UNT01", "Truck Hino 500", "BM 1234 XX", "Truck"), ("UNT02", "Excavator CAT", "EX-002", "Excavator")]:
        await db.units.insert_one({"id": gid(), "code": c, "name": n, "plate_no": plate, "type": typ, "division_id": divs.get("Asset"), "is_active": True, "created_at": now_iso()})
    items = [("SP001", "Oli Mesin 15W-40", "liter", "Sparepart"), ("SP002", "Filter Oli", "pcs", "Sparepart"),
             ("SP003", "Kampas Rem", "set", "Sparepart"), ("CN001", "Majun", "kg", "Consumable"),
             ("CN002", "Sarung Tangan", "pasang", "Consumable"), ("AT001", "Kertas A4", "rim", "ATK")]
    for c, n, u, dv in items:
        iid = gid()
        await db.items.insert_one({"id": iid, "code": c, "name": n, "unit": u, "category": dv,
                                   "division_id": divs.get(dv), "is_active": True, "created_at": now_iso()})
        for wid in whs:
            init = 50 if c.startswith("SP") else 100
            await db.item_warehouse.insert_one({"item_id": iid, "warehouse_id": wid, "min_stock": 20, "max_stock": 200, "current_stock": init})
            await db.stock_ledger.insert_one({"id": gid(), "doc_type": "Opening Balance", "doc_no": "OB", "doc_id": "ob",
                "item_id": iid, "warehouse_id": wid, "qty_in": init, "qty_out": 0, "running_balance": init,
                "project_id": None, "unit_id": None, "division_id": divs.get(dv), "user": "system", "at": now_iso()})

async def write_test_credentials():
    Path("/app/memory/test_credentials.md").write_text(f"""# Test Credentials

## Admin (owner)
- Email: {os.environ.get('ADMIN_EMAIL')}
- Password: {os.environ.get('ADMIN_PASSWORD')}
- Role: admin (all permissions, global scope)

## Auth endpoints
- POST /api/auth/login
- POST /api/auth/register
- GET  /api/auth/me
- POST /api/auth/logout
- POST /api/auth/refresh

Cookies httpOnly; frontend uses withCredentials. Bearer header also supported.
""")


# ---------------------------------------------------------------------------
# Entry point tunggal: `uvicorn server:app` otomatis memasang seluruh layer
# (sama seperti `python production_bootstrap.py`). production_bootstrap mengeset
# PROCUREFLOW_ENTRY=bootstrap sebelum mengimpor modul ini untuk mencegah impor ganda.
# ---------------------------------------------------------------------------
if os.environ.get("PROCUREFLOW_ENTRY") != "bootstrap":
    import production_bootstrap  # noqa: E402,F401
