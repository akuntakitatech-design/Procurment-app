"""CP3 — Vendor Contract Price (Master Kontrak Harga Vendor).

Master kontrak harga vendor sebagai SUMBER HARGA REFERENSI RESMI yang nantinya
(di CP4+) dibandingkan dengan harga PO. CP3 TIDAK menghubungkan harga ke PO,
tidak membangun Price Override maupun Approval.

Menyediakan:
- Permission vendor_contract:view / :manage / :activate dan vendor_contract_price:manage
- Master Kontrak (header) + Item Harga Kontrak (base price, discount %/nominal, net price)
- Status: draft / active / cancelled (expired diturunkan dari tanggal berakhir)
- Periode berlaku kontrak & per-item (effective start/end)
- Effective Price Resolver (reusable service + endpoint) — Vendor + Item + UOM + tanggal (+qty)
- Overlapping Active contract protection (Vendor+Item+UOM tidak boleh overlap saat aktif)
- Tolerance dua level: Contract Default & per-item (Use Default / Custom)
- Histori perubahan harga resmi (immutable) — bukan Price Override
- Dokumen kontrak (PDF/JPG/PNG/WEBP <=10MB, path R2 environment-aware, tenant-safe)
- Audit trail + tenant isolation (proxy auto-scope tenant_id)

Nilai uang disimpan sebagai INTEGER (rupiah) dan dihitung dengan Decimal (bukan float).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

import storage as S

CONTRACT_STATUSES = {"draft", "active", "cancelled"}  # 'expired' diturunkan dari tanggal
DISCOUNT_TYPES = {"NONE", "PERCENT", "AMOUNT"}
TOLERANCE_MODES = {"USE_CONTRACT_DEFAULT", "CUSTOM"}

DOC_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_DOC_SIZE = 10 * 1024 * 1024

# R2 object key environment-based (production tanpa /preview/).
APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "")).strip().lower()
IS_PRODUCTION = APP_ENV in ("production", "prod")
VC_DOC_SEGMENT = "vendor-contracts" if IS_PRODUCTION else "preview/vendor-contracts"

PERM_VC_VIEW = "vendor_contract:view"
PERM_VC_MANAGE = "vendor_contract:manage"
PERM_VC_ACTIVATE = "vendor_contract:activate"
PERM_VC_PRICE_MANAGE = "vendor_contract_price:manage"
NEW_PERMISSIONS = [PERM_VC_VIEW, PERM_VC_MANAGE, PERM_VC_ACTIVATE, PERM_VC_PRICE_MANAGE]

_FAR_PAST = "0000-01-01"
_FAR_FUTURE = "9999-12-31"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return date.today().isoformat()


def _money(value, field: str) -> int:
    """Nilai uang sebagai integer (hindari float pada penyimpanan)."""
    if value is None or value == "":
        return 0
    try:
        iv = int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field} harus berupa angka")
    if iv < 0:
        raise HTTPException(status_code=400, detail=f"{field} tidak boleh negatif")
    return iv


def _pct(value, field: str) -> float:
    if value is None or value == "":
        return 0.0
    try:
        p = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} harus berupa angka")
    if p < 0 or p > 100:
        raise HTTPException(status_code=400, detail=f"{field} harus di antara 0 dan 100")
    return round(p, 4)


def compute_net_price(base_price: int, discount_type: str, discount_value) -> int:
    """Net Contract Price = Base Price - discount (percent atau nominal).

    Dihitung dengan Decimal lalu dibulatkan ke integer rupiah. Net >= 0.
    """
    base = int(base_price or 0)
    dtype = (discount_type or "NONE").upper()
    if dtype == "PERCENT":
        pct = Decimal(str(discount_value or 0))
        if pct < 0 or pct > 100:
            raise HTTPException(status_code=400, detail="Diskon persen harus di antara 0 dan 100")
        disc = (Decimal(base) * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        net = base - int(disc)
    elif dtype == "AMOUNT":
        amt = _money(discount_value, "Diskon nominal")
        net = base - amt
    else:
        net = base
    if net < 0:
        raise HTTPException(status_code=400, detail="Diskon menghasilkan Net Price negatif")
    return int(net)


def _period(start, end, c_start, c_end):
    """Periode efektif item: fallback ke periode kontrak bila kosong."""
    s = (start or c_start or _FAR_PAST)
    e = (end or c_end or _FAR_FUTURE)
    return str(s), str(e)


def _overlaps(s1, e1, s2, e2) -> bool:
    return max(str(s1), str(s2)) <= min(str(e1), str(e2))


# ------------------------------------------------------------------ pydantic models
class ContractIn(BaseModel):
    contract_number: str = Field(min_length=1, max_length=120)
    supplier_id: str = Field(min_length=1)
    supplier_name: str | None = None
    contract_date: str | None = None
    start_date: str = Field(min_length=1)
    end_date: str = Field(min_length=1)
    currency: str = Field(default="IDR", min_length=1, max_length=10)
    contract_type: str | None = None
    vendor_pic: str | None = None
    payment_term: str | None = None
    default_tolerance_pct: float | int | str | None = 0
    notes: str | None = Field(default=None, max_length=4000)


class ItemIn(BaseModel):
    item_id: str = Field(min_length=1)
    item_code: str | None = None
    item_name: str | None = None
    uom_id: str = Field(min_length=1)
    uom_name: str | None = None
    min_qty: float | int | str | None = 0
    base_price: float | int | str | None = 0
    discount_type: str | None = "NONE"
    discount_value: float | int | str | None = 0
    lead_time_days: int | str | None = 0
    tolerance_mode: str | None = "USE_CONTRACT_DEFAULT"
    tolerance_pct: float | int | str | None = 0
    effective_start: str | None = None
    effective_end: str | None = None


class PriceChangeIn(BaseModel):
    base_price: float | int | str | None = 0
    discount_type: str | None = "NONE"
    discount_value: float | int | str | None = 0
    effective_date: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


def install(server):
    app = server.app
    db_ref = server

    # --- register permissions ---
    try:
        for p in NEW_PERMISSIONS:
            if p not in server.ALL_PERMISSIONS:
                server.ALL_PERMISSIONS.append(p)
        rd = server.ROLE_DEFAULTS
        for role in ("admin", "director"):
            for p in NEW_PERMISSIONS:
                if p not in rd.get(role, []):
                    rd.setdefault(role, []).append(p)
        # Procurement Manager / Head: boleh manage + activate + ubah harga.
        for p in NEW_PERMISSIONS:
            if p not in rd.get("manager", []):
                rd.setdefault("manager", []).append(p)
        # Buyer / Purchasing: hanya view (tidak boleh ubah master harga/aktivasi).
        if PERM_VC_VIEW not in rd.get("purchasing", []):
            rd.setdefault("purchasing", []).append(PERM_VC_VIEW)
    except Exception as exc:  # pragma: no cover
        server.logger.warning(f"Vendor Contract permission registration: {exc}")

    def _db():
        return db_ref.db

    def _require(user, perm):
        server.require(user, perm)

    # --------------------------------------------------- helpers
    def _derived_status(c: dict) -> str:
        st = (c.get("status") or "draft")
        if st == "active" and c.get("end_date") and str(c["end_date"]) < _today():
            return "expired"
        return st

    async def _supplier(supplier_id: str):
        return await _db().suppliers.find_one({"id": supplier_id}, {"_id": 0, "id": 1, "name": 1, "code": 1})

    def _item_net(it: dict) -> dict:
        it["net_price"] = compute_net_price(it.get("base_price"), it.get("discount_type"), it.get("discount_value"))
        return it

    def _effective_tolerance(contract: dict, it: dict) -> float:
        mode = (it.get("tolerance_mode") or "USE_CONTRACT_DEFAULT").upper()
        if mode == "CUSTOM":
            return float(it.get("tolerance_pct") or 0)
        return float(contract.get("default_tolerance_pct") or 0)

    async def _items(contract_id: str):
        rows = await _db().vendor_contract_items.find({"contract_id": contract_id}, {"_id": 0}).sort("created_at", 1).to_list(2000)
        return rows

    async def _enrich(c: dict, *, with_children=True) -> dict:
        out = {**c, "derived_status": _derived_status(c)}
        if with_children:
            items = await _items(c["id"])
            for it in items:
                it["effective_tolerance_pct"] = _effective_tolerance(c, it)
            docs = await _db().vendor_contract_documents.find({"contract_id": c["id"]}, {"_id": 0}).sort("uploaded_at", -1).to_list(500)
            history = await _db().vendor_contract_price_history.find({"contract_id": c["id"]}, {"_id": 0}).sort("at", -1).to_list(2000)
            out["items"] = items
            out["item_count"] = len(items)
            out["documents"] = docs
            out["document_count"] = len(docs)
            out["price_history"] = history
        return out

    def _validate_header(body: ContractIn):
        number = (body.contract_number or "").strip()
        if not number:
            raise HTTPException(status_code=400, detail="Nomor Kontrak wajib diisi")
        if not (body.supplier_id or "").strip():
            raise HTTPException(status_code=400, detail="Vendor wajib dipilih")
        if not body.start_date or not body.end_date:
            raise HTTPException(status_code=400, detail="Tanggal Mulai dan Tanggal Berakhir wajib diisi")
        if str(body.end_date) < str(body.start_date):
            raise HTTPException(status_code=400, detail="Tanggal Berakhir tidak boleh sebelum Tanggal Mulai")
        tol = _pct(body.default_tolerance_pct, "Default Price Tolerance")
        return {
            "contract_number": number,
            "supplier_id": body.supplier_id.strip(),
            "supplier_name": (body.supplier_name or "").strip() or None,
            "contract_date": body.contract_date or None,
            "start_date": str(body.start_date), "end_date": str(body.end_date),
            "currency": (body.currency or "IDR").strip().upper(),
            "contract_type": (body.contract_type or "").strip() or None,
            "vendor_pic": (body.vendor_pic or "").strip() or None,
            "payment_term": (body.payment_term or "").strip() or None,
            "default_tolerance_pct": tol,
            "notes": (body.notes or "").strip() or None,
        }

    async def _validate_item(contract: dict, body: ItemIn, *, exclude_row_id=None):
        if not (body.item_id or "").strip():
            raise HTTPException(status_code=400, detail="Barang/Jasa wajib dipilih")
        if not (body.uom_id or "").strip():
            raise HTTPException(status_code=400, detail="UOM wajib dipilih")
        dtype = (body.discount_type or "NONE").upper()
        if dtype not in DISCOUNT_TYPES:
            raise HTTPException(status_code=400, detail="Tipe diskon tidak valid")
        tmode = (body.tolerance_mode or "USE_CONTRACT_DEFAULT").upper()
        if tmode not in TOLERANCE_MODES:
            raise HTTPException(status_code=400, detail="Mode tolerance tidak valid")
        base = _money(body.base_price, "Base Price")
        # min_qty numeric non-negative
        try:
            minq = float(body.min_qty or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Minimum Qty harus berupa angka")
        if minq < 0:
            raise HTTPException(status_code=400, detail="Minimum Qty tidak boleh negatif")
        try:
            lead = int(float(body.lead_time_days or 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Lead time harus berupa angka")
        dval = body.discount_value
        if dtype == "PERCENT":
            dval = _pct(body.discount_value, "Diskon persen")
        elif dtype == "AMOUNT":
            dval = _money(body.discount_value, "Diskon nominal")
        else:
            dval = 0
        net = compute_net_price(base, dtype, dval)
        tol = _pct(body.tolerance_pct, "Price Tolerance") if tmode == "CUSTOM" else 0.0
        if body.effective_start and body.effective_end and str(body.effective_end) < str(body.effective_start):
            raise HTTPException(status_code=400, detail="Effective End tidak boleh sebelum Effective Start")

        # resolve item/uom name from master (fallback ke input)
        item_doc = await _db().items.find_one({"id": body.item_id}, {"_id": 0, "id": 1, "name": 1, "code": 1})
        uom_doc = await _db().uoms.find_one({"id": body.uom_id}, {"_id": 0, "id": 1, "name": 1, "symbol": 1})
        item_name = (body.item_name or (item_doc or {}).get("name") or "").strip() or None
        item_code = (body.item_code or (item_doc or {}).get("code") or "").strip() or None
        uom_name = (body.uom_name or (uom_doc or {}).get("name") or (uom_doc or {}).get("symbol") or "").strip() or None

        # duplicate Item+UOM dengan periode overlap dalam kontrak yang sama -> ditolak
        s_new, e_new = _period(body.effective_start, body.effective_end, contract.get("start_date"), contract.get("end_date"))
        existing = await _db().vendor_contract_items.find(
            {"contract_id": contract["id"], "item_id": body.item_id, "uom_id": body.uom_id}, {"_id": 0}).to_list(500)
        for ex in existing:
            if exclude_row_id and ex.get("id") == exclude_row_id:
                continue
            s_ex, e_ex = _period(ex.get("effective_start"), ex.get("effective_end"), contract.get("start_date"), contract.get("end_date"))
            if _overlaps(s_new, e_new, s_ex, e_ex):
                raise HTTPException(status_code=400, detail="Item + UOM sudah ada dengan periode efektif yang tumpang tindih pada kontrak ini")

        return {
            "item_id": body.item_id.strip(), "item_code": item_code, "item_name": item_name,
            "uom_id": body.uom_id.strip(), "uom_name": uom_name,
            "min_qty": minq, "base_price": base,
            "discount_type": dtype, "discount_value": dval, "net_price": net,
            "lead_time_days": lead,
            "tolerance_mode": tmode, "tolerance_pct": tol,
            "effective_start": body.effective_start or None, "effective_end": body.effective_end or None,
            "status": "active",
        }

    async def _check_activation_overlap(contract: dict):
        """Blokir aktivasi bila ada kontrak ACTIVE lain dengan Vendor+Item+UOM periode overlap."""
        items = await _items(contract["id"])
        if not items:
            raise HTTPException(status_code=400, detail="Kontrak tanpa item tidak dapat diaktifkan")
        conflicts = []
        for it in items:
            s_new, e_new = _period(it.get("effective_start"), it.get("effective_end"), contract.get("start_date"), contract.get("end_date"))
            others = await _db().vendor_contract_items.find(
                {"supplier_id": contract["supplier_id"], "item_id": it["item_id"], "uom_id": it["uom_id"]},
                {"_id": 0}).to_list(2000)
            for ot in others:
                if ot.get("contract_id") == contract["id"]:
                    continue
                oc = await _db().vendor_contracts.find_one({"id": ot.get("contract_id")}, {"_id": 0})
                if not oc or oc.get("status") != "active":
                    continue
                # kontrak active yang sudah expired (lewat tanggal) tidak dianggap konflik untuk periode baru
                s_ex, e_ex = _period(ot.get("effective_start"), ot.get("effective_end"), oc.get("start_date"), oc.get("end_date"))
                if _overlaps(s_new, e_new, s_ex, e_ex):
                    conflicts.append({
                        "contract_id": oc["id"], "contract_number": oc.get("contract_number"),
                        "item_name": it.get("item_name"), "uom_name": it.get("uom_name"),
                        "effective_start": s_ex, "effective_end": e_ex,
                    })
        return conflicts

    # ------------------------------------------------- Effective Price Resolver (reusable)
    async def resolve_price(supplier_id: str, item_id: str, uom_id: str, txn_date: str | None = None, qty: float | None = None):
        """Cari harga kontrak AKTIF yang berlaku untuk Vendor+Item+UOM pada tanggal transaksi.

        Mengabaikan kontrak draft/cancelled dan harga expired (lewat tanggal).
        Menghormati min_qty (tier) bila qty diberikan. Dipakai CP4 untuk PO (belum di-wire).
        """
        d = txn_date or _today()
        rows = await _db().vendor_contract_items.find(
            {"supplier_id": supplier_id, "item_id": item_id, "uom_id": uom_id}, {"_id": 0}).to_list(2000)
        candidates = []
        for it in rows:
            oc = await _db().vendor_contracts.find_one({"id": it.get("contract_id")}, {"_id": 0})
            if not oc or oc.get("status") != "active":
                continue
            s_ex, e_ex = _period(it.get("effective_start"), it.get("effective_end"), oc.get("start_date"), oc.get("end_date"))
            if not (str(s_ex) <= str(d) <= str(e_ex)):
                continue  # di luar periode / expired
            minq = float(it.get("min_qty") or 0)
            if qty is not None and float(qty) < minq:
                continue  # belum memenuhi minimum qty tier ini
            candidates.append((oc, it, minq))
        if not candidates:
            return None
        # pilih tier min_qty tertinggi yang <= qty; tie-break: contract_date terbaru
        candidates.sort(key=lambda c: (c[2], str(c[0].get("contract_date") or ""), str(c[0].get("created_at") or "")), reverse=True)
        oc, it, _minq = candidates[0]
        return {
            "contract_id": oc["id"], "contract_number": oc.get("contract_number"),
            "supplier_id": supplier_id, "supplier_name": oc.get("supplier_name"),
            "currency": oc.get("currency"),
            "item_id": item_id, "item_name": it.get("item_name"), "item_code": it.get("item_code"),
            "uom_id": uom_id, "uom_name": it.get("uom_name"),
            "min_qty": it.get("min_qty"),
            "base_price": int(it.get("base_price") or 0),
            "net_contract_price": int(it.get("net_price") or 0),
            "discount_type": it.get("discount_type"), "discount_value": it.get("discount_value"),
            "tolerance_pct": _effective_tolerance(oc, it),
            "effective_start": it.get("effective_start") or oc.get("start_date"),
            "effective_end": it.get("effective_end") or oc.get("end_date"),
            "lead_time_days": it.get("lead_time_days"),
            "resolved_for_date": d,
        }

    async def period_hint(supplier_id: str, item_id: str, uom_id: str, txn_date: str | None = None):
        """Contract Period Guard: when resolve_price finds NO active price for the date, detect
        whether an ACTIVE contract for this Vendor+Item+UOM actually EXISTS but the PO date falls
        OUTSIDE its effective period. Returns a non-blocking hint (never raises); None otherwise."""
        d = str(txn_date or _today())
        rows = await _db().vendor_contract_items.find(
            {"supplier_id": supplier_id, "item_id": item_id, "uom_id": uom_id}, {"_id": 0}).to_list(2000)
        best = None
        for it in rows:
            oc = await _db().vendor_contracts.find_one({"id": it.get("contract_id")}, {"_id": 0})
            if not oc or oc.get("status") != "active":
                continue
            s_ex, e_ex = _period(it.get("effective_start"), it.get("effective_end"), oc.get("start_date"), oc.get("end_date"))
            if str(s_ex) <= d <= str(e_ex):
                continue  # masih berlaku -> bukan near-miss (akan di-handle resolve_price)
            position = "before" if d < str(s_ex) else "after"
            cand = {"out_of_period": True, "contract_number": oc.get("contract_number"),
                    "effective_start": s_ex, "effective_end": e_ex, "position": position,
                    "net_contract_price": int(it.get("net_price") or 0)}
            # Prefer the contract whose window ends latest (most relevant / most recently expired).
            if best is None or str(e_ex) > str(best["effective_end"]):
                best = cand
        return best

    # ekspos untuk CP4
    server.resolve_vendor_contract_price = resolve_price
    server.resolve_contract_period_hint = period_hint

    # ============================ CONTRACT CRUD ============================
    @app.get("/api/vendor-contracts", tags=["vendor_contract"])
    async def list_contracts(q: str = "", supplier_id: str = "", status: str = "", currency: str = "",
                             period_start: str = "", period_end: str = "", sort: str = "-created_at",
                             page: int = 1, page_size: int = 20, user=Depends(server.current_user)):
        _require(user, PERM_VC_VIEW)
        flt = {}
        if supplier_id:
            flt["supplier_id"] = supplier_id
        if currency:
            flt["currency"] = currency.upper()
        rows = await _db().vendor_contracts.find(flt, {"_id": 0}).to_list(100000)
        # counts
        for r in rows:
            r["derived_status"] = _derived_status(r)
            r["item_count"] = await _db().vendor_contract_items.count_documents({"contract_id": r["id"]})
        if status:
            rows = [r for r in rows if r["derived_status"] == status]
        if period_start:
            rows = [r for r in rows if str(r.get("end_date") or "") >= period_start]
        if period_end:
            rows = [r for r in rows if str(r.get("start_date") or "") <= period_end]
        if q:
            ql = q.strip().lower()
            rows = [r for r in rows if any(ql in str(r.get(k) or "").lower()
                    for k in ("contract_number", "supplier_name", "contract_type", "vendor_pic"))]
        reverse = sort.startswith("-")
        key = sort.lstrip("-") or "created_at"
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=reverse)
        total = len(rows)
        page = max(1, int(page)); page_size = min(200, max(1, int(page_size)))
        start = (page - 1) * page_size
        items = rows[start:start + page_size]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "can_manage": server.has_perm(user, PERM_VC_MANAGE),
                "can_activate": server.has_perm(user, PERM_VC_ACTIVATE)}

    @app.get("/api/vendor-contracts/resolve-price", tags=["vendor_contract"])
    async def resolve_price_endpoint(vendor_id: str, item_id: str, uom_id: str, date: str = "",
                                     qty: float | None = None, user=Depends(server.current_user)):
        _require(user, PERM_VC_VIEW)
        result = await resolve_price(vendor_id, item_id, uom_id, date or None, qty)
        if not result:
            return {"found": False, "detail": "Tidak ada harga kontrak aktif yang berlaku untuk kombinasi ini pada tanggal tersebut."}
        return {"found": True, **result}

    @app.post("/api/vendor-contracts", tags=["vendor_contract"])
    async def create_contract(body: ContractIn, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        data = _validate_header(body)
        sup = await _supplier(data["supplier_id"])
        if not sup:
            raise HTTPException(status_code=400, detail="Vendor tidak ditemukan pada master supplier")
        data["supplier_name"] = sup.get("name")
        # unik per tenant + vendor
        dup = await _db().vendor_contracts.find_one(
            {"contract_number": data["contract_number"], "supplier_id": data["supplier_id"]}, {"_id": 0, "id": 1})
        if dup:
            raise HTTPException(status_code=409, detail=f"Nomor Kontrak '{data['contract_number']}' sudah digunakan untuk vendor ini")
        cid = str(uuid.uuid4())
        now = _now()
        doc = {"id": cid, **data, "status": "draft",
               "created_by": user.get("email"), "created_at": now,
               "updated_by": user.get("email"), "updated_at": now,
               "activated_by": None, "activated_at": None, "cancelled_by": None, "cancelled_at": None}
        await _db().vendor_contracts.insert_one(doc)
        await server.audit(user, "create", "vendor_contract", cid, doc["contract_number"],
                           after={"supplier": data["supplier_name"], "period": f"{data['start_date']}..{data['end_date']}"})
        clean = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        return await _enrich(clean)

    @app.get("/api/vendor-contracts/{cid}", tags=["vendor_contract"])
    async def get_contract(cid: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_VIEW)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        result = await _enrich(c)
        result["can_manage"] = server.has_perm(user, PERM_VC_MANAGE)
        result["can_activate"] = server.has_perm(user, PERM_VC_ACTIVATE)
        result["can_manage_price"] = server.has_perm(user, PERM_VC_PRICE_MANAGE)
        return result

    @app.put("/api/vendor-contracts/{cid}", tags=["vendor_contract"])
    async def update_contract(cid: str, body: ContractIn, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        existing = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if existing.get("status") != "draft":
            raise HTTPException(status_code=409, detail="Hanya kontrak Draft yang dapat diedit. Gunakan Perubahan Harga resmi untuk kontrak aktif.")
        data = _validate_header(body)
        sup = await _supplier(data["supplier_id"])
        if not sup:
            raise HTTPException(status_code=400, detail="Vendor tidak ditemukan pada master supplier")
        data["supplier_name"] = sup.get("name")
        if data["contract_number"] != existing.get("contract_number") or data["supplier_id"] != existing.get("supplier_id"):
            dup = await _db().vendor_contracts.find_one(
                {"contract_number": data["contract_number"], "supplier_id": data["supplier_id"], "id": {"$ne": cid}}, {"_id": 0, "id": 1})
            if dup:
                raise HTTPException(status_code=409, detail=f"Nomor Kontrak '{data['contract_number']}' sudah digunakan untuk vendor ini")
        data["updated_by"] = user.get("email"); data["updated_at"] = _now()
        await _db().vendor_contracts.update_one({"id": cid}, {"$set": data})
        # jika vendor berubah, sinkronkan supplier_id pada item (masih draft)
        if data["supplier_id"] != existing.get("supplier_id"):
            await _db().vendor_contract_items.update_many({"contract_id": cid}, {"$set": {"supplier_id": data["supplier_id"]}})
        await server.audit(user, "edit", "vendor_contract", cid, data["contract_number"],
                           before={"period": f"{existing.get('start_date')}..{existing.get('end_date')}"},
                           after={"period": f"{data['start_date']}..{data['end_date']}"})
        updated = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        return await _enrich(updated)

    @app.post("/api/vendor-contracts/{cid}/activate", tags=["vendor_contract"])
    async def activate_contract(cid: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_ACTIVATE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if c.get("status") == "cancelled":
            raise HTTPException(status_code=409, detail="Kontrak yang dibatalkan tidak dapat diaktifkan")
        if c.get("status") == "active":
            raise HTTPException(status_code=409, detail="Kontrak sudah aktif")
        conflicts = await _check_activation_overlap(c)
        if conflicts:
            raise HTTPException(status_code=409, detail={
                "message": "Aktivasi ditolak: terdapat harga Active lain dengan periode tumpang tindih (Vendor+Item+UOM).",
                "conflicts": conflicts,
            })
        now = _now()
        await _db().vendor_contracts.update_one({"id": cid}, {"$set": {
            "status": "active", "activated_by": user.get("email"), "activated_at": now, "updated_by": user.get("email"), "updated_at": now}})
        await server.audit(user, "approve", "vendor_contract", cid, c.get("contract_number"), after={"status": "active"})
        updated = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        return await _enrich(updated)

    @app.post("/api/vendor-contracts/{cid}/cancel", tags=["vendor_contract"])
    async def cancel_contract(cid: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if c.get("status") == "cancelled":
            raise HTTPException(status_code=409, detail="Kontrak sudah dibatalkan")
        await _db().vendor_contracts.update_one({"id": cid}, {"$set": {
            "status": "cancelled", "cancelled_by": user.get("email"), "cancelled_at": _now(), "updated_by": user.get("email"), "updated_at": _now()}})
        await server.audit(user, "cancel", "vendor_contract", cid, c.get("contract_number"), after={"status": "cancelled"})
        updated = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        return await _enrich(updated)

    # ============================ CONTRACT ITEMS ============================
    @app.post("/api/vendor-contracts/{cid}/items", tags=["vendor_contract"])
    async def add_item(cid: str, body: ItemIn, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if c.get("status") != "draft":
            raise HTTPException(status_code=409, detail="Item hanya dapat ditambah pada kontrak Draft")
        data = await _validate_item(c, body)
        rid = str(uuid.uuid4())
        now = _now()
        doc = {"id": rid, "contract_id": cid, "supplier_id": c["supplier_id"], **data,
               "created_by": user.get("email"), "created_at": now, "updated_by": user.get("email"), "updated_at": now}
        await _db().vendor_contract_items.insert_one(doc)
        await server.audit(user, "create", "vendor_contract_item", rid, c.get("contract_number"),
                           after={"item": data["item_name"], "uom": data["uom_name"], "base_price": data["base_price"], "net_price": data["net_price"]})
        return await _db().vendor_contract_items.find_one({"id": rid}, {"_id": 0})

    @app.put("/api/vendor-contracts/{cid}/items/{rid}", tags=["vendor_contract"])
    async def edit_item(cid: str, rid: str, body: ItemIn, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if c.get("status") != "draft":
            raise HTTPException(status_code=409, detail="Edit item hanya pada kontrak Draft. Gunakan Perubahan Harga resmi untuk kontrak aktif.")
        row = await _db().vendor_contract_items.find_one({"id": rid, "contract_id": cid}, {"_id": 0})
        if not row:
            raise HTTPException(status_code=404, detail="Item tidak ditemukan")
        data = await _validate_item(c, body, exclude_row_id=rid)
        data["updated_by"] = user.get("email"); data["updated_at"] = _now()
        await _db().vendor_contract_items.update_one({"id": rid}, {"$set": data})
        await server.audit(user, "edit", "vendor_contract_item", rid, c.get("contract_number"),
                           before={"base_price": row.get("base_price"), "net_price": row.get("net_price")},
                           after={"base_price": data["base_price"], "net_price": data["net_price"]})
        return await _db().vendor_contract_items.find_one({"id": rid}, {"_id": 0})

    @app.delete("/api/vendor-contracts/{cid}/items/{rid}", tags=["vendor_contract"])
    async def delete_item(cid: str, rid: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if c.get("status") != "draft":
            raise HTTPException(status_code=409, detail="Hapus item hanya pada kontrak Draft")
        row = await _db().vendor_contract_items.find_one({"id": rid, "contract_id": cid}, {"_id": 0})
        if not row:
            raise HTTPException(status_code=404, detail="Item tidak ditemukan")
        await _db().vendor_contract_items.delete_one({"id": rid, "contract_id": cid})
        await server.audit(user, "delete", "vendor_contract_item", rid, c.get("contract_number"), before={"item": row.get("item_name")})
        return {"ok": True}

    # ============================ OFFICIAL PRICE CHANGE (active) ============================
    @app.post("/api/vendor-contracts/{cid}/items/{rid}/price-change", tags=["vendor_contract"])
    async def price_change(cid: str, rid: str, body: PriceChangeIn, user=Depends(server.current_user)):
        _require(user, PERM_VC_PRICE_MANAGE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        if c.get("status") != "active":
            raise HTTPException(status_code=409, detail="Perubahan harga resmi hanya untuk kontrak Active")
        row = await _db().vendor_contract_items.find_one({"id": rid, "contract_id": cid}, {"_id": 0})
        if not row:
            raise HTTPException(status_code=404, detail="Item tidak ditemukan")
        dtype = (body.discount_type or "NONE").upper()
        if dtype not in DISCOUNT_TYPES:
            raise HTTPException(status_code=400, detail="Tipe diskon tidak valid")
        base = _money(body.base_price, "Base Price")
        if dtype == "PERCENT":
            dval = _pct(body.discount_value, "Diskon persen")
        elif dtype == "AMOUNT":
            dval = _money(body.discount_value, "Diskon nominal")
        else:
            dval = 0
        new_net = compute_net_price(base, dtype, dval)
        prev_base = int(row.get("base_price") or 0)
        prev_net = int(row.get("net_price") or 0)
        change_pct = round(((new_net - prev_net) / prev_net) * 100, 2) if prev_net else None
        now = _now()
        hist = {
            "id": str(uuid.uuid4()), "contract_id": cid, "item_row_id": rid,
            "item_id": row.get("item_id"), "item_name": row.get("item_name"), "uom_name": row.get("uom_name"),
            "previous_base_price": prev_base, "new_base_price": base,
            "previous_net_price": prev_net, "new_net_price": new_net,
            "change_pct": change_pct, "effective_date": str(body.effective_date),
            "reason": body.reason.strip(), "actor": user.get("email"), "actor_name": user.get("name"),
            "at": now,
        }
        await _db().vendor_contract_price_history.insert_one(hist)
        await _db().vendor_contract_items.update_one({"id": rid}, {"$set": {
            "base_price": base, "discount_type": dtype, "discount_value": dval, "net_price": new_net,
            "effective_start": str(body.effective_date), "updated_by": user.get("email"), "updated_at": now}})
        await server.audit(user, "edit", "vendor_contract_price", rid, c.get("contract_number"),
                           before={"base_price": prev_base, "net_price": prev_net},
                           after={"base_price": base, "net_price": new_net, "effective_date": str(body.effective_date), "reason": body.reason.strip()})
        return {k: v for k, v in hist.items() if k != "_id"}

    @app.get("/api/vendor-contracts/{cid}/price-history", tags=["vendor_contract"])
    async def price_history(cid: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_VIEW)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0, "id": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        return await _db().vendor_contract_price_history.find({"contract_id": cid}, {"_id": 0}).sort("at", -1).to_list(2000)

    # ============================ DOCUMENTS ============================
    def _resolve_ext(file: UploadFile):
        ctype = (file.content_type or "").lower()
        ext = DOC_TYPES.get(ctype)
        if not ext:
            fname = (file.filename or "").lower()
            for e in ("pdf", "png", "webp", "jpg", "jpeg"):
                if fname.endswith("." + e):
                    ext = "jpg" if e == "jpeg" else e
                    ctype = {"pdf": "application/pdf", "png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}[ext]
                    break
        return ext, ctype

    @app.get("/api/vendor-contracts/{cid}/documents", tags=["vendor_contract"])
    async def list_docs(cid: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_VIEW)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0, "id": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        return await _db().vendor_contract_documents.find({"contract_id": cid}, {"_id": 0}).sort("uploaded_at", -1).to_list(500)

    @app.post("/api/vendor-contracts/{cid}/documents", tags=["vendor_contract"])
    async def upload_doc(cid: str, file: UploadFile = File(...), user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        c = await _db().vendor_contracts.find_one({"id": cid}, {"_id": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Kontrak tidak ditemukan")
        ext, ctype = _resolve_ext(file)
        if not ext:
            raise HTTPException(status_code=400, detail="Tipe file tidak didukung. Gunakan PDF, JPG, PNG, atau WEBP")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="File kosong")
        if len(data) > MAX_DOC_SIZE:
            raise HTTPException(status_code=400, detail="Ukuran file maksimal 10 MB")
        object_key = f"{S.APP_NAME}/{VC_DOC_SEGMENT}/{cid}/{uuid.uuid4().hex}.{ext}"
        result = S.put_object(object_key, data, ctype)
        doc = {"id": str(uuid.uuid4()), "contract_id": cid,
               "object_key": result.get("path", object_key), "file_name": (file.filename or f"dokumen.{ext}"),
               "mime_type": ctype, "file_size": result.get("size", len(data)),
               "uploaded_by": user.get("email"), "uploaded_at": _now()}
        await _db().vendor_contract_documents.insert_one(doc)
        await server.audit(user, "upload_attachment", "vendor_contract", cid, c.get("contract_number"), after={"file_name": doc["file_name"]})
        return {k: v for k, v in doc.items() if k != "_id"}

    @app.get("/api/vendor-contracts/{cid}/documents/{doc_id}/download", tags=["vendor_contract"])
    async def download_doc(cid: str, doc_id: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_VIEW)
        doc = await _db().vendor_contract_documents.find_one({"id": doc_id, "contract_id": cid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        try:
            data, ctype = S.get_object(doc["object_key"])
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File tidak ditemukan")
        return Response(content=data, media_type=doc.get("mime_type") or ctype or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="{doc.get("file_name","dokumen")}"'})

    @app.delete("/api/vendor-contracts/{cid}/documents/{doc_id}", tags=["vendor_contract"])
    async def delete_doc(cid: str, doc_id: str, user=Depends(server.current_user)):
        _require(user, PERM_VC_MANAGE)
        doc = await _db().vendor_contract_documents.find_one({"id": doc_id, "contract_id": cid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan")
        await _db().vendor_contract_documents.delete_one({"id": doc_id, "contract_id": cid})
        await server.audit(user, "delete", "vendor_contract", cid, doc.get("file_name"))
        return {"ok": True}

    server.logger.info("CP3 Vendor Contract Price layer installed")
