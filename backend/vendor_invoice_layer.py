"""Tahap 3 — Invoice Vendor: DO -> Invoice Diterima -> Pembayaran -> Monitoring.

Lapisan administrasi/keuangan setelah receiving. Tidak mengubah PO, DO, commitment SPK, stok,
Moving Average maupun HPP. Relasi DO <-> Invoice many-to-many lewat `vendor_invoice_allocations`.
Urutan: Tenant (proxy) -> Permission (access hook) -> Cakupan Divisi (DO visibility) -> Business Rule.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile

import mariadb_motor
import receipt_control_layer as RC
import storage as S
import transaction_mutation_layer as TM
from attachment_integrity_guard_layer import _validate_file

TOL = 1.0            # toleransi Rp1 untuk status penagihan DO & selisih invoice
EPS = 0.005
BILL = ("Belum Ditagihkan", "Ditagihkan Sebagian", "Sudah Ditagihkan Penuh")
PAY = ("Belum Dibayar", "Dibayar Sebagian", "Lunas")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCK = asyncio.Lock()
ATT_ENTITIES = {"invoice", "invoice_payment"}
mariadb_motor.STRICT_PK_COLLECTIONS.add("vendor_invoice_keys")


def money(v, label):
    try:
        x = round(float(v), 2)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{label} tidak valid")
    if x < 0:
        raise HTTPException(400, f"{label} tidak boleh negatif")
    return x


def req_date(v, label):
    s = str(v or "").strip()[:10]
    if not DATE_RE.match(s):
        raise HTTPException(400, f"{label} wajib diisi (format tanggal tidak valid)")
    return s


def norm_no(s):
    return re.sub(r"\s+", " ", str(s or "").strip()).upper()


def key_id(supplier_id, invoice_no):
    return "vik-" + hashlib.sha1(f"{supplier_id}|{norm_no(invoice_no)}".encode()).hexdigest()[:40]


def bill_status(value, billed):
    if billed <= EPS:
        return BILL[0]
    return BILL[2] if billed >= value - TOL else BILL[1]


def pay_status(amount, paid):
    if paid <= EPS:
        return PAY[0]
    return PAY[2] if paid >= amount - EPS else PAY[1]


def today():
    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


def due_state(inv, td):
    if inv.get("payment_status") == PAY[2]:
        return "Lunas"
    dd = str(inv.get("due_date") or "")[:10]
    if not dd:
        return "-"
    if dd < td.isoformat():
        return "Lewat Jatuh Tempo"
    if dd <= (td + timedelta(days=7)).isoformat():
        return "Jatuh Tempo"
    return "Belum Jatuh Tempo"


def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731
    cu = server.current_user

    def can(user, key):
        return user.get("role") == "admin" or key in set(user.get("effective_permissions") or [])

    def need_any(user, keys, verb):
        if not any(can(user, k) for k in keys):
            raise HTTPException(403, f"Anda tidak memiliki izin untuk {verb} data Invoice Vendor.")

    # ------------------------------------------------------------------ helpers
    async def do_values(do_ids):
        out = {d: {"net": 0.0, "tax": 0.0, "total": 0.0} for d in do_ids}
        if not do_ids:
            return out
        lines = await db().do_lines.find({"do_id": {"$in": list(do_ids)}}, {"_id": 0, "do_id": 1, "po_line_id": 1, "po_id": 1, "qty": 1}).to_list(100000)
        pl_ids = list({ln["po_line_id"] for ln in lines if ln.get("po_line_id")})
        pls = {p["id"]: p for p in await db().po_lines.find({"id": {"$in": pl_ids}}, {"_id": 0, "id": 1, "qty": 1, "dpp": 1, "tax_amount": 1, "total": 1}).to_list(len(pl_ids) + 5)} if pl_ids else {}
        for ln in lines:
            p = pls.get(ln.get("po_line_id"))
            if not p or not float(p.get("qty") or 0):
                continue
            r = float(ln.get("qty") or 0) / float(p["qty"])
            o = out.setdefault(ln["do_id"], {"net": 0.0, "tax": 0.0, "total": 0.0})
            o["tax"] += float(p.get("tax_amount") or 0) * r
            o["total"] += float(p.get("total") or 0) * r
        for o in out.values():
            o["total"], o["tax"] = round(o["total"], 2), round(o["tax"], 2)
            o["net"] = round(o["total"] - o["tax"], 2)
        return out

    async def allocs_for(do_ids):
        if not do_ids:
            return []
        return await db().vendor_invoice_allocations.find({"do_id": {"$in": list(do_ids)}}, {"_id": 0}).to_list(100000)

    def billed_of(allocs, exclude=None):
        m = {}
        for a in allocs:
            if a.get("invoice_id") != exclude:
                m[a["do_id"]] = round(m.get(a["do_id"], 0.0) + float(a.get("amount") or 0), 2)
        return m

    async def traces(dos):
        rows = await RC.enrich_list(server, "do", [dict(d) for d in dos]) if dos else []
        return {r["id"]: r for r in rows}

    async def vis_dos(user):
        return await server.ACCESS_VISIBLE_IDS("do", user)

    def inv_visible(inv, vis):
        return vis is None or all(d in vis for d in inv.get("do_ids") or [])

    async def get_inv(iid, user):
        inv = await db().vendor_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv:
            raise HTTPException(404, "Invoice Vendor tidak ditemukan")
        if not server.is_global(user):
            for d in inv.get("do_ids") or []:
                if not await server.ACCESS_DOC_VISIBLE("do", d, user):
                    raise HTTPException(403, "Invoice ini berada di luar cakupan divisi Anda.")
        return inv

    def join(ts, key):
        vals = []
        for t in ts:
            vals += [x.strip() for x in str(t.get(key) or "").split(",") if x.strip()]
        return ", ".join(dict.fromkeys(vals))

    async def enrich(invs):
        do_ids = sorted({d for i in invs for d in i.get("do_ids") or []})
        dos = await db().do.find({"id": {"$in": do_ids}}, {"_id": 0}).to_list(len(do_ids) + 5) if do_ids else []
        tr = await traces(dos)
        sups = {s["id"]: s for s in await db().suppliers.find({}, {"_id": 0, "id": 1, "name": 1, "code": 1}).to_list(5000)}
        td = today()
        for i in invs:
            ts = [tr.get(d) or {} for d in i.get("do_ids") or []]
            i.update({
                "supplier_name": (sups.get(i.get("supplier_id")) or {}).get("name"),
                "do_nos": ", ".join(t.get("no") for t in ts if t.get("no")),
                "trace_po": join(ts, "trace_po"), "trace_ro": join(ts, "trace_ro"), "trace_mro": join(ts, "trace_mro"),
                "trace_spk": join(ts, "trace_spk"), "trace_project": join(ts, "trace_project"),
                "trace_division": join(ts, "trace_division"),
                "remaining": round(float(i.get("amount") or 0) - float(i.get("paid_total") or 0), 2),
                "due_state": due_state(i, td),
            })
        return invs

    async def visible_invoices(user):
        invs = await db().vendor_invoices.find({}, {"_id": 0}).to_list(100000)
        vis = await vis_dos(user)
        return [i for i in invs if inv_visible(i, vis)]

    # ------------------------------------------------------------------ validation
    async def validate(body, user, current=None):
        cur = current or {}
        sup = cur.get("supplier_id") or body.get("supplier_id")
        if current and body.get("supplier_id") and body["supplier_id"] != cur["supplier_id"]:
            raise HTTPException(400, "Supplier invoice tidak dapat diubah. Hapus dan catat ulang invoice bila supplier salah.")
        if not sup or not await db().suppliers.find_one({"id": sup}, {"_id": 0, "id": 1}):
            raise HTTPException(400, "Supplier wajib dipilih")
        f = {k: body.get(k, cur.get(k)) for k in ("invoice_no", "invoice_date", "received_date", "due_date", "dpp", "tax_amount", "amount", "diff_reason", "notes")}
        inv_no = str(f["invoice_no"] or "").strip()
        if not inv_no:
            raise HTTPException(400, "No Invoice wajib diisi")
        if await db().vendor_invoices.find_one({"supplier_id": sup, "invoice_no_norm": norm_no(inv_no), "id": {"$ne": cur.get("id") or ""}}, {"_id": 0, "id": 1}):
            raise HTTPException(409, f"No Invoice {inv_no} untuk Supplier ini sudah tercatat.")
        out = {"supplier_id": sup, "invoice_no": inv_no, "invoice_no_norm": norm_no(inv_no),
               "invoice_date": req_date(f["invoice_date"], "Tanggal Invoice"),
               "received_date": req_date(f["received_date"], "Tanggal Invoice Diterima"),
               "due_date": req_date(f["due_date"], "Jatuh Tempo"),
               "notes": str(f["notes"] or "").strip(), "diff_reason": str(f["diff_reason"] or "").strip()}
        if out["due_date"] < out["invoice_date"]:
            raise HTTPException(400, "Jatuh Tempo tidak boleh sebelum Tanggal Invoice")
        amount = money(f["amount"], "Nilai Invoice")
        if amount <= 0:
            raise HTTPException(400, "Nilai Invoice harus lebih dari 0")
        tax = money(f["tax_amount"] or 0, "Pajak")
        dpp = money(body["dpp"], "DPP") if body.get("dpp") not in (None, "") else round(amount - tax, 2)
        if abs(dpp + tax - amount) > 0.01:
            raise HTTPException(400, "Nilai Invoice harus sama dengan DPP + Pajak")
        raw = body.get("allocations") if "allocations" in body else cur.get("_allocations")
        allocs, seen = [], set()
        for a in raw or []:
            did = (a or {}).get("do_id")
            amt = money((a or {}).get("amount"), "Nilai alokasi DO")
            if not did or amt <= 0:
                continue
            if did in seen:
                raise HTTPException(400, "DO yang sama tidak boleh dipilih dua kali dalam satu invoice")
            seen.add(did)
            allocs.append({"do_id": did, "amount": amt})
        if not allocs:
            raise HTTPException(400, "Pilih minimal satu DO dengan nilai alokasi lebih dari 0")
        ids = [a["do_id"] for a in allocs]
        dos = {d["id"]: d for d in await db().do.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 5)}
        for did in ids:
            d = dos.get(did)
            if not d:
                raise HTTPException(404, "DO tidak ditemukan")
            if str(d.get("status") or "").lower() in ("cancelled", "dibatalkan"):
                raise HTTPException(400, f"DO {d.get('no')} sudah dibatalkan dan tidak dapat ditagihkan")
            if d.get("supplier_id") != sup:
                raise HTTPException(400, f"DO {d.get('no')} berasal dari Supplier lain. Semua DO dalam satu invoice harus dari Supplier yang sama.")
            if not await server.ACCESS_DOC_VISIBLE("do", did, user):
                raise HTTPException(403, f"DO {d.get('no')} berada di luar cakupan divisi Anda.")
        vals = await do_values(ids)
        billed = billed_of(await allocs_for(ids), exclude=cur.get("id"))
        rows, total = [], 0.0
        for a in allocs:
            d, v = dos[a["do_id"]], vals[a["do_id"]]["total"]
            before = billed.get(a["do_id"], 0.0)
            rem = round(v - before, 2)
            if a["amount"] > rem + EPS:
                raise HTTPException(409, f"Alokasi DO {d.get('no')} melebihi sisa belum ditagihkan (Sisa Rp {rem:,.0f}).".replace(",", "."))
            total += a["amount"]
            rows.append({"do_id": a["do_id"], "do_no": d.get("no"), "do_value": v, "billed_before": before,
                         "amount": a["amount"], "remaining_after": round(rem - a["amount"], 2)})
        total = round(total, 2)
        diff = round(amount - total, 2)
        if abs(diff) >= TOL and not out["diff_reason"]:
            raise HTTPException(400, "Total Alokasi DO berbeda dengan Nilai Invoice Vendor. Alasan Selisih wajib diisi.")
        if current and amount < float(cur.get("paid_total") or 0) - EPS:
            raise HTTPException(409, "Nilai Invoice tidak boleh lebih kecil dari total yang sudah dibayar")
        tr = await traces(list(dos.values()))
        divs = sorted({x for did in ids for x in (tr.get(did) or {}).get("trace_division_ids") or []})
        lines = await db().do_lines.find({"do_id": {"$in": ids}}, {"_id": 0, "po_id": 1}).to_list(100000)
        out.update({"dpp": dpp, "tax_amount": tax, "amount": amount, "alloc_total": total, "diff": diff,
                    "diff_status": "Sesuai" if abs(diff) < TOL else "Ada Selisih",
                    "do_ids": ids, "po_ids": sorted({ln["po_id"] for ln in lines if ln.get("po_id")}), "division_ids": divs})
        if not out["diff_status"] == "Ada Selisih":
            out["diff_reason"] = ""
        return out, rows

    async def save_allocs(iid, rows, user):
        await db().vendor_invoice_allocations.delete_many({"invoice_id": iid})
        for r in rows:
            await db().vendor_invoice_allocations.insert_one({"id": server.gid(), "invoice_id": iid, **r,
                                                             "created_by": user.get("email"), "created_at": server.now_iso()})

    async def claim_key(supplier_id, invoice_no, iid):
        if await db().vendor_invoices.find_one({"supplier_id": supplier_id, "invoice_no_norm": norm_no(invoice_no), "id": {"$ne": iid}}, {"_id": 0, "id": 1}):
            raise HTTPException(409, f"No Invoice {invoice_no} untuk Supplier ini sudah tercatat.")
        try:
            await db().vendor_invoice_keys.insert_one({"id": key_id(supplier_id, invoice_no), "invoice_id": iid, "created_at": server.now_iso()})
        except Exception as exc:  # noqa: BLE001
            if mariadb_motor._is_duplicate_pk(exc):
                raise HTTPException(409, f"No Invoice {invoice_no} untuk Supplier ini sudah tercatat.")
            raise

    def snap(inv, rows=None):
        keep = ("no", "supplier_id", "invoice_no", "invoice_date", "received_date", "due_date", "dpp", "tax_amount", "amount",
                "alloc_total", "diff", "diff_reason", "notes", "paid_total", "payment_status")
        s = {k: inv.get(k) for k in keep}
        if rows is not None:
            s["allocations"] = [{"do_no": r["do_no"], "amount": r["amount"]} for r in rows]
        return s

    async def refresh_paid(iid):
        inv = await db().vendor_invoices.find_one({"id": iid}, {"_id": 0})
        pays = await db().vendor_invoice_payments.find({"invoice_id": iid, "status": "Aktif"}, {"_id": 0, "amount": 1}).to_list(10000)
        paid = round(sum(float(p.get("amount") or 0) for p in pays), 2)
        st = pay_status(float(inv.get("amount") or 0), paid)
        await db().vendor_invoices.update_one({"id": iid}, {"$set": {"paid_total": paid, "payment_status": st, "updated_at": server.now_iso()}})
        return paid, st

    # ------------------------------------------------------------------ routes (static paths first)
    @app.get("/api/vendor-invoices", tags=["vendor-invoice"])
    async def list_invoices(user=Depends(cu)):
        return await enrich(await visible_invoices(user))

    @app.get("/api/vendor-invoices/summary", tags=["vendor-invoice"])
    async def summary(user=Depends(cu)):
        invs = await enrich(await visible_invoices(user))
        billing = await do_billing_rows(user)
        unb = [b for b in billing if b["billing_status"] != BILL[2]]
        out = {"invoice_not_received": len(unb), "invoice_not_received_value": round(sum(b["remaining"] for b in unb), 2),
               "invoice_received": len(invs), "invoice_received_value": round(sum(i["amount"] for i in invs), 2),
               "total_payable": round(sum(max(0.0, i["remaining"]) for i in invs), 2)}
        for key, st in (("unpaid", PAY[0]), ("partial", PAY[1]), ("paid", PAY[2])):
            rows = [i for i in invs if i.get("payment_status") == st]
            out[key], out[key + "_value"] = len(rows), round(sum(i["remaining"] if st != PAY[2] else i["amount"] for i in rows), 2)
        for key, st in (("due_soon", "Jatuh Tempo"), ("overdue", "Lewat Jatuh Tempo")):
            rows = [i for i in invs if i["due_state"] == st]
            out[key], out[key + "_value"] = len(rows), round(sum(i["remaining"] for i in rows), 2)
        return out

    async def do_billing_rows(user, supplier_id=None, exclude=None):
        q = {"supplier_id": supplier_id} if supplier_id else {}
        dos = await db().do.find(q, {"_id": 0}).to_list(100000)
        vis = await vis_dos(user)
        dos = [d for d in dos if (vis is None or d["id"] in vis) and str(d.get("status") or "").lower() not in ("cancelled", "dibatalkan")]
        ids = [d["id"] for d in dos]
        vals, allocs = await do_values(ids), await allocs_for(ids)
        billed, tr = billed_of(allocs, exclude=exclude), await traces(dos)
        sups = {s["id"]: s.get("name") for s in await db().suppliers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)}
        out = []
        for d in dos:
            t, v, b = tr.get(d["id"]) or {}, vals[d["id"]]["total"], billed.get(d["id"], 0.0)
            out.append({"do_id": d["id"], "do_no": d.get("no"), "date": d.get("date"), "supplier_id": d.get("supplier_id"),
                        "supplier_name": sups.get(d.get("supplier_id")), "po_nos": t.get("trace_po"), "ro_nos": t.get("trace_ro"),
                        "mro_nos": t.get("trace_mro"), "project": t.get("trace_project"), "division": t.get("trace_division"),
                        "spk": t.get("trace_spk"), "do_value": v, "do_net": vals[d["id"]]["net"], "do_tax": vals[d["id"]]["tax"],
                        "billed": b, "remaining": round(v - b, 2), "billing_status": bill_status(v, b)})
        return out

    @app.get("/api/vendor-invoices/do-billing", tags=["vendor-invoice"])
    async def do_billing(user=Depends(cu)):
        return await do_billing_rows(user)

    @app.get("/api/vendor-invoices/eligible-dos", tags=["vendor-invoice"])
    async def eligible_dos(supplier_id: str, invoice_id: str = None, user=Depends(cu)):
        need_any(user, ["invoice.create", "invoice.edit"], "mencatat")
        if invoice_id:
            await get_inv(invoice_id, user)
        mine = {a["do_id"] for a in await db().vendor_invoice_allocations.find({"invoice_id": invoice_id}, {"_id": 0, "do_id": 1}).to_list(5000)} if invoice_id else set()
        rows = await do_billing_rows(user, supplier_id=supplier_id, exclude=invoice_id)
        return [r for r in rows if r["remaining"] > EPS or r["do_id"] in mine]

    @app.get("/api/vendor-invoices/do/{do_id}", tags=["vendor-invoice"])
    async def invoices_for_do(do_id: str, user=Depends(cu)):
        d = await db().do.find_one({"id": do_id}, {"_id": 0})
        if not d:
            raise HTTPException(404, "DO tidak ditemukan")
        if not await server.ACCESS_DOC_VISIBLE("do", do_id, user):
            raise HTTPException(403, "Dokumen ini berada di luar cakupan divisi Anda.")
        v = (await do_values([do_id]))[do_id]["total"]
        allocs = await allocs_for([do_id])
        b = billed_of(allocs).get(do_id, 0.0)
        invs = {i["id"]: i for i in await db().vendor_invoices.find({"id": {"$in": [a["invoice_id"] for a in allocs]}}, {"_id": 0}).to_list(5000)} if allocs else {}
        vis = await vis_dos(user)
        rows = [{"invoice_id": a["invoice_id"], "no": invs[a["invoice_id"]].get("no"), "invoice_no": invs[a["invoice_id"]].get("invoice_no"),
                 "invoice_date": invs[a["invoice_id"]].get("invoice_date"), "amount": a["amount"],
                 "payment_status": invs[a["invoice_id"]].get("payment_status")}
                for a in allocs if a["invoice_id"] in invs and inv_visible(invs[a["invoice_id"]], vis)]
        return {"do_id": do_id, "do_no": d.get("no"), "do_value": v, "billed": b, "remaining": round(v - b, 2),
                "billing_status": bill_status(v, b), "invoices": rows}

    @app.post("/api/vendor-invoices", tags=["vendor-invoice"])
    async def create_invoice(body: dict, user=Depends(cu)):
        async with _LOCK:
            data, rows = await validate(body or {}, user)
            iid = server.gid()
            await claim_key(data["supplier_id"], data["invoice_no"], iid)
            try:
                doc = {"id": iid, "no": await server.next_number("INV"), **data, "status": "Diterima", "paid_total": 0.0,
                       "payment_status": PAY[0], "created_by": user.get("email"), "created_by_name": user.get("name"),
                       "created_at": server.now_iso(), "updated_at": server.now_iso()}
                await db().vendor_invoices.insert_one(doc)
                await save_allocs(iid, rows, user)
            except Exception:
                await db().vendor_invoice_keys.delete_one({"id": key_id(data["supplier_id"], data["invoice_no"])})
                raise
            await server.audit(user, "create", "invoice", iid, doc["no"], after=snap(doc, rows))
        return await detail(iid, user)

    async def detail(iid, user):
        inv = (await enrich([await get_inv(iid, user)]))[0]
        allocs = await db().vendor_invoice_allocations.find({"invoice_id": iid}, {"_id": 0}).to_list(5000)
        ids = [a["do_id"] for a in allocs]
        dos = await db().do.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids) + 5) if ids else []
        tr, vals, billed = await traces(dos), await do_values(ids), billed_of(await allocs_for(ids))
        inv["allocations"] = [{**a, "do_date": (tr.get(a["do_id"]) or {}).get("date"), "do_value_now": vals[a["do_id"]]["total"],
                               "billed_now": billed.get(a["do_id"], 0.0), "remaining_now": round(vals[a["do_id"]]["total"] - billed.get(a["do_id"], 0.0), 2),
                               "billing_status": bill_status(vals[a["do_id"]]["total"], billed.get(a["do_id"], 0.0)),
                               **{k: (tr.get(a["do_id"]) or {}).get(k) for k in ("trace_po", "trace_ro", "trace_mro", "trace_spk", "trace_project", "trace_division")}}
                              for a in allocs]
        inv["payments"] = await db().vendor_invoice_payments.find({"invoice_id": iid}, {"_id": 0}).sort("created_at", 1).to_list(10000)
        atts = await db().attachments.find({"invoice_id": iid, "is_deleted": False}, {"_id": 0, "storage_path": 0}).to_list(2000)
        inv["files"] = [a for a in atts if a.get("entity") == "invoice"]
        for p in inv["payments"]:
            p["attachments"] = [a for a in atts if a.get("entity") == "invoice_payment" and a.get("entity_id") == p["id"]]
        inv["history"] = await db().audit_logs.find({"entity": "invoice", "entity_id": iid}, {"_id": 0}).sort("at", -1).to_list(500)
        return inv

    @app.get("/api/vendor-invoices/{iid}", tags=["vendor-invoice"])
    async def get_invoice(iid: str, user=Depends(cu)):
        return await detail(iid, user)

    @app.get("/api/vendor-invoices/{iid}/print", tags=["vendor-invoice"])
    async def print_invoice(iid: str, user=Depends(cu)):
        return await detail(iid, user)

    @app.put("/api/vendor-invoices/{iid}", tags=["vendor-invoice"])
    async def edit_invoice(iid: str, body: dict, user=Depends(cu)):
        async with _LOCK:
            cur = await get_inv(iid, user)
            old_rows = await db().vendor_invoice_allocations.find({"invoice_id": iid}, {"_id": 0}).to_list(5000)
            cur["_allocations"] = [{"do_id": a["do_id"], "amount": a["amount"]} for a in old_rows]
            data, rows = await validate(body or {}, user, current=cur)
            if data["invoice_no_norm"] != cur.get("invoice_no_norm"):
                await claim_key(cur["supplier_id"], data["invoice_no"], iid)
                await db().vendor_invoice_keys.delete_one({"id": key_id(cur["supplier_id"], cur["invoice_no"])})
            await db().vendor_invoices.update_one({"id": iid}, {"$set": {**data, "updated_at": server.now_iso(), "updated_by": user.get("email")}})
            await save_allocs(iid, rows, user)
            await refresh_paid(iid)
            new = await db().vendor_invoices.find_one({"id": iid}, {"_id": 0})
            await server.audit(user, "edit", "invoice", iid, cur.get("no"), before=snap(cur, old_rows), after=snap(new, rows),
                               reason=(body or {}).get("edit_reason"))
        return await detail(iid, user)

    @app.delete("/api/vendor-invoices/{iid}", tags=["vendor-invoice"])
    async def delete_invoice(iid: str, user=Depends(cu)):
        async with _LOCK:
            cur = await get_inv(iid, user)
            if await db().vendor_invoice_payments.find_one({"invoice_id": iid, "status": "Aktif"}, {"_id": 0, "id": 1}):
                raise HTTPException(409, "Invoice sudah memiliki pembayaran aktif. Batalkan pembayaran terlebih dahulu sebelum menghapus invoice.")
            rows = await db().vendor_invoice_allocations.find({"invoice_id": iid}, {"_id": 0}).to_list(5000)
            await db().vendor_invoice_allocations.delete_many({"invoice_id": iid})
            await db().vendor_invoice_keys.delete_one({"id": key_id(cur["supplier_id"], cur["invoice_no"])})
            await db().vendor_invoices.delete_one({"id": iid})
            await db().attachments.update_many({"invoice_id": iid, "is_deleted": False}, {"$set": {"is_deleted": True, "deleted_by": user.get("email"), "deleted_at": server.now_iso()}})
            await server.audit(user, "delete", "invoice", iid, cur.get("no"), before=snap(cur, rows))
        return {"ok": True}

    @app.post("/api/vendor-invoices/{iid}/payments", tags=["vendor-invoice"])
    async def add_payment(iid: str, body: dict, user=Depends(cu)):
        body = body or {}
        async with _LOCK:
            inv = await get_inv(iid, user)
            pdate = req_date(body.get("date"), "Tanggal Pembayaran")
            amt = money(body.get("amount"), "Nilai Dibayar")
            if amt <= 0:
                raise HTTPException(400, "Nilai Dibayar harus lebih dari 0")
            paid, _ = await refresh_paid(iid)
            rem = round(float(inv.get("amount") or 0) - paid, 2)
            if amt > rem + EPS:
                raise HTTPException(409, f"Nilai pembayaran melebihi sisa invoice (Sisa Rp {rem:,.0f}).".replace(",", "."))
            pay = {"id": server.gid(), "invoice_id": iid, "date": pdate, "amount": amt,
                   "reference": str(body.get("reference") or "").strip(), "notes": str(body.get("notes") or "").strip(),
                   "status": "Aktif", "created_by": user.get("email"), "created_by_name": user.get("name"), "created_at": server.now_iso()}
            await db().vendor_invoice_payments.insert_one(pay)
            paid, st = await refresh_paid(iid)
            await server.audit(user, "payment", "invoice", iid, inv.get("no"),
                               after={"tanggal": pdate, "nilai": amt, "referensi": pay["reference"], "sudah_dibayar": paid, "status": st})
        return await detail(iid, user)

    @app.post("/api/vendor-invoices/{iid}/payments/{pid}/cancel", tags=["vendor-invoice"])
    async def cancel_payment(iid: str, pid: str, body: dict = None, user=Depends(cu)):
        reason = str((body or {}).get("reason") or "").strip()
        if not reason:
            raise HTTPException(400, "Alasan pembatalan pembayaran wajib diisi")
        async with _LOCK:
            inv = await get_inv(iid, user)
            pay = await db().vendor_invoice_payments.find_one({"id": pid, "invoice_id": iid}, {"_id": 0})
            if not pay:
                raise HTTPException(404, "Pembayaran tidak ditemukan")
            if pay.get("status") != "Aktif":
                raise HTTPException(409, "Pembayaran ini sudah dibatalkan")
            await db().vendor_invoice_payments.update_one({"id": pid}, {"$set": {
                "status": "Dibatalkan", "cancel_reason": reason, "cancelled_by": user.get("email"), "cancelled_at": server.now_iso()}})
            paid, st = await refresh_paid(iid)
            await server.audit(user, "payment_cancel", "invoice", iid, inv.get("no"), reason=reason,
                               before={"tanggal": pay.get("date"), "nilai": pay.get("amount"), "referensi": pay.get("reference")},
                               after={"sudah_dibayar": paid, "status": st})
        return await detail(iid, user)

    # ------------------------------------------------------------------ lampiran (reuse attachments + storage existing)
    # Invoice -> banyak lampiran (entity "invoice"); Pembayaran -> banyak lampiran (entity "invoice_payment").
    def find_route(path, method):
        return next((r for r in app.router.routes if getattr(r, "path", "") == path and method in (getattr(r, "methods", None) or set())), None)

    async def att_parent(entity, entity_id, user):
        """Tenant (proxy) -> invoice visibility (permission + cakupan divisi). Returns (invoice, payment|None)."""
        if not can(user, "invoice.view"):
            raise HTTPException(403, "Anda tidak memiliki izin untuk melihat data Invoice Vendor.")
        if entity == "invoice_payment":
            pay = await db().vendor_invoice_payments.find_one({"id": entity_id}, {"_id": 0})
            if not pay:
                raise HTTPException(404, "Pembayaran tidak ditemukan")
            return await get_inv(pay["invoice_id"], user), pay
        return await get_inv(entity_id, user), None

    def need_att_write(entity, user):
        if entity == "invoice_payment":
            need_any(user, ["invoice.pay"], "mengelola lampiran pembayaran")
        else:
            need_any(user, ["invoice.create", "invoice.edit"], "mengelola lampiran")

    def att_label(entity):
        return "Pembayaran" if entity == "invoice_payment" else "Invoice"

    r_up = find_route("/api/attachments", "POST")
    if r_up:
        orig_up = r_up.endpoint
        app.router.routes.remove(r_up)

        async def upload(request: Request, file: UploadFile = File(...), entity: str = Form(...), entity_id: str = Form(...),
                         category: str = Form("Lainnya"), note: str = Form("")):
            ent = str(entity or "").strip().lower()
            if ent not in ATT_ENTITIES:
                return await orig_up(request, file, entity, entity_id, category, note)
            user = await cu(request)
            server.require(user, "upload_attachment")
            need_att_write(ent, user)
            inv, pay = await att_parent(ent, str(entity_id or "").strip(), user)
            if pay and pay.get("status") != "Aktif":
                raise HTTPException(409, "Pembayaran sudah dibatalkan; lampiran tidak dapat ditambahkan")
            await _validate_file(file)
            name = file.filename.rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower()
            data = await file.read()
            ct = file.content_type or S.MIME_TYPES.get(ext, "application/octet-stream")
            path = f"{S.APP_NAME}/uploads/{ent}/{server.gid()}.{ext}"
            res = S.put_object(path, data, ct)
            doc = {"id": server.gid(), "storage_path": res["path"], "original_filename": name, "content_type": ct,
                   "size": res.get("size", len(data)), "entity": ent, "entity_id": entity_id, "invoice_id": inv["id"],
                   "category": str(category or "Lainnya")[:100], "note": str(note or "")[:1000], "uploaded_by": user.get("name"),
                   "uploaded_by_email": user.get("email"), "is_deleted": False, "created_at": server.now_iso()}
            try:
                await db().attachments.insert_one(doc)
            except Exception:
                S.delete_object(res["path"])  # penyimpanan gagal -> tidak meninggalkan file yatim
                raise
            await server.audit(user, "upload_file", "invoice", inv["id"], inv.get("no"),
                               after={"file": name, "induk": att_label(ent), "payment_id": (pay or {}).get("id")})
            return {k: v for k, v in doc.items() if k != "storage_path"}
        app.add_api_route("/api/attachments", upload, methods=["POST"], tags=["vendor-invoice"])

    r_list = find_route("/api/attachments", "GET")
    if r_list:
        orig_list = r_list.endpoint
        app.router.routes.remove(r_list)

        async def list_att(entity: str, entity_id: str, user=Depends(cu)):
            if entity in ATT_ENTITIES:
                await att_parent(entity, entity_id, user)
            return await orig_list(entity=entity, entity_id=entity_id, user=user)
        app.add_api_route("/api/attachments", list_att, methods=["GET"], tags=["vendor-invoice"])

    r_dl = find_route("/api/attachments/{aid}/download", "GET")
    if r_dl:
        orig_dl = r_dl.endpoint
        app.router.routes.remove(r_dl)

        async def download(aid: str, request: Request, auth: str = Query(None)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0, "entity": 1, "entity_id": 1})
            if rec and rec.get("entity") in ATT_ENTITIES:
                await att_parent(rec["entity"], rec["entity_id"], await cu(request))
            return await orig_dl(aid=aid, request=request, auth=None)
        app.add_api_route("/api/attachments/{aid}/download", download, methods=["GET"], tags=["vendor-invoice"])

    r_del = find_route("/api/attachments/{aid}", "DELETE")
    if r_del:
        orig_del = r_del.endpoint
        app.router.routes.remove(r_del)

        async def delete_att(aid: str, user=Depends(cu)):
            rec = await db().attachments.find_one({"id": aid, "is_deleted": False}, {"_id": 0})
            if not rec or rec.get("entity") not in ATT_ENTITIES:
                return await orig_del(aid=aid, user=user)
            need_att_write(rec["entity"], user)
            inv, pay = await att_parent(rec["entity"], rec["entity_id"], user)
            await db().attachments.update_one({"id": aid}, {"$set": {"is_deleted": True, "deleted_by": user.get("email"), "deleted_at": server.now_iso()}})
            await server.audit(user, "delete_file", "invoice", inv["id"], inv.get("no"),
                               before={"file": rec.get("original_filename"), "induk": att_label(rec["entity"]), "payment_id": (pay or {}).get("id")})
            return {"ok": True}
        app.add_api_route("/api/attachments/{aid}", delete_att, methods=["DELETE"], tags=["vendor-invoice"])

    # ------------------------------------------------------------------ DO guard + audit scope
    orig_blockers = TM._blockers

    async def blockers(srv, module, did):
        out = await orig_blockers(srv, module, did)
        if module == "do":
            for a in await db().vendor_invoice_allocations.find({"do_id": did}, {"_id": 0, "invoice_id": 1}).to_list(5000):
                inv = await db().vendor_invoices.find_one({"id": a["invoice_id"]}, {"_id": 0, "no": 1, "invoice_no": 1})
                if inv and not any(b.get("id") == a["invoice_id"] for b in out):
                    out.append({"type": "INVOICE VENDOR", "id": a["invoice_id"], "no": inv.get("invoice_no") or inv.get("no")})
        return out
    TM._blockers = blockers

    route = next((r for r in app.router.routes if getattr(r, "path", "") == "/api/audit" and "GET" in (r.methods or set())), None)
    if route:
        orig_audit = route.endpoint
        app.router.routes.remove(route)

        async def audit_list(entity: str = None, entity_id: str = None, limit: int = 300, user=Depends(cu)):
            rows = await orig_audit(entity=entity, entity_id=entity_id, limit=limit, user=user)
            if not any(str(r.get("entity")) == "invoice" for r in rows or []):
                return rows
            ok_view, vis, cache = can(user, "invoice.view"), None if server.is_global(user) else await vis_dos(user), {}
            out = []
            for r in rows:
                if str(r.get("entity")) != "invoice":
                    out.append(r)
                    continue
                if not ok_view:
                    continue
                eid = r.get("entity_id")
                if eid not in cache:
                    inv = await db().vendor_invoices.find_one({"id": eid}, {"_id": 0, "do_ids": 1})
                    cache[eid] = bool(inv) and inv_visible(inv, vis) if vis is not None else True
                if cache[eid]:
                    out.append(r)
            return out
        app.add_api_route("/api/audit", audit_list, methods=["GET"], tags=["vendor-invoice"])
