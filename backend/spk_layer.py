"""CP1 — SPK Foundation.

Master SPK sebagai sumber kontrol budget Procurement (fondasi, belum terhubung ke MRO/RO/PO).

Menyediakan:
- Permission spk:view / spk:manage dan procurement_budget_policy:view / :manage
- Tenant Procurement Settings: default Global & Category Budget Control Policy
- Master SPK CRUD + status (draft/active/closed/cancelled)
- Nilai SPK vs Budget Procurement (integer rupiah, bukan float) + validasi
- Budget Control Policy per-SPK (USE_TENANT_DEFAULT / CUSTOM) + Effective Policy service
- Reusable future-enforcement helper (Projected Commitment / Remaining)
- Dokumen SPK (PDF/JPG/PNG/WEBP <=10MB, prefix preview/staging, tenant-safe object key)
- Audit trail SPK + audit khusus perubahan Budget Control Policy

Semua query tenant-aware (proxy isolation otomatis meng-scope tenant_id).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

import storage as S

POLICY_MODES = {"USE_TENANT_DEFAULT", "CUSTOM"}
POLICY_VALUES = {"WARNING_ONLY", "HARD_BLOCK"}
SPK_STATUSES = {"draft", "active", "closed", "cancelled"}
DEFAULT_TENANT_POLICY = {"default_global_budget_policy": "HARD_BLOCK", "default_category_budget_policy": "WARNING_ONLY"}

DOC_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_DOC_SIZE = 10 * 1024 * 1024

# CP1 §6 — R2 object keys must be environment-based. In production (APP_ENV=production)
# SPK documents live under ".../spk-documents/..."; in preview/staging they are isolated
# under ".../preview/spk-documents/..." so preview never touches production objects.
APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "")).strip().lower()
IS_PRODUCTION = APP_ENV in ("production", "prod")
DOC_PATH_SEGMENT = "spk-documents" if IS_PRODUCTION else "preview/spk-documents"

PERM_SPK_VIEW = "spk:view"
PERM_SPK_MANAGE = "spk:manage"
PERM_POLICY_VIEW = "procurement_budget_policy:view"
PERM_POLICY_MANAGE = "procurement_budget_policy:manage"
PERM_ADD_VIEW = "spk_addendum:view"
PERM_ADD_MANAGE = "spk_addendum:manage"
PERM_ADD_FINALIZE = "spk_addendum:finalize"
NEW_PERMISSIONS = [PERM_SPK_VIEW, PERM_SPK_MANAGE, PERM_POLICY_VIEW, PERM_POLICY_MANAGE,
                   PERM_ADD_VIEW, PERM_ADD_MANAGE, PERM_ADD_FINALIZE]
ADDENDUM_TYPES = {"SPK_VALUE", "PROCUREMENT_BUDGET", "BOTH"}
ADDENDUM_STATUSES = {"draft", "effective", "cancelled"}
ADD_DOC_SEGMENT = "spk-addendums" if os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "")).strip().lower() in ("production", "prod") else "preview/spk-addendums"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _money(value, field: str) -> int:
    """Simpan nilai uang sebagai integer rupiah (hindari floating point)."""
    if value is None or value == "":
        return 0
    try:
        # terima "5000000000", 5000000000, 5000000000.0 -> integer rupiah
        iv = int(round(float(value)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} harus berupa angka")
    if iv < 0:
        raise HTTPException(status_code=400, detail=f"{field} tidak boleh negatif")
    return iv


# ------------------------------------------------------------------ reusable services
def effective_policy(spk: dict, tenant_defaults: dict) -> dict:
    """Menentukan Effective Budget Policy (dipakai backend, bukan hanya frontend)."""
    td = tenant_defaults or DEFAULT_TENANT_POLICY
    mode = (spk or {}).get("budget_policy_mode") or "USE_TENANT_DEFAULT"
    if mode == "CUSTOM":
        return {
            "source": "CUSTOM",
            "global": spk.get("custom_global_budget_policy") or td["default_global_budget_policy"],
            "category": spk.get("custom_category_budget_policy") or td["default_category_budget_policy"],
        }
    return {
        "source": "USE_TENANT_DEFAULT",
        "global": td["default_global_budget_policy"],
        "category": td["default_category_budget_policy"],
    }


def evaluate_budget(existing_commitment: int, current_txn: int, budget: int, policy: str) -> dict:
    """Future-enforcement helper (belum di-wire ke PO pada CP1).

    Projected Commitment = existing + current; Projected Remaining = budget - projected.
    decision: 'ok' bila remaining>=0; else 'warning' (WARNING_ONLY) atau 'block' (HARD_BLOCK).
    """
    projected_commitment = int(existing_commitment or 0) + int(current_txn or 0)
    projected_remaining = int(budget or 0) - projected_commitment
    if projected_remaining >= 0:
        decision = "ok"
    else:
        decision = "block" if policy == "HARD_BLOCK" else "warning"
    return {
        "projected_commitment": projected_commitment,
        "projected_remaining": projected_remaining,
        "over_by": max(0, -projected_remaining),
        "policy": policy,
        "decision": decision,
    }


# ------------------------------------------------------------------ pydantic models
class BudgetPolicyIn(BaseModel):
    default_global_budget_policy: str
    default_category_budget_policy: str


class SpkIn(BaseModel):
    spk_number: str = Field(min_length=1, max_length=120)
    project_name: str = Field(min_length=1, max_length=250)
    customer: str | None = Field(default=None, max_length=250)
    spk_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    division_id: str | None = None
    division_name: str | None = None
    pic_id: str | None = None
    pic_name: str | None = None
    project_id: str | None = None
    spk_value: float | int | str | None = 0
    procurement_budget: float | int | str | None = 0
    status: str | None = "draft"
    notes: str | None = Field(default=None, max_length=4000)
    budget_policy_mode: str | None = "USE_TENANT_DEFAULT"
    custom_global_budget_policy: str | None = None
    custom_category_budget_policy: str | None = None
    category_allocations: list | None = None  # future-ready; disimpan tapi belum dipakai transaksi


class StatusIn(BaseModel):
    status: str


class AddendumIn(BaseModel):
    addendum_number: str = Field(min_length=1, max_length=120)
    addendum_date: str
    addendum_type: str
    effective_date: str | None = None
    pic_id: str | None = None
    pic_name: str | None = None
    division_id: str | None = None
    division_name: str | None = None
    reason: str = Field(min_length=1, max_length=4000)
    spk_value_change: float | int | str | None = 0   # signed delta
    budget_change: float | int | str | None = 0       # signed delta


class FinalizeIn(BaseModel):
    expected_spk_value: int | None = None
    expected_procurement_budget: int | None = None


def _signed(value, field: str) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} harus berupa angka")


def install(server):
    app = server.app
    db_ref = server  # akses server.db saat runtime (proxy tenant-scoped)

    # --- daftarkan permission baru ke arsitektur permission existing ---
    try:
        for p in NEW_PERMISSIONS:
            if p not in server.ALL_PERMISSIONS:
                server.ALL_PERMISSIONS.append(p)
        rd = server.ROLE_DEFAULTS
        # Tenant Admin & Director: seluruh permission (admin sudah bypass, tapi eksplisit untuk director).
        for role in ("admin", "director"):
            for p in NEW_PERMISSIONS:
                if p not in rd.get(role, []):
                    rd.setdefault(role, []).append(p)
        # Procurement Manager / Head: boleh manage SPK & budget policy.
        for p in NEW_PERMISSIONS:
            if p not in rd.get("manager", []):
                rd.setdefault("manager", []).append(p)
        # Buyer / Purchasing: hanya view (tidak boleh manage budget policy).
        for p in (PERM_SPK_VIEW, PERM_POLICY_VIEW, PERM_ADD_VIEW):
            if p not in rd.get("purchasing", []):
                rd.setdefault("purchasing", []).append(p)
    except Exception as exc:  # pragma: no cover
        server.logger.warning(f"SPK permission registration: {exc}")

    def _db():
        return db_ref.db

    def _require(user, perm):
        server.require(user, perm)

    async def _tenant_defaults():
        row = await _db().settings.find_one({"id": "procurement_budget_policy"}, {"_id": 0}) or {}
        return {
            "default_global_budget_policy": row.get("default_global_budget_policy") or DEFAULT_TENANT_POLICY["default_global_budget_policy"],
            "default_category_budget_policy": row.get("default_category_budget_policy") or DEFAULT_TENANT_POLICY["default_category_budget_policy"],
        }

    async def _policy_audit(user, *, scope, policy_type, previous, new, spk_id=None, spk_number=None):
        await _db().budget_policy_audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "actor": user.get("email"),
            "actor_name": user.get("name"),
            "scope": scope,          # TENANT_DEFAULT | SPK_CUSTOM
            "policy_type": policy_type,  # GLOBAL | CATEGORY | MODE
            "spk_id": spk_id,
            "spk_number": spk_number,
            "previous_value": previous,
            "new_value": new,
            "at": _now(),
        })

    def _budget_summary(spk: dict) -> dict:
        budget = int(spk.get("procurement_budget") or 0)
        commitment = 0  # CP2: belum ada transaksi PO
        realisasi = 0
        available = budget - commitment
        pct = round((commitment / budget) * 100, 2) if budget else 0
        return {
            "spk_value": int(spk.get("spk_value") or 0),
            "procurement_budget": budget,
            "original_spk_value": int(spk.get("original_spk_value", spk.get("spk_value") or 0) or 0),
            "original_procurement_budget": int(spk.get("original_procurement_budget", spk.get("procurement_budget") or 0) or 0),
            "commitment": commitment,
            "realisasi": realisasi,
            "available_budget": available,
            "commitment_pct": pct,
            "over_budget": bool(spk.get("over_budget")),
        }

    async def _enrich(spk: dict) -> dict:
        td = await _tenant_defaults()
        docs = await _db().spk_documents.find({"spk_id": spk["id"]}, {"_id": 0}).sort("uploaded_at", -1).to_list(500)
        allocations = await _db().spk_budget_allocations.find({"spk_id": spk["id"]}, {"_id": 0}).to_list(500)
        return {
            **spk,
            "budget_summary": _budget_summary(spk),
            "effective_policy": effective_policy(spk, td),
            "tenant_default_policy": td,
            "documents": docs,
            "document_count": len(docs),
            "category_allocations": allocations,
            "addendums": await _db().spk_addendums.find({"spk_id": spk["id"]}, {"_id": 0}).sort("created_at", 1).to_list(1000),
        }

    def _validate_spk(body: SpkIn, *, can_manage_policy: bool, existing: dict | None = None):
        number = (body.spk_number or "").strip()
        if not number:
            raise HTTPException(status_code=400, detail="Nomor SPK wajib diisi")
        project = (body.project_name or "").strip()
        if not project:
            raise HTTPException(status_code=400, detail="Nama pekerjaan wajib diisi")
        spk_value = _money(body.spk_value, "Nilai SPK")
        budget = _money(body.procurement_budget, "Budget Procurement")
        if budget > spk_value:
            raise HTTPException(status_code=400, detail="Budget Procurement tidak boleh melebihi Nilai SPK")
        if body.start_date and body.end_date and str(body.end_date) < str(body.start_date):
            raise HTTPException(status_code=400, detail="Tanggal berakhir tidak boleh sebelum tanggal mulai")
        status = (body.status or "draft").lower()
        if status not in SPK_STATUSES:
            raise HTTPException(status_code=400, detail="Status SPK tidak valid")

        mode = (body.budget_policy_mode or "USE_TENANT_DEFAULT").upper()
        if mode not in POLICY_MODES:
            raise HTTPException(status_code=400, detail="Mode Budget Control Policy tidak valid")
        cg = (body.custom_global_budget_policy or "").upper() or None
        cc = (body.custom_category_budget_policy or "").upper() or None
        if mode == "CUSTOM":
            if not cg or not cc:
                raise HTTPException(status_code=400, detail="Custom policy wajib memiliki Global dan Category policy")
            if cg not in POLICY_VALUES or cc not in POLICY_VALUES:
                raise HTTPException(status_code=400, detail="Nilai policy harus WARNING_ONLY atau HARD_BLOCK")
        else:
            cg = cc = None

        # Authorization backend untuk perubahan policy (tidak cukup sembunyikan tombol).
        prev_mode = (existing or {}).get("budget_policy_mode", "USE_TENANT_DEFAULT")
        prev_cg = (existing or {}).get("custom_global_budget_policy")
        prev_cc = (existing or {}).get("custom_category_budget_policy")
        policy_changed = (mode != prev_mode) or (cg != prev_cg) or (cc != prev_cc)
        if policy_changed and not can_manage_policy:
            raise HTTPException(status_code=403, detail="Tidak punya izin mengubah Budget Control Policy (procurement_budget_policy:manage)")

        return {
            "spk_number": number, "project_name": project,
            "customer": (body.customer or "").strip() or None,
            "spk_date": body.spk_date or None, "start_date": body.start_date or None, "end_date": body.end_date or None,
            "division_id": body.division_id or None, "pic_id": body.pic_id or None, "project_id": body.project_id or None,
            "division_name": (body.division_name or "").strip() or None, "pic_name": (body.pic_name or "").strip() or None,
            "spk_value": spk_value, "procurement_budget": budget, "status": status,
            "notes": (body.notes or "").strip() or None,
            "budget_policy_mode": mode, "custom_global_budget_policy": cg, "custom_category_budget_policy": cc,
        }, policy_changed

    # ============================ TENANT BUDGET POLICY ============================
    @app.get("/api/procurement/budget-policy", tags=["spk"])
    async def get_budget_policy(user=Depends(server.current_user)):
        _require(user, PERM_POLICY_VIEW)
        td = await _tenant_defaults()
        return {**td, "can_manage": server.has_perm(user, PERM_POLICY_MANAGE)}

    @app.put("/api/procurement/budget-policy", tags=["spk"])
    async def set_budget_policy(body: BudgetPolicyIn, user=Depends(server.current_user)):
        _require(user, PERM_POLICY_MANAGE)
        g = (body.default_global_budget_policy or "").upper()
        c = (body.default_category_budget_policy or "").upper()
        if g not in POLICY_VALUES or c not in POLICY_VALUES:
            raise HTTPException(status_code=400, detail="Policy harus WARNING_ONLY atau HARD_BLOCK")
        prev = await _tenant_defaults()
        await _db().settings.update_one(
            {"id": "procurement_budget_policy"},
            {"$set": {"id": "procurement_budget_policy", "default_global_budget_policy": g,
                      "default_category_budget_policy": c, "updated_at": _now(), "updated_by": user.get("email")}},
            upsert=True,
        )
        if prev["default_global_budget_policy"] != g:
            await _policy_audit(user, scope="TENANT_DEFAULT", policy_type="GLOBAL",
                                previous=prev["default_global_budget_policy"], new=g)
        if prev["default_category_budget_policy"] != c:
            await _policy_audit(user, scope="TENANT_DEFAULT", policy_type="CATEGORY",
                                previous=prev["default_category_budget_policy"], new=c)
        return {"default_global_budget_policy": g, "default_category_budget_policy": c, "can_manage": True}

    # ============================ SPK CRUD ============================
    @app.get("/api/spk", tags=["spk"])
    async def list_spk(q: str = "", status: str = "", division_id: str = "", period_start: str = "",
                       period_end: str = "", sort: str = "-created_at", page: int = 1, page_size: int = 20,
                       user=Depends(server.current_user)):
        _require(user, PERM_SPK_VIEW)
        flt = {}
        if status:
            flt["status"] = status
        if division_id:
            flt["division_id"] = division_id
        if period_start:
            flt.setdefault("start_date", {})["$gte"] = period_start
        if period_end:
            flt.setdefault("end_date", {})["$lte"] = period_end
        rows = await _db().spk.find(flt, {"_id": 0}).to_list(100000)
        if q:
            ql = q.strip().lower()
            rows = [r for r in rows if any(ql in str(r.get(k) or "").lower()
                    for k in ("spk_number", "project_name", "customer", "pic_name"))]
        # sorting
        reverse = sort.startswith("-")
        key = sort.lstrip("-") or "created_at"
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=reverse)
        total = len(rows)
        page = max(1, int(page)); page_size = min(200, max(1, int(page_size)))
        start = (page - 1) * page_size
        items = rows[start:start + page_size]
        # ringkas budget summary + effective policy untuk kolom tabel
        td = await _tenant_defaults()
        for it in items:
            it["available_budget"] = int(it.get("procurement_budget") or 0)
            it["effective_policy"] = effective_policy(it, td)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @app.post("/api/spk", tags=["spk"])
    async def create_spk(body: SpkIn, user=Depends(server.current_user)):
        _require(user, PERM_SPK_MANAGE)
        can_policy = server.has_perm(user, PERM_POLICY_MANAGE)
        data, policy_changed = _validate_spk(body, can_manage_policy=can_policy)
        # unik per tenant (collection auto tenant-scoped)
        dup = await _db().spk.find_one({"spk_number": data["spk_number"]}, {"_id": 0, "id": 1})
        if dup:
            raise HTTPException(status_code=409, detail=f"Nomor SPK '{data['spk_number']}' sudah digunakan di tenant ini")
        spk_id = str(uuid.uuid4())
        now = _now()
        doc = {
            "id": spk_id, **data,
            "original_spk_value": data["spk_value"],
            "original_procurement_budget": data["procurement_budget"],
            "over_budget": False,
            "created_by": user.get("email"), "created_at": now,
            "updated_by": user.get("email"), "updated_at": now,
        }
        await _db().spk.insert_one(doc)
        # future-ready category allocations (belum dipakai transaksi)
        for alloc in (body.category_allocations or []):
            try:
                await _db().spk_budget_allocations.insert_one({
                    "id": str(uuid.uuid4()), "spk_id": spk_id,
                    "category_id": alloc.get("category_id"),
                    "allocated_budget": _money(alloc.get("allocated_budget"), "Alokasi kategori"),
                    "created_at": now,
                })
            except HTTPException:
                pass
        await server.audit(user, "create", "spk", spk_id, doc.get("spk_number"), after={
            "spk_number": doc["spk_number"], "spk_value": doc["spk_value"],
            "procurement_budget": doc["procurement_budget"], "status": doc["status"],
        })
        if policy_changed and data["budget_policy_mode"] == "CUSTOM":
            await _policy_audit(user, scope="SPK_CUSTOM", policy_type="MODE", previous="USE_TENANT_DEFAULT",
                                new={"global": data["custom_global_budget_policy"], "category": data["custom_category_budget_policy"]},
                                spk_id=spk_id, spk_number=doc["spk_number"])
        clean = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        return await _enrich(clean)

    @app.get("/api/spk/{spk_id}", tags=["spk"])
    async def get_spk(spk_id: str, user=Depends(server.current_user)):
        _require(user, PERM_SPK_VIEW)
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        if not spk:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        result = await _enrich(spk)
        result["can_manage"] = server.has_perm(user, PERM_SPK_MANAGE)
        result["can_manage_policy"] = server.has_perm(user, PERM_POLICY_MANAGE)
        result["can_manage_addendum"] = server.has_perm(user, PERM_ADD_MANAGE)
        result["can_finalize_addendum"] = server.has_perm(user, PERM_ADD_FINALIZE)
        return result

    @app.put("/api/spk/{spk_id}", tags=["spk"])
    async def update_spk(spk_id: str, body: SpkIn, user=Depends(server.current_user)):
        _require(user, PERM_SPK_MANAGE)
        existing = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        can_policy = server.has_perm(user, PERM_POLICY_MANAGE)
        data, policy_changed = _validate_spk(body, can_manage_policy=can_policy, existing=existing)
        if data["spk_number"] != existing.get("spk_number"):
            dup = await _db().spk.find_one({"spk_number": data["spk_number"], "id": {"$ne": spk_id}}, {"_id": 0, "id": 1})
            if dup:
                raise HTTPException(status_code=409, detail=f"Nomor SPK '{data['spk_number']}' sudah digunakan di tenant ini")
        data["updated_by"] = user.get("email"); data["updated_at"] = _now()
        await _db().spk.update_one({"id": spk_id}, {"$set": data})
        await server.audit(user, "edit", "spk", spk_id, data.get("spk_number"),
                           before={"spk_number": existing.get("spk_number"), "spk_value": existing.get("spk_value"),
                                   "procurement_budget": existing.get("procurement_budget"), "status": existing.get("status")},
                           after={"spk_number": data["spk_number"], "spk_value": data["spk_value"],
                                  "procurement_budget": data["procurement_budget"], "status": data["status"]})
        if policy_changed:
            await _policy_audit(user, scope="SPK_CUSTOM", policy_type="MODE",
                                previous={"mode": existing.get("budget_policy_mode"),
                                          "global": existing.get("custom_global_budget_policy"),
                                          "category": existing.get("custom_category_budget_policy")},
                                new={"mode": data["budget_policy_mode"],
                                     "global": data["custom_global_budget_policy"],
                                     "category": data["custom_category_budget_policy"]},
                                spk_id=spk_id, spk_number=data["spk_number"])
        updated = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        return await _enrich(updated)

    @app.patch("/api/spk/{spk_id}/status", tags=["spk"])
    async def change_status(spk_id: str, body: StatusIn, user=Depends(server.current_user)):
        _require(user, PERM_SPK_MANAGE)
        status = (body.status or "").lower()
        if status not in SPK_STATUSES:
            raise HTTPException(status_code=400, detail="Status SPK tidak valid")
        existing = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        await _db().spk.update_one({"id": spk_id}, {"$set": {"status": status, "updated_by": user.get("email"), "updated_at": _now()}})
        await server.audit(user, "edit", "spk", spk_id, existing.get("spk_number"),
                           before={"status": existing.get("status")}, after={"status": status})
        updated = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        return await _enrich(updated)

    # ============================ SPK DOCUMENTS ============================
    @app.get("/api/spk/{spk_id}/documents", tags=["spk"])
    async def list_documents(spk_id: str, user=Depends(server.current_user)):
        _require(user, PERM_SPK_VIEW)
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0, "id": 1})
        if not spk:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        return await _db().spk_documents.find({"spk_id": spk_id}, {"_id": 0}).sort("uploaded_at", -1).to_list(500)

    @app.post("/api/spk/{spk_id}/documents", tags=["spk"])
    async def upload_document(spk_id: str, file: UploadFile = File(...), user=Depends(server.current_user)):
        _require(user, PERM_SPK_MANAGE)
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        if not spk:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        ctype = (file.content_type or "").lower()
        ext = DOC_TYPES.get(ctype)
        if not ext:
            fname = (file.filename or "").lower()
            for e in ("pdf", "png", "webp", "jpg", "jpeg"):
                if fname.endswith("." + e):
                    ext = "jpg" if e == "jpeg" else e
                    ctype = {"pdf": "application/pdf", "png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}[ext]
                    break
        if not ext:
            raise HTTPException(status_code=400, detail="Tipe file tidak didukung. Gunakan PDF, JPG, PNG, atau WEBP")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="File kosong")
        if len(data) > MAX_DOC_SIZE:
            raise HTTPException(status_code=400, detail="Ukuran file maksimal 10 MB")
        # object key environment-based (production tanpa /preview/); hardening meng-scope tenant
        object_key = f"{S.APP_NAME}/{DOC_PATH_SEGMENT}/{spk_id}/{uuid.uuid4().hex}.{ext}"
        result = S.put_object(object_key, data, ctype)
        doc = {
            "id": str(uuid.uuid4()), "spk_id": spk_id,
            "object_key": result.get("path", object_key),
            "file_name": (file.filename or f"dokumen.{ext}"),
            "mime_type": ctype, "file_size": result.get("size", len(data)),
            "uploaded_by": user.get("email"), "uploaded_at": _now(),
        }
        await _db().spk_documents.insert_one(doc)
        await server.audit(user, "upload_attachment", "spk", spk_id, spk.get("spk_number"),
                           after={"file_name": doc["file_name"], "file_size": doc["file_size"]})
        return {k: v for k, v in doc.items() if k != "_id"}

    @app.get("/api/spk/{spk_id}/documents/{doc_id}/download", tags=["spk"])
    async def download_document(spk_id: str, doc_id: str, user=Depends(server.current_user)):
        _require(user, PERM_SPK_VIEW)
        # tenant-scoped find: dokumen tenant lain tidak akan ketemu (ZT-SPK-07)
        doc = await _db().spk_documents.find_one({"id": doc_id, "spk_id": spk_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        try:
            data, ctype = S.get_object(doc["object_key"])  # scoped_get_object memvalidasi kepemilikan tenant
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File tidak ditemukan")
        return Response(content=data, media_type=doc.get("mime_type") or ctype or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{doc.get("file_name","dokumen")}"'})

    @app.delete("/api/spk/{spk_id}/documents/{doc_id}", tags=["spk"])
    async def delete_document(spk_id: str, doc_id: str, user=Depends(server.current_user)):
        _require(user, PERM_SPK_MANAGE)
        doc = await _db().spk_documents.find_one({"id": doc_id, "spk_id": spk_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        await _db().spk_documents.delete_one({"id": doc_id, "spk_id": spk_id})
        await server.audit(user, "delete", "spk", spk_id, doc.get("file_name"))
        return {"ok": True}

    # ============================ SPK ADDENDUM (CP2) ============================
    def _add_enrich(a: dict) -> dict:
        return {**a}

    async def _list_addendums(spk_id: str):
        return await _db().spk_addendums.find({"spk_id": spk_id}, {"_id": 0}).sort("created_at", 1).to_list(1000)

    @app.get("/api/spk/{spk_id}/addendums", tags=["spk"])
    async def list_addendums(spk_id: str, user=Depends(server.current_user)):
        _require(user, PERM_ADD_VIEW)
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0, "id": 1})
        if not spk:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        return await _list_addendums(spk_id)

    def _validate_addendum(body: AddendumIn):
        atype = (body.addendum_type or "").upper()
        if atype not in ADDENDUM_TYPES:
            raise HTTPException(status_code=400, detail="Tipe Addendum tidak valid")
        sv = _signed(body.spk_value_change, "Perubahan Nilai SPK")
        bv = _signed(body.budget_change, "Perubahan Budget")
        if atype == "SPK_VALUE":
            bv = 0
        elif atype == "PROCUREMENT_BUDGET":
            sv = 0
        return atype, sv, bv

    def _check_resulting(new_sv: int, new_budget: int):
        if new_sv < 0:
            raise HTTPException(status_code=400, detail="Nilai SPK hasil Addendum tidak boleh negatif")
        if new_budget < 0:
            raise HTTPException(status_code=400, detail="Budget Procurement hasil Addendum tidak boleh negatif")
        if new_budget > new_sv:
            raise HTTPException(status_code=400, detail=f"Budget Procurement hasil ({new_budget}) melebihi Nilai SPK hasil ({new_sv}). Addendum tidak dapat difinalisasi.")

    @app.post("/api/spk/{spk_id}/addendums", tags=["spk"])
    async def create_addendum(spk_id: str, body: AddendumIn, user=Depends(server.current_user)):
        _require(user, PERM_ADD_MANAGE)
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        if not spk:
            raise HTTPException(status_code=404, detail="SPK tidak ditemukan")
        num = body.addendum_number.strip()
        if await _db().spk_addendums.find_one({"spk_id": spk_id, "addendum_number": num}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=409, detail=f"Nomor Addendum '{num}' sudah digunakan pada SPK ini")
        atype, sv, bv = _validate_addendum(body)
        now = _now()
        aid = str(uuid.uuid4())
        doc = {
            "id": aid, "spk_id": spk_id, "addendum_number": num,
            "addendum_date": body.addendum_date or None, "addendum_type": atype,
            "effective_date": body.effective_date or None,
            "pic_id": body.pic_id or None, "pic_name": (body.pic_name or "").strip() or None,
            "division_id": body.division_id or None, "division_name": (body.division_name or "").strip() or None,
            "reason": body.reason.strip(),
            "spk_value_change": sv, "budget_change": bv,
            "status": "draft",
            "before_spk_value": None, "after_spk_value": None,
            "before_procurement_budget": None, "after_procurement_budget": None,
            "created_by": user.get("email"), "created_at": now,
            "updated_by": user.get("email"), "updated_at": now,
            "finalized_by": None, "finalized_at": None, "cancelled_by": None, "cancelled_at": None,
        }
        await _db().spk_addendums.insert_one(doc)
        await server.audit(user, "create", "spk_addendum", aid, num,
                           after={"spk_id": spk_id, "type": atype, "spk_value_change": sv, "budget_change": bv})
        clean = await _db().spk_addendums.find_one({"id": aid}, {"_id": 0})
        return clean

    @app.get("/api/spk/{spk_id}/addendums/{aid}", tags=["spk"])
    async def get_addendum(spk_id: str, aid: str, user=Depends(server.current_user)):
        _require(user, PERM_ADD_VIEW)
        a = await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Addendum tidak ditemukan")
        docs = await _db().spk_addendum_documents.find({"addendum_id": aid}, {"_id": 0}).sort("uploaded_at", -1).to_list(500)
        a["documents"] = docs
        a["can_manage"] = server.has_perm(user, PERM_ADD_MANAGE)
        a["can_finalize"] = server.has_perm(user, PERM_ADD_FINALIZE)
        return a

    @app.put("/api/spk/{spk_id}/addendums/{aid}", tags=["spk"])
    async def update_addendum(spk_id: str, aid: str, body: AddendumIn, user=Depends(server.current_user)):
        _require(user, PERM_ADD_MANAGE)
        a = await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Addendum tidak ditemukan")
        if a.get("status") != "draft":
            raise HTTPException(status_code=409, detail="Hanya Addendum berstatus Draft yang dapat diedit. Buat Addendum baru untuk koreksi.")
        atype, sv, bv = _validate_addendum(body)
        num = body.addendum_number.strip()
        dup = await _db().spk_addendums.find_one({"spk_id": spk_id, "addendum_number": num, "id": {"$ne": aid}}, {"_id": 0, "id": 1})
        if dup:
            raise HTTPException(status_code=409, detail=f"Nomor Addendum '{num}' sudah digunakan pada SPK ini")
        upd = {
            "addendum_number": num, "addendum_date": body.addendum_date or None, "addendum_type": atype,
            "effective_date": body.effective_date or None, "pic_id": body.pic_id or None,
            "pic_name": (body.pic_name or "").strip() or None, "division_id": body.division_id or None,
            "division_name": (body.division_name or "").strip() or None, "reason": body.reason.strip(),
            "spk_value_change": sv, "budget_change": bv,
            "updated_by": user.get("email"), "updated_at": _now(),
        }
        await _db().spk_addendums.update_one({"id": aid}, {"$set": upd})
        await server.audit(user, "edit", "spk_addendum", aid, num, before={"spk_value_change": a.get("spk_value_change"), "budget_change": a.get("budget_change")}, after={"spk_value_change": sv, "budget_change": bv})
        return await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})

    @app.post("/api/spk/{spk_id}/addendums/{aid}/finalize", tags=["spk"])
    async def finalize_addendum(spk_id: str, aid: str, body: FinalizeIn, user=Depends(server.current_user)):
        _require(user, PERM_ADD_FINALIZE)
        a = await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Addendum tidak ditemukan")
        if a.get("status") != "draft":
            raise HTTPException(status_code=409, detail="Hanya Addendum Draft yang dapat difinalisasi")
        # concurrency: re-read current SPK values
        spk = await _db().spk.find_one({"id": spk_id}, {"_id": 0})
        cur_sv = int(spk.get("spk_value") or 0)
        cur_budget = int(spk.get("procurement_budget") or 0)
        if body.expected_spk_value is not None and int(body.expected_spk_value) != cur_sv:
            raise HTTPException(status_code=409, detail="Nilai SPK dasar sudah berubah sejak form dibuka. Muat ulang (refresh) sebelum finalisasi.")
        if body.expected_procurement_budget is not None and int(body.expected_procurement_budget) != cur_budget:
            raise HTTPException(status_code=409, detail="Budget dasar sudah berubah sejak form dibuka. Muat ulang (refresh) sebelum finalisasi.")
        new_sv = cur_sv + int(a.get("spk_value_change") or 0)
        new_budget = cur_budget + int(a.get("budget_change") or 0)
        _check_resulting(new_sv, new_budget)
        # future-ready over-budget vs existing commitment (0 in CP2) — warning only, not blocking
        existing_commitment = 0
        over_budget = new_budget < existing_commitment
        warning = None
        if over_budget:
            warning = f"Budget setelah Addendum lebih kecil dari commitment yang sudah berjalan sebesar Rp{existing_commitment - new_budget}."
        now = _now()
        await _db().spk_addendums.update_one({"id": aid}, {"$set": {
            "status": "effective",
            "before_spk_value": cur_sv, "after_spk_value": new_sv,
            "before_procurement_budget": cur_budget, "after_procurement_budget": new_budget,
            "finalized_by": user.get("email"), "finalized_at": now, "updated_at": now,
        }})
        await _db().spk.update_one({"id": spk_id}, {"$set": {
            "spk_value": new_sv, "procurement_budget": new_budget,
            "over_budget": bool(over_budget), "updated_by": user.get("email"), "updated_at": now,
        }})
        await server.audit(user, "edit", "spk_addendum", aid, a.get("addendum_number"),
                           before={"spk_value": cur_sv, "procurement_budget": cur_budget},
                           after={"spk_value": new_sv, "procurement_budget": new_budget, "status": "effective"})
        result = await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})
        if warning:
            result["warning"] = warning
        return result

    @app.post("/api/spk/{spk_id}/addendums/{aid}/cancel", tags=["spk"])
    async def cancel_addendum(spk_id: str, aid: str, user=Depends(server.current_user)):
        _require(user, PERM_ADD_MANAGE)
        a = await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404, detail="Addendum tidak ditemukan")
        if a.get("status") == "effective":
            raise HTTPException(status_code=409, detail="Addendum Effective tidak dapat dibatalkan (buat Addendum koreksi).")
        await _db().spk_addendums.update_one({"id": aid}, {"$set": {"status": "cancelled", "cancelled_by": user.get("email"), "cancelled_at": _now(), "updated_at": _now()}})
        await server.audit(user, "edit", "spk_addendum", aid, a.get("addendum_number"), after={"status": "cancelled"})
        return await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0})

    @app.post("/api/spk/{spk_id}/addendums/{aid}/documents", tags=["spk"])
    async def upload_addendum_doc(spk_id: str, aid: str, file: UploadFile = File(...), user=Depends(server.current_user)):
        _require(user, PERM_ADD_MANAGE)
        a = await _db().spk_addendums.find_one({"id": aid, "spk_id": spk_id}, {"_id": 0, "id": 1, "addendum_number": 1})
        if not a:
            raise HTTPException(status_code=404, detail="Addendum tidak ditemukan")
        ctype = (file.content_type or "").lower()
        ext = DOC_TYPES.get(ctype)
        if not ext:
            fname = (file.filename or "").lower()
            for e in ("pdf", "png", "webp", "jpg", "jpeg"):
                if fname.endswith("." + e):
                    ext = "jpg" if e == "jpeg" else e
                    ctype = {"pdf": "application/pdf", "png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}[ext]
                    break
        if not ext:
            raise HTTPException(status_code=400, detail="Tipe file tidak didukung. Gunakan PDF, JPG, PNG, atau WEBP")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="File kosong")
        if len(data) > MAX_DOC_SIZE:
            raise HTTPException(status_code=400, detail="Ukuran file maksimal 10 MB")
        object_key = f"{S.APP_NAME}/{ADD_DOC_SEGMENT}/{aid}/{uuid.uuid4().hex}.{ext}"
        result = S.put_object(object_key, data, ctype)
        doc = {
            "id": str(uuid.uuid4()), "addendum_id": aid, "spk_id": spk_id,
            "object_key": result.get("path", object_key), "file_name": (file.filename or f"dokumen.{ext}"),
            "mime_type": ctype, "file_size": result.get("size", len(data)),
            "uploaded_by": user.get("email"), "uploaded_at": _now(),
        }
        await _db().spk_addendum_documents.insert_one(doc)
        await server.audit(user, "upload_attachment", "spk_addendum", aid, a.get("addendum_number"), after={"file_name": doc["file_name"]})
        return {k: v for k, v in doc.items() if k != "_id"}

    @app.get("/api/spk/{spk_id}/addendums/{aid}/documents/{doc_id}/download", tags=["spk"])
    async def download_addendum_doc(spk_id: str, aid: str, doc_id: str, user=Depends(server.current_user)):
        _require(user, PERM_ADD_VIEW)
        doc = await _db().spk_addendum_documents.find_one({"id": doc_id, "addendum_id": aid, "spk_id": spk_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        try:
            data, ctype = S.get_object(doc["object_key"])
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File tidak ditemukan")
        return Response(content=data, media_type=doc.get("mime_type") or ctype or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{doc.get("file_name","dokumen")}"'})

    @app.delete("/api/spk/{spk_id}/addendums/{aid}/documents/{doc_id}", tags=["spk"])
    async def delete_addendum_doc(spk_id: str, aid: str, doc_id: str, user=Depends(server.current_user)):
        _require(user, PERM_ADD_MANAGE)
        doc = await _db().spk_addendum_documents.find_one({"id": doc_id, "addendum_id": aid, "spk_id": spk_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        await _db().spk_addendum_documents.delete_one({"id": doc_id, "addendum_id": aid, "spk_id": spk_id})
        await server.audit(user, "delete", "spk_addendum", aid, doc.get("file_name"))
        return {"ok": True}

    server.logger.info("CP1 SPK Foundation layer installed")
