"""DP Supplier — realisasi pembayaran uang muka supplier dari PO + alokasi DP ke Invoice Vendor.

Sumber kebenaran nilai DP adalah PO (`dp_enabled`, `dp_type`, `dp_value`, `dp_amount`). Finance tidak
menginput ulang nilai DP; Finance hanya mencatat realisasi (tanggal, sumber dana, referensi, bukti)
lalu Approve. Tidak membuat jurnal, tidak mengubah Kas/Bank, stok, HPP, Moving Average, commitment.

Collections (tenant-scoped otomatis oleh TenantDatabaseProxy, tabel dibuat otomatis):
- supplier_dp_payments          : realisasi DP (Draft -> Approved | Draft -> Cancelled; soft cancel)
- supplier_dp_keys               : PK strict "sdp-<po_id>" = maksimal 1 pembayaran aktif (Draft/Approved) per PO
- vendor_invoice_dp_allocations  : pemakaian DP per Invoice Vendor per PO
Urutan: Tenant (proxy) -> Permission (access hook + cek di endpoint) -> Cakupan Divisi PO -> Business Rule.
Concurrency: MariaDB named lock `pfdp:<po_id>` (pool lock existing ro_source_lock) + recheck di dalam lock.
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile

import division_visibility_layer as Division
import doc_procurement as DPM
import mariadb_motor
import ro_source_lock as RS
import storage as S
import transaction_mutation_layer as TM
from attachment_integrity_guard_layer import _validate_file

log = logging.getLogger("procureflow")

EPS = 0.005
VALID_PO = ("Approved", "Partially Received", "Fully Received")
ST_DRAFT, ST_APPROVED, ST_CANCELLED = "Draft", "Approved", "Cancelled"
LABEL = {ST_DRAFT: "Menunggu Verifikasi", ST_APPROVED: "Sudah Dibayar", ST_CANCELLED: "Dibatalkan"}
ATT_ENTITY = "supplier_dp_payment"
AUDIT_ENTITY = "supplier_dp"
LOCK_PREFIX = "pfdp:"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MSG_PO_CANCEL = "PO memiliki DP yang sudah dibayar. Selesaikan/reversal uang muka terlebih dahulu."
MSG_PO_EDIT = ("PO memiliki DP yang sudah dibayar. Perubahan yang memengaruhi nilai PO, DP, supplier, atau divisi "
               "tidak dapat dilakukan. Fitur reversal/revisi DP belum tersedia.")
MSG_NOT_FOUND = "DP Supplier tidak ditemukan atau tidak dapat diakses."
MSG_DP_PAID_CANCEL = "DP sudah dibayar dan tidak dapat dibatalkan. Fitur reversal/pengembalian DP belum tersedia."
_FALLBACK = asyncio.Lock()
mariadb_motor.STRICT_PK_COLLECTIONS.add("supplier_dp_keys")


def rp(v):
    return f"Rp {float(v or 0):,.0f}".replace(",", ".")


def r2(v):
    return round(float(v or 0) + 0.0, 2)


def today():
    return datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()


def key_id(po_id):
    return f"sdp-{po_id}"


def po_eligible(po):
    return bool(po) and po.get("status") in VALID_PO and po.get("cancelled") is not True and po.get("dp_enabled") is True \
        and float(po.get("dp_amount") or 0) > EPS


def dp_terms(po):
    if not po or not po.get("dp_enabled"):
        return "-"
    if po.get("dp_type") == "percentage":
        v = float(po.get("dp_value") or 0)
        return f"{('%g' % v).replace('.', ',')}% dari Grand Total"
    return "Nominal"


@asynccontextmanager
async def dp_locks(server, po_ids):
    """Named lock lintas proses per PO (pfdp:<po_id>), terurut -> bebas deadlock. Fallback asyncio (1 proses)."""
    names = RS.lock_names(po_ids, LOCK_PREFIX)
    if not names:
        yield
        return
    dsn = RS._dsn_of(server)
    if not dsn:
        async with _FALLBACK:
            yield
        return
    pool = await RS._lock_pool(dsn)
    conn = await pool.acquire()
    try:
        async with conn.cursor() as cur:
            for name in names:
                await cur.execute("SELECT GET_LOCK(%s, %s)", (name, RS.LOCK_TIMEOUT_S))
                got = (await cur.fetchone() or [None])[0]
                if got != 1:
                    raise HTTPException(409, "DP Supplier sedang diproses transaksi lain. Silakan coba lagi.")
        yield
    finally:
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT RELEASE_ALL_LOCKS()")
            pool.release(conn)
        except Exception as exc:  # noqa: BLE001 - koneksi rusak -> server melepas kunci otomatis
            log.warning(f"Supplier DP lock release: {exc}")
            conn.close()
            pool.release(conn)


# ====================================================================== helpers dipakai Invoice Vendor
async def approved_payments(server, po_ids):
    if not po_ids:
        return {}
    rows = await server.db.supplier_dp_payments.find({"po_id": {"$in": list(po_ids)}, "status": ST_APPROVED}, {"_id": 0}).to_list(10000)
    return {r["po_id"]: r for r in rows}


async def used_by_payment(server, pay_ids, exclude_invoice=None):
    if not pay_ids:
        return {}
    rows = await server.db.vendor_invoice_dp_allocations.find({"dp_payment_id": {"$in": list(pay_ids)}}, {"_id": 0}).to_list(100000)
    out = {}
    for a in rows:
        if exclude_invoice and a.get("invoice_id") == exclude_invoice:
            continue
        out[a["dp_payment_id"]] = r2(out.get(a["dp_payment_id"], 0) + float(a.get("amount") or 0))
    return out


async def po_portions(server, do_allocs):
    """Nilai bagian Invoice per PO = alokasi DO x porsi nilai komersial PO line di DO tsb (rumus do_values existing)."""
    ids = [a["do_id"] for a in do_allocs if a.get("do_id")]
    if not ids:
        return {}
    lines = await server.db.do_lines.find({"do_id": {"$in": ids}}, {"_id": 0, "do_id": 1, "po_id": 1, "po_line_id": 1, "qty": 1}).to_list(100000)
    pl_ids = list({ln["po_line_id"] for ln in lines if ln.get("po_line_id")})
    pls = {p["id"]: p for p in await server.db.po_lines.find({"id": {"$in": pl_ids}}, {"_id": 0, "id": 1, "qty": 1, "total": 1, "po_id": 1}).to_list(len(pl_ids) + 5)} if pl_ids else {}
    per = {}
    for ln in lines:
        p = pls.get(ln.get("po_line_id"))
        if not p or not float(p.get("qty") or 0):
            continue
        po_id = ln.get("po_id") or p.get("po_id")
        if not po_id:
            continue
        v = float(p.get("total") or 0) * float(ln.get("qty") or 0) / float(p["qty"])
        m = per.setdefault(ln["do_id"], {})
        m[po_id] = m.get(po_id, 0.0) + v
    out = {}
    for a in do_allocs:
        m = per.get(a.get("do_id")) or {}
        total = sum(m.values())
        if total <= EPS:
            continue
        for po_id, v in m.items():
            out[po_id] = out.get(po_id, 0.0) + float(a.get("amount") or 0) * v / total
    return {k: r2(v) for k, v in out.items()}


def _install_state(server):
    return getattr(server, "_SUPPLIER_DP", None)


async def po_access(server, user, po):
    if not po:
        return False
    if server.is_global(user):
        return True
    if not Division._division_allowed(server, user, po.get("division_id")):
        return False
    return bool(await server.ACCESS_DOC_VISIBLE("po", po["id"], user))


async def invoice_dp_candidates(server, user, supplier_id, do_allocs, invoice_id=None):
    """DP Approved dari PO yang benar-benar menjadi sumber DO pada invoice, supplier sama, dalam cakupan user."""
    portions = await po_portions(server, do_allocs)
    current = {}
    if invoice_id:
        for a in await server.db.vendor_invoice_dp_allocations.find({"invoice_id": invoice_id}, {"_id": 0}).to_list(5000):
            current[a["po_id"]] = r2(current.get(a["po_id"], 0) + float(a.get("amount") or 0))
    po_ids = sorted(set(portions) | set(current))
    pays = await approved_payments(server, po_ids)
    used = await used_by_payment(server, [p["id"] for p in pays.values()], exclude_invoice=invoice_id)
    pos = {p["id"]: p for p in await server.db.po.find({"id": {"$in": list(pays)}}, {"_id": 0}).to_list(len(pays) + 5)} if pays else {}
    rows = []
    for po_id in po_ids:
        pay, po = pays.get(po_id), pos.get(po_id)
        if not pay or not po or pay.get("supplier_id") != supplier_id or po.get("supplier_id") != supplier_id:
            continue
        if not await po_access(server, user, po):
            continue
        paid = r2(pay.get("amount"))
        u = used.get(pay["id"], 0.0)
        avail = r2(max(0.0, paid - u))
        portion = portions.get(po_id, 0.0)
        cur = current.get(po_id, 0.0)
        if avail <= EPS and cur <= EPS:
            continue
        rows.append({"po_id": po_id, "po_no": po.get("no"), "po_date": po.get("date"), "dp_payment_id": pay["id"], "dp_no": pay.get("no"),
                     "invoice_portion": portion, "dp_paid": paid, "dp_used": u, "dp_available": avail,
                     "max_allocation": r2(min(avail, portion)), "suggested": r2(min(avail, portion)), "current_allocation": cur})
    return rows


async def validate_invoice_dp(server, user, supplier_id, do_allocs, raw, invoice_id, amount, paid):
    """Validasi ulang (backend = sumber kebenaran). Dipanggil DI DALAM dp_locks."""
    cands = {c["po_id"]: c for c in await invoice_dp_candidates(server, user, supplier_id, do_allocs, invoice_id)}
    rows, seen = [], set()
    for a in raw or []:
        po_id = str((a or {}).get("po_id") or "").strip()
        try:
            amt = round(float((a or {}).get("amount") or 0), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "Nilai alokasi DP tidak valid")
        if amt < 0:
            raise HTTPException(400, "Nilai alokasi DP tidak boleh negatif")
        if amt <= EPS:
            continue
        if po_id in seen:
            raise HTTPException(400, "DP PO yang sama tidak boleh dialokasikan dua kali dalam satu invoice")
        seen.add(po_id)
        c = cands.get(po_id)
        if not c:
            raise HTTPException(400, "DP tidak dapat dialokasikan: PO bukan sumber DO pada invoice ini, DP belum dibayar, "
                                     "supplier berbeda, atau di luar cakupan divisi Anda.")
        if amt > c["dp_available"] + EPS:
            raise HTTPException(409, f"Alokasi DP PO {c['po_no']} melebihi DP tersedia ({rp(c['dp_available'])}).")
        if amt > c["invoice_portion"] + EPS:
            raise HTTPException(409, f"Alokasi DP PO {c['po_no']} melebihi nilai bagian invoice PO tersebut ({rp(c['invoice_portion'])}).")
        rows.append({"po_id": po_id, "po_no": c["po_no"], "dp_payment_id": c["dp_payment_id"], "dp_no": c["dp_no"], "amount": amt})
    total = r2(sum(r["amount"] for r in rows))
    if total + float(paid or 0) > float(amount or 0) + EPS:
        raise HTTPException(409, f"Total DP dialokasikan ({rp(total)}) + pembayaran invoice ({rp(paid)}) melebihi Nilai Invoice ({rp(amount)}).")
    return rows, total


async def save_invoice_dp(server, iid, rows, user):
    await server.db.vendor_invoice_dp_allocations.delete_many({"invoice_id": iid})
    for r in rows:
        await server.db.vendor_invoice_dp_allocations.insert_one({
            "id": server.gid(), "invoice_id": iid, "dp_payment_id": r["dp_payment_id"], "po_id": r["po_id"], "amount": r["amount"],
            "created_by": user.get("email"), "created_by_name": user.get("name"), "created_at": server.now_iso()})


async def invoice_dp_rows(server, iid):
    return await server.db.vendor_invoice_dp_allocations.find({"invoice_id": iid}, {"_id": 0}).to_list(5000)


async def invoice_dp_total(server, iid):
    return r2(sum(float(a.get("amount") or 0) for a in await invoice_dp_rows(server, iid)))


async def invoice_dp_detail(server, iid):
    allocs = await invoice_dp_rows(server, iid)
    if not allocs:
        return []
    pay_ids = sorted({a["dp_payment_id"] for a in allocs})
    pays = {p["id"]: p for p in await server.db.supplier_dp_payments.find({"id": {"$in": pay_ids}}, {"_id": 0}).to_list(len(pay_ids) + 5)}
    used_all = await used_by_payment(server, pay_ids)
    pos = {p["id"]: p for p in await server.db.po.find({"id": {"$in": [a["po_id"] for a in allocs]}}, {"_id": 0, "id": 1, "no": 1}).to_list(len(allocs) + 5)}
    out = []
    for a in allocs:
        pay = pays.get(a["dp_payment_id"]) or {}
        paid, used = r2(pay.get("amount")), used_all.get(a["dp_payment_id"], 0.0)
        out.append({**a, "po_no": (pos.get(a["po_id"]) or {}).get("no"), "dp_no": pay.get("no"), "dp_paid": paid, "dp_used": used,
                    "dp_remaining": r2(paid - used)})
    return out


# ====================================================================== install
def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731
    cu = server.current_user

    def can(user, key):
        return user.get("role") == "admin" or key in set(user.get("effective_permissions") or [])

    def need(user, key, verb):
        if not can(user, key):
            raise HTTPException(403, f"Anda tidak memiliki izin untuk {verb} DP Supplier.")

    async def load_po(po_id, user):
        # Tidak ada / tenant lain / di luar cakupan divisi -> respons generik yang sama (tidak membocorkan keberadaan data).
        po = await db().po.find_one({"id": po_id}, {"_id": 0})
        if not po or not await po_access(server, user, po):
            raise HTTPException(404, MSG_NOT_FOUND)
        return po

    async def load_pay(pid, user):
        pay = await db().supplier_dp_payments.find_one({"id": pid}, {"_id": 0})
        if not pay:
            raise HTTPException(404, MSG_NOT_FOUND)
        po = await load_po(pay["po_id"], user)
        return pay, po

    def reject_amount(body, po):
        for k in ("amount", "dp_amount"):
            if k in (body or {}) and body[k] not in (None, ""):
                try:
                    v = float(body[k])
                except (TypeError, ValueError):
                    raise HTTPException(400, "Nilai DP mengikuti PO dan tidak dapat diubah.")
                if abs(v - float(po.get("dp_amount") or 0)) > EPS:
                    raise HTTPException(400, "Nilai DP mengikuti PO dan tidak dapat diubah.")

    def fields(body, cur=None):
        cur = cur or {}
        out = {}
        for k in ("payment_date", "fund_source", "reference", "notes"):
            if k in (body or {}):
                out[k] = str(body.get(k) or "").strip()
            else:
                out[k] = cur.get(k, "")
        if out["payment_date"]:
            out["payment_date"] = out["payment_date"][:10]
            if not DATE_RE.match(out["payment_date"]):
                raise HTTPException(400, "Tanggal Pembayaran tidak valid")
        out["fund_source"] = out["fund_source"][:200]
        out["reference"] = out["reference"][:200]
        out["notes"] = out["notes"][:2000]
        return out

    def require_eligible(po):
        if po.get("cancelled") is True or str(po.get("status") or "").lower() in ("cancelled", "canceled"):
            raise HTTPException(409, "PO sudah dibatalkan; DP tidak dapat diproses.")
        if po.get("status") not in VALID_PO:
            raise HTTPException(409, f"PO berstatus {po.get('status') or 'Draft'}; DP hanya dapat diproses untuk PO yang sudah Approved.")
        if not po.get("dp_enabled") or float(po.get("dp_amount") or 0) <= EPS:
            raise HTTPException(409, "PO ini tidak menggunakan DP.")

    async def proof_count(pid):
        return await db().attachments.count_documents({"entity": ATT_ENTITY, "entity_id": pid, "is_deleted": False})

    def snap(pay):
        return {k: pay.get(k) for k in ("no", "amount", "payment_date", "fund_source", "reference", "notes", "status")}

    async def names_of(coll, ids):
        ids = [i for i in ids if i]
        if not ids:
            return {}
        return {r["id"]: r.get("name") for r in await getattr(db(), coll).find({"id": {"$in": list(set(ids))}}, {"_id": 0, "id": 1, "name": 1}).to_list(len(ids) + 5)}

    def pay_out(p):
        return {**p, "status_label": LABEL.get(p.get("status"), p.get("status"))}

    async def row_of(po, pays, used, sups, divs):
        active = next((p for p in pays if p.get("status") == ST_APPROVED), None) or next((p for p in pays if p.get("status") == ST_DRAFT), None)
        paid = r2(active.get("amount")) if active and active.get("status") == ST_APPROVED else 0.0
        u = used.get(active["id"], 0.0) if active and active.get("status") == ST_APPROVED else 0.0
        status = ST_APPROVED if paid > EPS else ST_DRAFT
        return {"po_id": po["id"], "po_no": po.get("no"), "po_date": po.get("date"), "po_status": po.get("status"),
                "supplier_id": po.get("supplier_id"), "supplier_name": sups.get(po.get("supplier_id")),
                "division_id": po.get("division_id"), "division_name": divs.get(po.get("division_id")),
                "po_value": r2(po.get("grand_total")), "dp_type": po.get("dp_type"), "dp_value": po.get("dp_value"),
                "dp_terms": dp_terms(po), "dp_amount": r2(po.get("dp_amount")), "payment_notes": po.get("payment_notes"),
                "payment_id": (active or {}).get("id"), "dp_no": (active or {}).get("no"), "paid_amount": paid,
                "dp_used": u, "dp_available": r2(paid - u), "status": status, "status_label": LABEL[status]}

    # ------------------------------------------------------------------ list
    @app.get("/api/supplier-dp", tags=["supplier-dp"])
    async def list_dp(user=Depends(cu)):
        need(user, "supplier_dp.view", "melihat")
        pos = await db().po.find({"dp_enabled": True}, {"_id": 0}).to_list(100000)
        pays_all = await db().supplier_dp_payments.find({}, {"_id": 0}).to_list(100000)
        by_po = {}
        for p in pays_all:
            by_po.setdefault(p["po_id"], []).append(p)
        paid_po = {p["po_id"] for p in pays_all if p.get("status") == ST_APPROVED}
        pos = [p for p in pos if po_eligible(p) or p["id"] in paid_po]
        vis = None if server.is_global(user) else await server.ACCESS_VISIBLE_IDS("po", user)
        if vis is not None:
            pos = [p for p in pos if p["id"] in vis and Division._division_allowed(server, user, p.get("division_id"))]
        used = await used_by_payment(server, [p["id"] for p in pays_all if p.get("status") == ST_APPROVED])
        sups = await names_of("suppliers", [p.get("supplier_id") for p in pos])
        divs = await names_of("divisions", [p.get("division_id") for p in pos])
        rows = [await row_of(p, by_po.get(p["id"], []), used, sups, divs) for p in pos]
        rows.sort(key=lambda r: str(r.get("po_date") or ""), reverse=True)
        rows.sort(key=lambda r: r["status"] == ST_APPROVED)
        return rows

    async def detail(po_id, user):
        po = await load_po(po_id, user)
        pays = await db().supplier_dp_payments.find({"po_id": po_id}, {"_id": 0}).sort("created_at", 1).to_list(1000)
        if not po_eligible(po) and not any(p.get("status") == ST_APPROVED for p in pays):
            if not pays:
                raise HTTPException(404, "PO ini tidak memiliki DP yang dapat diproses (PO harus Approved dan menggunakan DP).")
        used = await used_by_payment(server, [p["id"] for p in pays if p.get("status") == ST_APPROVED])
        sups = await names_of("suppliers", [po.get("supplier_id")])
        divs = await names_of("divisions", [po.get("division_id")])
        row = await row_of(po, pays, used, sups, divs)
        atts = await db().attachments.find({"entity": ATT_ENTITY, "entity_id": {"$in": [p["id"] for p in pays]}, "is_deleted": False},
                                           {"_id": 0, "storage_path": 0}).to_list(2000) if pays else []
        allocs = await db().vendor_invoice_dp_allocations.find({"po_id": po_id}, {"_id": 0}).to_list(5000)
        invs = {i["id"]: i for i in await db().vendor_invoices.find({"id": {"$in": [a["invoice_id"] for a in allocs]}}, {"_id": 0, "id": 1, "no": 1, "invoice_no": 1, "invoice_date": 1}).to_list(len(allocs) + 5)} if allocs else {}
        history = await db().audit_logs.find({"entity": AUDIT_ENTITY, "entity_id": {"$in": [p["id"] for p in pays]}}, {"_id": 0}).sort("at", -1).to_list(500) if pays else []
        return {**row, "eligible": po_eligible(po), "po": {"id": po["id"], "no": po.get("no"), "date": po.get("date"), "status": po.get("status"),
                                                       "supplier_name": sups.get(po.get("supplier_id")), "division_name": divs.get(po.get("division_id")),
                                                       "grand_total": r2(po.get("grand_total")), "currency": po.get("currency"),
                                                       "payment_term": po.get("payment_term"), "dp_remaining": po.get("dp_remaining")},
                "active_payment": pay_out(next((p for p in pays if p["id"] == row["payment_id"]), None)) if row["payment_id"] else None,
                "payments": [{**pay_out(p), "attachments": [a for a in atts if a.get("entity_id") == p["id"]]} for p in pays],
                "invoice_usage": [{**a, "invoice_no": (invs.get(a["invoice_id"]) or {}).get("invoice_no"), "invoice_sys_no": (invs.get(a["invoice_id"]) or {}).get("no"),
                                   "invoice_date": (invs.get(a["invoice_id"]) or {}).get("invoice_date")} for a in allocs],
                "history": history, "today": today()}

    @app.get("/api/supplier-dp/payments/{pid}/print", tags=["supplier-dp"])
    async def print_dp(pid: str, user=Depends(cu)):
        need(user, "supplier_dp.print", "mencetak")
        pay, po = await load_pay(pid, user)
        await server.audit(user, "print", AUDIT_ENTITY, pid, pay.get("no"))
        return await detail(po["id"], user)

    @app.get("/api/supplier-dp/{po_id}", tags=["supplier-dp"])
    async def get_dp(po_id: str, user=Depends(cu)):
        need(user, "supplier_dp.view", "melihat")
        return await detail(po_id, user)

    # ------------------------------------------------------------------ draft / edit / approve / cancel
    @app.post("/api/supplier-dp/{po_id}/draft", tags=["supplier-dp"])
    async def create_draft(po_id: str, body: dict = None, user=Depends(cu)):
        body = body or {}
        need(user, "supplier_dp.approve", "memproses")
        await load_po(po_id, user)
        async with dp_locks(server, [po_id]):
            po = await load_po(po_id, user)
            require_eligible(po)
            reject_amount(body, po)
            exist = await db().supplier_dp_payments.find_one({"po_id": po_id, "status": {"$in": [ST_DRAFT, ST_APPROVED]}}, {"_id": 0})
            if exist:
                raise HTTPException(409, f"DP untuk PO ini sudah {'dibayar' if exist['status'] == ST_APPROVED else 'memiliki draft aktif'} ({exist.get('no')}).")
            f = fields(body)
            pid = server.gid()
            try:
                await db().supplier_dp_keys.insert_one({"id": key_id(po_id), "po_id": po_id, "payment_id": pid, "created_at": server.now_iso()})
            except Exception as exc:  # noqa: BLE001
                if mariadb_motor._is_duplicate_pk(exc):
                    raise HTTPException(409, "DP untuk PO ini sudah memiliki draft aktif atau sudah dibayar.")
                raise
            try:
                doc = {"id": pid, "no": await server.next_number("DP"), "po_id": po_id, "po_no": po.get("no"),
                       "supplier_id": po.get("supplier_id"), "division_id": po.get("division_id"), "amount": r2(po.get("dp_amount")),
                       "dp_type": po.get("dp_type"), "dp_value": po.get("dp_value"),
                       "payment_date": f["payment_date"] or today(), "fund_source": f["fund_source"], "reference": f["reference"],
                       "notes": f["notes"], "status": ST_DRAFT, "created_by": user.get("email"), "created_by_name": user.get("name"),
                       "created_at": server.now_iso(), "updated_at": server.now_iso()}
                await db().supplier_dp_payments.insert_one(doc)
            except Exception:
                await db().supplier_dp_keys.delete_one({"id": key_id(po_id)})
                raise
            await server.audit(user, "create", AUDIT_ENTITY, pid, doc["no"], after=snap(doc))
        return await detail(po_id, user)

    @app.put("/api/supplier-dp/payments/{pid}", tags=["supplier-dp"])
    async def edit_draft(pid: str, body: dict = None, user=Depends(cu)):
        body = body or {}
        need(user, "supplier_dp.approve", "memproses")
        pay, po = await load_pay(pid, user)
        async with dp_locks(server, [po["id"]]):
            pay, po = await load_pay(pid, user)
            if pay.get("status") != ST_DRAFT:
                raise HTTPException(409, "Hanya draft DP (Menunggu Verifikasi) yang dapat diubah.")
            require_eligible(po)
            reject_amount(body, po)
            f = fields(body, pay)
            upd = {**f, "amount": r2(po.get("dp_amount")), "dp_type": po.get("dp_type"), "dp_value": po.get("dp_value"),
                   "updated_at": server.now_iso(), "updated_by": user.get("email")}
            await db().supplier_dp_payments.update_one({"id": pid, "status": ST_DRAFT}, {"$set": upd})
            await server.audit(user, "edit", AUDIT_ENTITY, pid, pay.get("no"), before=snap(pay), after=snap({**pay, **upd}))
        return await detail(po["id"], user)

    @app.post("/api/supplier-dp/payments/{pid}/approve", tags=["supplier-dp"])
    async def approve(pid: str, body: dict = None, user=Depends(cu)):
        body = body or {}
        need(user, "supplier_dp.approve", "menyetujui")
        pay, po = await load_pay(pid, user)
        async with dp_locks(server, [po["id"]]):
            pay, po = await load_pay(pid, user)
            if pay.get("status") == ST_APPROVED:
                raise HTTPException(409, f"DP {pay.get('no')} sudah dibayar (Approved). Tidak dapat di-approve dua kali.")
            if pay.get("status") != ST_DRAFT:
                raise HTTPException(409, "Draft DP ini sudah dibatalkan.")
            require_eligible(po)
            reject_amount(body, po)
            if await db().supplier_dp_payments.find_one({"po_id": po["id"], "status": ST_APPROVED, "id": {"$ne": pid}}, {"_id": 0, "id": 1}):
                raise HTTPException(409, "DP untuk PO ini sudah dibayar.")
            f = fields(body, pay)
            if not f["payment_date"]:
                raise HTTPException(400, "Tanggal Pembayaran wajib diisi")
            if not f["fund_source"]:
                raise HTTPException(400, "Sumber Dana wajib diisi")
            if abs(float(pay.get("amount") or 0) - float(po.get("dp_amount") or 0)) > EPS:
                raise HTTPException(409, f"Nilai DP pada draft ({rp(pay.get('amount'))}) berbeda dengan nilai DP PO saat ini ({rp(po.get('dp_amount'))}). "
                                         "Simpan ulang draft agar nilai mengikuti PO.")
            if await proof_count(pid) < 1:
                raise HTTPException(400, "Bukti Pembayaran wajib diunggah sebelum Approve Pembayaran DP.")
            upd = {**f, "status": ST_APPROVED, "approved_by": user.get("email"), "approved_by_name": user.get("name"),
                   "approved_at": server.now_iso(), "updated_at": server.now_iso()}
            res = await db().supplier_dp_payments.update_one({"id": pid, "status": ST_DRAFT}, {"$set": upd})
            if getattr(res, "matched_count", 1) == 0:
                raise HTTPException(409, "DP sudah diproses transaksi lain.")
            await server.audit(user, "approve", AUDIT_ENTITY, pid, pay.get("no"), before=snap(pay), after=snap({**pay, **upd}))
        return await detail(po["id"], user)

    @app.post("/api/supplier-dp/payments/{pid}/cancel", tags=["supplier-dp"])
    async def cancel_draft(pid: str, body: dict = None, user=Depends(cu)):
        body = body or {}
        need(user, "supplier_dp.approve", "membatalkan")
        pay, po = await load_pay(pid, user)
        reason = str(body.get("reason") or "").strip()
        async with dp_locks(server, [po["id"]]):
            pay, po = await load_pay(pid, user)
            if pay.get("status") == ST_APPROVED:
                raise HTTPException(409, MSG_DP_PAID_CANCEL)
            if pay.get("status") != ST_DRAFT:
                raise HTTPException(409, "Draft DP ini sudah dibatalkan.")
            if not reason:
                raise HTTPException(400, "Alasan pembatalan draft DP wajib diisi")
            await cancel_draft_doc(pay, user, reason)
        return await detail(po["id"], user)

    async def cancel_draft_doc(pay, user, reason):
        upd = {"status": ST_CANCELLED, "cancelled_by": user.get("email"), "cancelled_by_name": user.get("name"),
               "cancelled_at": server.now_iso(), "cancel_reason": reason[:1000], "updated_at": server.now_iso()}
        await db().supplier_dp_payments.update_one({"id": pay["id"], "status": ST_DRAFT}, {"$set": upd})
        k = await db().supplier_dp_keys.find_one({"id": key_id(pay["po_id"])}, {"_id": 0})
        if k and k.get("payment_id") == pay["id"]:
            await db().supplier_dp_keys.delete_one({"id": key_id(pay["po_id"])})
        await server.audit(user, "cancel", AUDIT_ENTITY, pay["id"], pay.get("no"), reason=reason, before=snap(pay), after=snap({**pay, **upd}))

    # ------------------------------------------------------------------ guard PO (cancel / edit / delete)
    def find_route(path, method):
        return next((r for r in app.router.routes if getattr(r, "path", "") == path and method in (getattr(r, "methods", None) or set())), None)

    async def paid_dp(po_id):
        return await db().supplier_dp_payments.find_one({"po_id": po_id, "status": ST_APPROVED}, {"_id": 0})

    async def drafts_after_po_gone(po_id, user, reason):
        for d in await db().supplier_dp_payments.find({"po_id": po_id, "status": ST_DRAFT}, {"_id": 0}).to_list(50):
            await cancel_draft_doc(d, user, reason)

    r_cancel = find_route("/api/po/{did}/cancel", "POST")
    if r_cancel:
        orig_cancel = r_cancel.endpoint
        app.router.routes.remove(r_cancel)

        async def guarded_po_cancel(did: str, body: dict = None, user=Depends(cu)):
            async with dp_locks(server, [did]):
                if await paid_dp(did):
                    raise HTTPException(409, MSG_PO_CANCEL)
                res = await orig_cancel(did=did, body=body or {}, user=user)
                po = await db().po.find_one({"id": did}, {"_id": 0, "status": 1, "cancelled": 1})
                if po and (po.get("cancelled") is True or po.get("status") == "Cancelled"):
                    await drafts_after_po_gone(did, user, "PO dibatalkan")
            return res
        app.add_api_route("/api/po/{did}/cancel", guarded_po_cancel, methods=["POST"], tags=["supplier-dp"])

    def commercial(po_doc, normalized=None):
        """Signature komersial PO: Grand Total, DP, supplier, divisi, mata uang."""
        if normalized is None:
            return {"grand_total": r2(po_doc.get("grand_total")), "dp_enabled": bool(po_doc.get("dp_enabled")), "dp_type": po_doc.get("dp_type"),
                    "dp_value": r2(po_doc.get("dp_value")) if po_doc.get("dp_value") is not None else None,
                    "dp_amount": r2(po_doc.get("dp_amount")), "supplier_id": po_doc.get("supplier_id"),
                    "division_id": po_doc.get("division_id"), "currency": po_doc.get("currency") or None}
        lines = [dict(ln) for ln in normalized.get("lines") or [] if not (ln.get("qty") is not None and float(ln.get("qty") or 0) <= 0)]
        _c, t = DPM.compute_po_totals(normalized, lines)
        dp = DPM.compute_po_dp(DPM.po_dp_source(po_doc, normalized), t["grand_total"])
        return {"grand_total": r2(t["grand_total"]), "dp_enabled": bool(dp.get("dp_enabled")), "dp_type": dp.get("dp_type"),
                "dp_value": r2(dp.get("dp_value")) if dp.get("dp_value") is not None else None, "dp_amount": r2(dp.get("dp_amount")),
                "supplier_id": normalized.get("supplier_id", po_doc.get("supplier_id")),
                "division_id": normalized.get("division_id", po_doc.get("division_id")),
                "currency": (normalized.get("currency", po_doc.get("currency")) or None)}

    def same(a, b):
        for k in a:
            x, y = a[k], b.get(k)
            if isinstance(x, float) or isinstance(y, float):
                if abs(float(x or 0) - float(y or 0)) > EPS:
                    return False
            elif x != y:
                return False
        return True

    r_put = find_route("/api/transactions/{module}/{did}", "PUT")
    if r_put:
        orig_put = r_put.endpoint
        app.router.routes.remove(r_put)

        async def guarded_txn_edit(module: str, did: str, body: dict, user=Depends(cu)):
            if module != "po":
                return await orig_put(module=module, did=did, body=body, user=user)
            async with dp_locks(server, [did]):
                po = await db().po.find_one({"id": did}, {"_id": 0})
                if po and await paid_dp(did):
                    normalized, _m = await TM._normalize_qty_body(server, "po", body)
                    if not same(commercial(po), commercial(po, normalized)):
                        raise HTTPException(409, MSG_PO_EDIT)
                return await orig_put(module=module, did=did, body=body, user=user)
        app.add_api_route("/api/transactions/{module}/{did}", guarded_txn_edit, methods=["PUT"], tags=["supplier-dp"])

    r_del = find_route("/api/transactions/{module}/{did}", "DELETE")
    if r_del:
        orig_del = r_del.endpoint
        app.router.routes.remove(r_del)

        async def guarded_txn_delete(module: str, did: str, user=Depends(cu)):
            if module != "po":
                return await orig_del(module=module, did=did, user=user)
            async with dp_locks(server, [did]):
                if await paid_dp(did):
                    raise HTTPException(409, MSG_PO_CANCEL)
                res = await orig_del(module=module, did=did, user=user)
                if not await db().po.find_one({"id": did}, {"_id": 0, "id": 1}):
                    await drafts_after_po_gone(did, user, "PO dihapus")
            return res
        app.add_api_route("/api/transactions/{module}/{did}", guarded_txn_delete, methods=["DELETE"], tags=["supplier-dp"])

    # ------------------------------------------------------------------ lampiran (AttachmentPanel + storage existing)
    async def att_parent(entity_id, user):
        need(user, "supplier_dp.view", "melihat")
        return await load_pay(str(entity_id or "").strip(), user)

    r_up = find_route("/api/attachments", "POST")
    if r_up:
        orig_up = r_up.endpoint
        app.router.routes.remove(r_up)

        async def upload(request: Request, file: UploadFile = File(...), entity: str = Form(...), entity_id: str = Form(...),
                         category: str = Form("Lainnya"), note: str = Form("")):
            if str(entity or "").strip().lower() != ATT_ENTITY:
                return await orig_up(request, file, entity, entity_id, category, note)
            user = await cu(request)
            server.require(user, "upload_attachment")
            need(user, "supplier_dp.approve", "mengunggah bukti pembayaran")
            pay, po = await att_parent(entity_id, user)
            if pay.get("status") != ST_DRAFT:
                raise HTTPException(409, "Bukti pembayaran hanya dapat diubah selama DP masih Menunggu Verifikasi.")
            await _validate_file(file)
            name = file.filename.rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower()
            data = await file.read()
            ct = file.content_type or S.MIME_TYPES.get(ext, "application/octet-stream")
            res = S.put_object(f"{S.APP_NAME}/uploads/{ATT_ENTITY}/{server.gid()}.{ext}", data, ct)
            doc = {"id": server.gid(), "storage_path": res["path"], "original_filename": name, "content_type": ct,
                   "size": res.get("size", len(data)), "entity": ATT_ENTITY, "entity_id": pay["id"], "po_id": po["id"],
                   "category": str(category if category and category != "Lainnya" else "Bukti Pembayaran")[:100], "note": str(note or "")[:1000], "uploaded_by": user.get("name"),
                   "uploaded_by_email": user.get("email"), "is_deleted": False, "created_at": server.now_iso()}
            try:
                await db().attachments.insert_one(doc)
            except Exception:
                S.delete_object(res["path"])
                raise
            await server.audit(user, "upload_file", AUDIT_ENTITY, pay["id"], pay.get("no"), after={"file": name})
            return {k: v for k, v in doc.items() if k != "storage_path"}
        app.add_api_route("/api/attachments", upload, methods=["POST"], tags=["supplier-dp"])

    r_list = find_route("/api/attachments", "GET")
    if r_list:
        orig_list = r_list.endpoint
        app.router.routes.remove(r_list)

        async def list_att(entity: str, entity_id: str, user=Depends(cu)):
            if entity == ATT_ENTITY:
                await att_parent(entity_id, user)
            return await orig_list(entity=entity, entity_id=entity_id, user=user)
        app.add_api_route("/api/attachments", list_att, methods=["GET"], tags=["supplier-dp"])

    r_dl = find_route("/api/attachments/{aid}/download", "GET")
    if r_dl:
        orig_dl = r_dl.endpoint
        app.router.routes.remove(r_dl)

        async def download(aid: str, request: Request, auth: str = Query(None)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0, "entity": 1, "entity_id": 1})
            if rec and rec.get("entity") == ATT_ENTITY:
                await att_parent(rec["entity_id"], await cu(request))
            return await orig_dl(aid=aid, request=request, auth=auth)
        app.add_api_route("/api/attachments/{aid}/download", download, methods=["GET"], tags=["supplier-dp"])

    r_adel = find_route("/api/attachments/{aid}", "DELETE")
    if r_adel:
        orig_adel = r_adel.endpoint
        app.router.routes.remove(r_adel)

        async def delete_att(aid: str, user=Depends(cu)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0})
            if not rec or rec.get("entity") != ATT_ENTITY:
                return await orig_adel(aid=aid, user=user)
            need(user, "supplier_dp.approve", "menghapus bukti pembayaran")
            pay, _po = await att_parent(rec["entity_id"], user)
            if pay.get("status") != ST_DRAFT:
                raise HTTPException(409, "Bukti pembayaran hanya dapat diubah selama DP masih Menunggu Verifikasi.")
            await db().attachments.update_one({"id": aid}, {"$set": {"is_deleted": True, "deleted_by": user.get("email"), "deleted_at": server.now_iso()}})
            await server.audit(user, "delete_file", AUDIT_ENTITY, pay["id"], pay.get("no"), before={"file": rec.get("original_filename")})
            return {"ok": True}
        app.add_api_route("/api/attachments/{aid}", delete_att, methods=["DELETE"], tags=["supplier-dp"])

    # ------------------------------------------------------------------ audit scope untuk entity supplier_dp
    r_audit = find_route("/api/audit", "GET")
    if r_audit:
        orig_audit = r_audit.endpoint
        app.router.routes.remove(r_audit)

        async def audit_list(entity: str = None, entity_id: str = None, limit: int = 300, user=Depends(cu)):
            rows = await orig_audit(entity=entity, entity_id=entity_id, limit=limit, user=user)
            if not any(str(r.get("entity")) == AUDIT_ENTITY for r in rows or []):
                return rows
            ok, cache, out = can(user, "supplier_dp.view"), {}, []
            for r in rows:
                if str(r.get("entity")) != AUDIT_ENTITY:
                    out.append(r)
                    continue
                if not ok:
                    continue
                eid = r.get("entity_id")
                if eid not in cache:
                    pay = await db().supplier_dp_payments.find_one({"id": eid}, {"_id": 0, "po_id": 1})
                    po = await db().po.find_one({"id": (pay or {}).get("po_id")}, {"_id": 0}) if pay else None
                    cache[eid] = await po_access(server, user, po)
                if cache[eid]:
                    out.append(r)
            return out
        app.add_api_route("/api/audit", audit_list, methods=["GET"], tags=["supplier-dp"])
