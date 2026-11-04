"""DO Saldo Awal — dokumen DO historis (sebelum periode berjalan) yang nilainya diinput manual.

Dokumen disimpan di koleksi `do` dengan penanda `is_opening: true` supaya otomatis
ikut terpilih di form Invoice Vendor (No. DO + Nilai DO), tetapi:
- tidak memiliki baris barang / tidak menggerakkan stok maupun PO outstanding;
- nilai dihitung dari DPP + PPN yang diinput (bukan rasio baris PO);
- No. PO / RO / MRO / SPK disimpan sebagai teks referensi.
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import Depends, HTTPException

MAX_TEXT = 120


def _txt(value, label, required=False, max_len=MAX_TEXT):
    out = str(value or "").strip()
    if required and not out:
        raise HTTPException(400, f"{label} wajib diisi")
    if len(out) > max_len:
        raise HTTPException(400, f"{label} maksimal {max_len} karakter")
    return out


def _money(value, label):
    try:
        num = round(float(value or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{label} harus berupa angka")
    if num < 0:
        raise HTTPException(400, f"{label} tidak boleh negatif")
    return num


def _date(value):
    raw = str(value or "").strip()[:10]
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Tanggal DO harus format YYYY-MM-DD")
    return raw


def install(server):
    app = server.app

    def allowed_divisions(user):
        return None if server.is_global(user) else {str(x) for x in (user.get("divisions") or []) if x}

    def scope_ok(user, division_id):
        alw = allowed_divisions(user)
        return alw is None or str(division_id) in alw

    async def no_exists(no, exclude_id=None):
        for candidate in {no, no.upper(), no.lower()}:
            hit = await server.db.do.find_one({"no": candidate}, {"_id": 0, "id": 1})
            if hit and hit.get("id") != exclude_id:
                return True
        return False

    async def billed_by_do(do_ids):
        if not do_ids:
            return {}
        rows = await server.db.vendor_invoice_allocations.find({"do_id": {"$in": list(do_ids)}},
                                                               {"_id": 0, "do_id": 1, "amount": 1}).to_list(100000)
        out = {}
        for r in rows:
            out[r["do_id"]] = round(out.get(r["do_id"], 0.0) + float(r.get("amount") or 0), 2)
        return out

    async def names():
        sups = {x["id"]: x.get("legal_name") or x.get("name") or ""
                for x in await server.db.suppliers.find({}, {"_id": 0, "id": 1, "name": 1, "legal_name": 1}).to_list(10000)}
        divs = {x["id"]: x.get("name") for x in await server.db.divisions.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)}
        projs = {x["id"]: x.get("name") for x in await server.db.projects.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)}
        return sups, divs, projs

    def shape(doc, sups, divs, projs, billed):
        dpp, ppn = round(float(doc.get("dpp") or 0), 2), round(float(doc.get("ppn") or 0), 2)
        total = round(dpp + ppn, 2)
        used = round(float(billed or 0), 2)
        return {
            "id": doc.get("id"), "no": doc.get("no"), "date": doc.get("date"),
            "supplier_id": doc.get("supplier_id"), "supplier_name": sups.get(doc.get("supplier_id")) or doc.get("supplier_name"),
            "division_id": doc.get("division_id"), "division_name": divs.get(doc.get("division_id")),
            "project_id": doc.get("project_id"), "project_name": projs.get(doc.get("project_id")),
            "po_no": doc.get("po_no_text") or "", "ro_no": doc.get("ro_no_text") or "",
            "mro_no": doc.get("mro_no_text") or "", "spk": doc.get("spk_text") or "",
            "dpp": dpp, "ppn": ppn, "do_value": total, "billed": used,
            "remaining": round(total - used, 2), "notes": doc.get("notes") or "",
            "status": doc.get("status") or "Posted", "created_at": doc.get("created_at"),
            "created_by": doc.get("created_by"),
        }

    def validate_refs(body):
        payload = body or {}
        return {
            "no": _txt(payload.get("no"), "No. DO", required=True, max_len=64),
            "date": _date(payload.get("date")),
            "supplier_id": _txt(payload.get("supplier_id"), "Supplier", required=True),
            "division_id": _txt(payload.get("division_id"), "Divisi", required=True),
            "project_id": _txt(payload.get("project_id"), "Proyek") or None,
            "po_no_text": _txt(payload.get("po_no"), "No. PO", max_len=64),
            "ro_no_text": _txt(payload.get("ro_no"), "No. RO", max_len=64),
            "mro_no_text": _txt(payload.get("mro_no"), "No. MRO", max_len=64),
            "spk_text": _txt(payload.get("spk"), "SPK", max_len=64),
            "dpp": _money(payload.get("dpp"), "DPP"),
            "ppn": _money(payload.get("ppn"), "PPN"),
            "notes": _txt(payload.get("notes"), "Catatan", max_len=500),
        }

    async def validate_targets(payload, user, exclude_id=None):
        if payload["dpp"] + payload["ppn"] <= 0:
            raise HTTPException(400, "Nilai DO (DPP + PPN) harus lebih dari 0")
        if not await server.db.suppliers.find_one({"id": payload["supplier_id"]}, {"_id": 0, "id": 1}):
            raise HTTPException(400, "Supplier tidak ditemukan")
        if not await server.db.divisions.find_one({"id": payload["division_id"]}, {"_id": 0, "id": 1}):
            raise HTTPException(400, "Divisi tidak ditemukan")
        if not scope_ok(user, payload["division_id"]):
            raise HTTPException(403, "Tidak dapat menggunakan divisi di luar kewenangan user")
        if payload["project_id"] and not await server.db.projects.find_one({"id": payload["project_id"]}, {"_id": 0, "id": 1}):
            raise HTTPException(400, "Proyek tidak ditemukan")
        if await no_exists(payload["no"], exclude_id):
            raise HTTPException(409, f"No. DO {payload['no']} sudah dipakai dokumen lain")

    async def load_opening(did):
        doc = await server.db.do.find_one({"id": did, "is_opening": True}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "DO saldo awal tidak ditemukan")
        return doc

    def assert_not_billed(billed, no, action):
        if float(billed or 0) > 0:
            raise HTTPException(409, f"DO {no} sudah dipakai invoice, tidak dapat {action}. "
                                     "Batalkan alokasi invoice terlebih dahulu.")

    def require_opening(user):
        """Izin khusus `do.opening`: tidak semua pemegang akses DO boleh membuat saldo awal."""
        if not server.has_perm(user, "do.opening"):
            raise HTTPException(403, "Anda tidak memiliki izin mengakses DO Saldo Awal.")

    # ------------------------------------------------------------------ routes
    @app.get("/api/opening-dos", tags=["opening-do"])
    async def list_opening(user=Depends(server.current_user)):
        require_opening(user)
        docs = await server.db.do.find({"is_opening": True}, {"_id": 0}).sort("date", -1).to_list(20000)
        alw = allowed_divisions(user)
        if alw is not None:
            docs = [d for d in docs if str(d.get("division_id") or "") in alw]
        sups, divs, projs = await names()
        billed = await billed_by_do([d["id"] for d in docs if d.get("id")])
        return [shape(d, sups, divs, projs, billed.get(d["id"], 0.0)) for d in docs]

    @app.post("/api/opening-dos", tags=["opening-do"])
    async def create_opening(body: dict = None, user=Depends(server.current_user)):
        require_opening(user)
        payload = validate_refs(body)
        await validate_targets(payload, user)
        doc = {
            "id": server.gid(), "is_opening": True, "status": "Posted",
            **payload,
            "opening_value": round(payload["dpp"] + payload["ppn"], 2),
            "created_at": server.now_iso(), "created_by": user.get("email"),
            "created_by_name": user.get("name"),
        }
        await server.db.do.insert_one(doc)
        await server.audit(user, "create", "opening_do", doc["id"], doc["no"])
        sups, divs, projs = await names()
        return shape(doc, sups, divs, projs, 0.0)

    @app.put("/api/opening-dos/{did}", tags=["opening-do"])
    async def update_opening(did: str, body: dict = None, user=Depends(server.current_user)):
        require_opening(user)
        old = await load_opening(did)
        billed = (await billed_by_do([did])).get(did, 0.0)
        assert_not_billed(billed, old.get("no"), "diubah")
        payload = validate_refs(body)
        await validate_targets(payload, user, exclude_id=did)
        payload["opening_value"] = round(payload["dpp"] + payload["ppn"], 2)
        await server.db.do.update_one({"id": did}, {"$set": {**payload, "updated_at": server.now_iso(),
                                                             "updated_by": user.get("email")}})
        doc = await load_opening(did)
        await server.audit(user, "edit", "opening_do", did, doc.get("no"), before=old, after=doc)
        sups, divs, projs = await names()
        return shape(doc, sups, divs, projs, billed)

    @app.delete("/api/opening-dos/{did}", tags=["opening-do"])
    async def delete_opening(did: str, user=Depends(server.current_user)):
        require_opening(user)
        doc = await load_opening(did)
        billed = (await billed_by_do([did])).get(did, 0.0)
        assert_not_billed(billed, doc.get("no"), "dihapus")
        await server.db.do.delete_one({"id": did, "is_opening": True})
        await server.audit(user, "delete", "opening_do", did, doc.get("no"), before=doc)
        return {"ok": True}
