"""Transmittal Invoice Vendor — serah terima dokumen invoice ke departemen/tujuan.

Aditif: TIDAK mengubah perhitungan invoice (PPN/DP/pembayaran/outstanding), stok, MWA, maupun HPP.
Transmittal hanya mencatat pengiriman dokumen:
  Draft -> Dikirim -> Diterima | Dikembalikan
Invoice tidak boleh berada pada dua Transmittal AKTIF (Draft/Dikirim) sekaligus; pengiriman ulang
setelah Dikembalikan tercatat sebagai transmittal baru sehingga historinya jelas.

Urutan guard: Tenant (proxy) -> Permission -> Cakupan Divisi (lewat DO invoice) -> Business Rule.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException

import mariadb_motor

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("Draft", "Dikirim", "Diterima", "Dikembalikan")
ACTIVE = {"Draft", "Dikirim"}
TRANSITIONS = {"Draft": {"Dikirim"}, "Dikirim": {"Diterima", "Dikembalikan"}, "Diterima": {"Dikembalikan"}, "Dikembalikan": set()}
_LOCK = asyncio.Lock()
mariadb_motor.STRICT_PK_COLLECTIONS.add("invoice_transmittal_items")


def today():
    return datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()


def req_date(v, label):
    s = str(v or "").strip()[:10]
    if not DATE_RE.match(s):
        raise HTTPException(400, f"{label} wajib diisi (format tanggal tidak valid)")
    return s


def checklist_of(inv):
    # Import lazy: vendor_invoice_layer mengimpor rantai server -> production_bootstrap (hindari circular import).
    from vendor_invoice_layer import CHECK_KEYS, CHECK_VALUES, CHECK_DEFAULT
    raw = inv.get("doc_checklist") if isinstance(inv.get("doc_checklist"), dict) else {}
    return {k: (str(raw.get(k) or "").strip() if str(raw.get(k) or "").strip() in CHECK_VALUES else CHECK_DEFAULT) for k in CHECK_KEYS}


def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731
    cu = server.current_user

    def can(user, key):
        return user.get("role") == "admin" or key in set(user.get("effective_permissions") or [])

    def need(user, key, verb):
        if not can(user, key):
            raise HTTPException(403, f"Anda tidak memiliki izin untuk {verb} Transmittal Invoice.")

    # ------------------------------------------------------------------ helpers
    async def inv_of(iid, user):
        inv = await db().vendor_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv:
            raise HTTPException(404, "Invoice Vendor tidak ditemukan")
        if not server.is_global(user):
            for d in inv.get("do_ids") or []:
                if not await server.ACCESS_DOC_VISIBLE("do", d, user):
                    raise HTTPException(403, "Invoice ini berada di luar cakupan divisi Anda.")
        return inv

    async def active_links(exclude_tid=None):
        """Peta invoice_id -> transmittal aktif (Draft/Dikirim)."""
        trs = await db().invoice_transmittals.find({"status": {"$in": list(ACTIVE)}}, {"_id": 0, "id": 1, "no": 1, "status": 1}).to_list(10000)
        ids = [t["id"] for t in trs if t["id"] != exclude_tid]
        if not ids:
            return {}
        items = await db().invoice_transmittal_items.find({"transmittal_id": {"$in": ids}}, {"_id": 0, "invoice_id": 1, "transmittal_id": 1}).to_list(200000)
        tmap = {t["id"]: t for t in trs}
        return {i["invoice_id"]: tmap.get(i["transmittal_id"]) for i in items if i.get("transmittal_id") in tmap}

    async def snapshot(invoice_ids, user, exclude_tid=None):
        """Ambil data invoice (vendor, no invoice, faktur pajak, PO, nilai, checklist) untuk item transmittal."""
        if not invoice_ids:
            raise HTTPException(400, "Pilih minimal satu invoice")
        uniq = list(dict.fromkeys(invoice_ids))
        if len(uniq) != len(invoice_ids):
            raise HTTPException(400, "Invoice yang sama tidak boleh dipilih dua kali")
        active = await active_links(exclude_tid)
        rows = []
        for iid in uniq:
            inv = await inv_of(iid, user)
            busy = active.get(iid)
            if busy:
                raise HTTPException(409, f"Invoice {inv.get('invoice_no') or inv.get('no')} masih berada pada Transmittal aktif {busy.get('no')} ({busy.get('status')}).")
            sup = await db().suppliers.find_one({"id": inv.get("supplier_id")}, {"_id": 0, "id": 1, "name": 1}) or {}
            rows.append({
                "invoice_id": iid,
                "invoice_no": inv.get("invoice_no"),
                "invoice_doc_no": inv.get("no"),
                "invoice_date": inv.get("invoice_date"),
                "supplier_id": inv.get("supplier_id"),
                "supplier_name": sup.get("name") or inv.get("supplier_name") or "",
                "tax_invoice_no": str(inv.get("tax_invoice_no") or ""),
                "tax_invoice_date": str(inv.get("tax_invoice_date") or ""),
                "po_nos": str(inv.get("trace_po") or ""),
                "do_nos": ", ".join(inv.get("do_nos") or []) if isinstance(inv.get("do_nos"), list) else str(inv.get("do_nos") or ""),
                "amount": round(float(inv.get("amount") or 0), 2),
                "checklist": checklist_of(inv),
                "division_ids": list(inv.get("division_ids") or []),
            })
        return rows

    def summarize(rows):
        suppliers = list(dict.fromkeys([r["supplier_name"] for r in rows if r.get("supplier_name")]))
        return {
            "invoice_count": len(rows),
            "total_amount": round(sum(float(r.get("amount") or 0) for r in rows), 2),
            "suppliers": ", ".join(suppliers),
            "supplier_ids": list(dict.fromkeys([r["supplier_id"] for r in rows if r.get("supplier_id")])),
            "division_ids": sorted({d for r in rows for d in (r.get("division_ids") or [])}),
            "invoice_nos": ", ".join([str(r.get("invoice_no") or "") for r in rows]),
        }

    async def items_of(tid):
        return await db().invoice_transmittal_items.find({"transmittal_id": tid}, {"_id": 0}).sort("created_at", 1).to_list(5000)

    async def get_tid(tid, user):
        t = await db().invoice_transmittals.find_one({"id": tid}, {"_id": 0})
        if not t:
            raise HTTPException(404, "Transmittal tidak ditemukan")
        if not server.is_global(user):
            for iid in t.get("invoice_ids") or []:
                await inv_of(iid, user)
        return t

    async def detail(t, user):
        items = await items_of(t["id"])
        out = dict(t)
        out["items"] = items
        out["history"] = await db().audit_logs.find({"entity": "invoice_transmittal", "entity_id": t["id"]}, {"_id": 0}).sort("at", -1).to_list(500)
        proof = None
        if t.get("proof_attachment_id"):
            proof = await db().attachments.find_one({"id": t["proof_attachment_id"], "is_deleted": False},
                                                    {"_id": 0, "storage_path": 0})
        out["proof"] = proof
        out["allowed_actions"] = sorted(TRANSITIONS.get(t.get("status"), set()))
        return out

    def header_fields(body, cur=None):
        cur = cur or {}
        body = body or {}
        out = {
            "date": req_date(body.get("date", cur.get("date") or today()), "Tanggal Pengiriman"),
            "destination": str(body.get("destination", cur.get("destination")) or "").strip()[:200],
            "sender_name": str(body.get("sender_name", cur.get("sender_name")) or "").strip()[:200],
            "receiver_name": str(body.get("receiver_name", cur.get("receiver_name")) or "").strip()[:200],
            "notes": str(body.get("notes", cur.get("notes")) or "").strip()[:2000],
        }
        if not out["destination"]:
            raise HTTPException(400, "Tujuan/Departemen wajib diisi")
        if not out["sender_name"]:
            raise HTTPException(400, "Pengirim wajib diisi")
        return out

    async def audit(user, action, t, reason=None, before=None, after=None):
        await server.audit(user, action, "invoice_transmittal", t["id"], t.get("no"), reason=reason, before=before, after=after)

    # ------------------------------------------------------------------ routes
    @app.get("/api/invoice-transmittals", tags=["transmittal"])
    async def list_transmittals(user=Depends(cu)):
        need(user, "transmittal.view", "melihat")
        rows = await db().invoice_transmittals.find({}, {"_id": 0}).to_list(50000)
        if server.is_global(user):
            return rows
        allowed, out = set(), []
        # Cakupan divisi: transmittal hanya terlihat bila SEMUA invoice-nya berada dalam cakupan user.
        for t in rows:
            ids = t.get("invoice_ids") or []
            ok = True
            for iid in ids:
                try:
                    await inv_of(iid, user)
                except HTTPException:
                    ok = False
                    break
            if ok:
                out.append(t)
        return out

    @app.get("/api/invoice-transmittals/eligible-invoices", tags=["transmittal"])
    async def eligible_invoices(user=Depends(cu)):
        """Invoice yang boleh dibuatkan transmittal (belum ada di transmittal aktif)."""
        need(user, "transmittal.view", "melihat")
        active = await active_links()
        invs = await db().vendor_invoices.find({}, {"_id": 0}).to_list(100000)
        sups = {s["id"]: s.get("name") for s in await db().suppliers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)}
        out = []
        for inv in invs:
            if inv["id"] in active:
                continue
            if not server.is_global(user):
                visible = True
                for d in inv.get("do_ids") or []:
                    if not await server.ACCESS_DOC_VISIBLE("do", d, user):
                        visible = False
                        break
                if not visible:
                    continue
            out.append({
                "id": inv["id"], "no": inv.get("no"), "invoice_no": inv.get("invoice_no"),
                "invoice_date": inv.get("invoice_date"), "supplier_name": sups.get(inv.get("supplier_id")) or "",
                "tax_invoice_no": str(inv.get("tax_invoice_no") or ""), "po_nos": str(inv.get("trace_po") or ""),
                "do_nos": str(inv.get("do_nos") or ""), "amount": round(float(inv.get("amount") or 0), 2),
                "doc_checklist": checklist_of(inv),
            })
        return out

    @app.get("/api/invoice-transmittals/by-invoice/{iid}", tags=["transmittal"])
    async def transmittals_by_invoice(iid: str, user=Depends(cu)):
        need(user, "transmittal.view", "melihat")
        await inv_of(iid, user)
        items = await db().invoice_transmittal_items.find({"invoice_id": iid}, {"_id": 0, "transmittal_id": 1}).to_list(5000)
        tids = [i["transmittal_id"] for i in items if i.get("transmittal_id")]
        if not tids:
            return []
        return await db().invoice_transmittals.find({"id": {"$in": tids}}, {"_id": 0}).sort("created_at", -1).to_list(5000)

    @app.post("/api/invoice-transmittals", tags=["transmittal"])
    async def create_transmittal(body: dict, user=Depends(cu)):
        need(user, "transmittal.create", "membuat")
        async with _LOCK:
            body = body or {}
            head = header_fields(body)
            rows = await snapshot([str(x) for x in (body.get("invoice_ids") or [])], user)
            tid = server.gid()
            no = await server.next_number("TRN")
            doc = {"id": tid, "no": no, **head, **summarize(rows), "status": "Draft",
                   "invoice_ids": [r["invoice_id"] for r in rows],
                   "created_by": user.get("email"), "created_by_name": user.get("name"),
                   "created_at": server.now_iso(), "updated_at": server.now_iso()}
            await db().invoice_transmittals.insert_one(doc)
            for r in rows:
                await db().invoice_transmittal_items.insert_one({"id": server.gid(), "transmittal_id": tid, **r,
                                                                 "created_by": user.get("email"), "created_at": server.now_iso()})
            await audit(user, "create", doc, after={"items": len(rows), "nilai": doc["total_amount"]})
        return await detail(doc, user)

    @app.get("/api/invoice-transmittals/{tid}", tags=["transmittal"])
    async def get_transmittal(tid: str, user=Depends(cu)):
        need(user, "transmittal.view", "melihat")
        return await detail(await get_tid(tid, user), user)

    @app.put("/api/invoice-transmittals/{tid}", tags=["transmittal"])
    async def edit_transmittal(tid: str, body: dict, user=Depends(cu)):
        need(user, "transmittal.edit", "mengubah")
        async with _LOCK:
            t = await get_tid(tid, user)
            if t.get("status") != "Draft":
                raise HTTPException(409, "Transmittal yang sudah dikirim tidak dapat diubah. Buat transmittal baru bila perlu koreksi.")
            body = body or {}
            head = header_fields(body, t)
            values = dict(head)
            if "invoice_ids" in body:
                old_items = await items_of(tid)
                rows = await snapshot([str(x) for x in (body.get("invoice_ids") or [])], user, exclude_tid=tid)
                await db().invoice_transmittal_items.delete_many({"transmittal_id": tid})
                for r in rows:
                    await db().invoice_transmittal_items.insert_one({"id": server.gid(), "transmittal_id": tid, **r,
                                                                     "created_by": user.get("email"), "created_at": server.now_iso()})
                values.update({**summarize(rows), "invoice_ids": [r["invoice_id"] for r in rows]})
                await audit(user, "edit_items", t, before={"items": len(old_items)}, after={"items": len(rows)})
            await db().invoice_transmittals.update_one({"id": tid}, {"$set": {**values, "updated_at": server.now_iso(), "updated_by": user.get("email")}})
            new = await db().invoice_transmittals.find_one({"id": tid}, {"_id": 0})
            await audit(user, "edit", new, before={k: t.get(k) for k in head}, after={k: new.get(k) for k in head})
        return await detail(new, user)

    @app.delete("/api/invoice-transmittals/{tid}", tags=["transmittal"])
    async def delete_transmittal(tid: str, user=Depends(cu)):
        need(user, "transmittal.delete", "menghapus")
        async with _LOCK:
            t = await get_tid(tid, user)
            if t.get("status") != "Draft":
                raise HTTPException(409, "Hanya Transmittal berstatus Draft yang dapat dihapus. Gunakan status Dikembalikan untuk transmittal yang sudah dikirim.")
            await db().invoice_transmittal_items.delete_many({"transmittal_id": tid})
            await db().invoice_transmittals.delete_one({"id": tid})
            await audit(user, "delete", t, before={"status": t.get("status"), "items": t.get("invoice_count")})
        return {"ok": True}

    async def move(tid, user, target, reason=None, extra=None, action=None):
        async with _LOCK:
            t = await get_tid(tid, user)
            cur = t.get("status")
            if target not in TRANSITIONS.get(cur, set()):
                raise HTTPException(409, f"Status Transmittal {cur} tidak dapat diubah menjadi {target}.")
            patch = {"status": target, "updated_at": server.now_iso(), "updated_by": user.get("email"), **(extra or {})}
            await db().invoice_transmittals.update_one({"id": tid}, {"$set": patch})
            new = await db().invoice_transmittals.find_one({"id": tid}, {"_id": 0})
            await audit(user, action or target.lower(), new, reason=reason, before={"status": cur}, after={"status": target, **(extra or {})})
        return await detail(new, user)

    @app.post("/api/invoice-transmittals/{tid}/send", tags=["transmittal"])
    async def send_transmittal(tid: str, body: dict = None, user=Depends(cu)):
        """Menandai dokumen terkirim. Cetak TIDAK memanggil endpoint ini (cetak tidak mengubah status)."""
        need(user, "transmittal.edit", "mengirim")
        extra = {"sent_at": server.now_iso(), "sent_by": user.get("email"), "sent_by_name": user.get("name")}
        return await move(tid, user, "Dikirim", reason=str((body or {}).get("note") or "").strip() or None, extra=extra, action="send")

    @app.post("/api/invoice-transmittals/{tid}/receive", tags=["transmittal"])
    async def receive_transmittal(tid: str, body: dict = None, user=Depends(cu)):
        need(user, "transmittal.receive", "menerima")
        body = body or {}
        proof_id = str(body.get("proof_attachment_id") or "").strip()
        extra = {"received_at": server.now_iso(), "received_by": user.get("email"), "received_by_name": user.get("name")}
        if str(body.get("receiver_name") or "").strip():
            extra["receiver_name"] = str(body.get("receiver_name")).strip()[:200]
        if proof_id:
            att = await db().attachments.find_one({"id": proof_id, "is_deleted": False}, {"_id": 0, "entity": 1, "entity_id": 1, "invoice_id": 1})
            if not att:
                raise HTTPException(404, "Bukti serah terima tidak ditemukan")
            t = await get_tid(tid, user)
            if att.get("entity") != "invoice" or att.get("invoice_id") not in (t.get("invoice_ids") or []):
                raise HTTPException(400, "Bukti serah terima harus lampiran dari invoice pada transmittal ini")
            extra["proof_attachment_id"] = proof_id
        return await move(tid, user, "Diterima", reason=str(body.get("note") or "").strip() or None, extra=extra, action="receive")

    @app.post("/api/invoice-transmittals/{tid}/return", tags=["transmittal"])
    async def return_transmittal(tid: str, body: dict = None, user=Depends(cu)):
        need(user, "transmittal.receive", "mengembalikan")
        reason = str((body or {}).get("reason") or "").strip()
        if not reason:
            raise HTTPException(400, "Alasan pengembalian wajib diisi")
        extra = {"returned_at": server.now_iso(), "returned_by": user.get("email"), "returned_by_name": user.get("name"), "return_reason": reason[:1000]}
        return await move(tid, user, "Dikembalikan", reason=reason, extra=extra, action="return")

    @app.get("/api/invoice-transmittals/{tid}/print", tags=["transmittal"])
    async def print_transmittal(tid: str, user=Depends(cu)):
        """Data cetak A4. Tidak mengubah status (cetak != kirim)."""
        need(user, "transmittal.print", "mencetak")
        t = await get_tid(tid, user)
        out = await detail(t, user)
        out["company"] = await db().settings.find_one({"id": "company"}, {"_id": 0}) or {}
        return out
