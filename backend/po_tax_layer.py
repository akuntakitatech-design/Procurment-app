"""F2 — Route PPN untuk form PO (backend = sumber perhitungan resmi).

GET  /api/po/tax-options?date=YYYY-MM-DD  -> Jenis PPN dari Master Pajak (label, kelengkapan, masa berlaku).
POST /api/po/tax-preview                 -> hitung resmi (engine yang sama dengan simpan) tanpa menulis apa pun.
     body: header PO + lines; `po_id` opsional (edit: versi & snapshot baris dari dokumen tersimpan).
GET  /api/po/tax-readiness               -> audit READ-ONLY go-live: Master Pajak belum lengkap + Supplier Non-PKP berisiko.
Izin modul `po` diperiksa ACCESS_HOOK (path /api/po/*); preview nominal butuh `view_purchase_price`.
"""
from copy import deepcopy

from fastapi import Depends

import po_tax


def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731

    async def tax_options(date: str | None = None, user=Depends(server.current_user)):
        rows = await db().taxes.find({"is_active": {"$ne": False}}, {"_id": 0}).to_list(500)
        opts = [po_tax.tax_option(t, date) for t in rows]
        opts.sort(key=lambda o: (not o["ready"], o.get("trx_code") or "99", str(o.get("name") or "")))
        return {"items": opts, "date": date, "ppnbm_enabled": False}

    async def tax_preview(body: dict, user=Depends(server.current_user)):
        server.require(user, "view_purchase_price")
        body = deepcopy(body or {})
        doc, old = None, None
        if body.get("po_id"):
            import division_visibility_layer as DV  # akses dokumen = aturan detail PO (divisi / approver yang ditugaskan)
            doc = await DV._require_doc_view(server, "po", str(body["po_id"]), user)
            old = await db().po_lines.find({"po_id": doc["id"]}, {"_id": 0}).to_list(2000)
            body.setdefault("supplier_id", doc.get("supplier_id"))
        import transaction_mutation_layer as TM  # normalisasi satuan (UoM) sama persis dengan jalur simpan
        body, _m = await TM._normalize_qty_body(server, "po", body)
        lines = [dict(x) for x in (body.get("lines") or []) if not (x.get("qty") is not None and float(x.get("qty") or 0) <= 0)]
        body["lines"] = lines
        version = await po_tax.prepare_po(db(), body, doc=doc, old_lines=old)
        import doc_procurement as DP
        out, totals = DP.compute_po_totals(body, lines)
        return po_tax.preview_payload(out, totals, version)

    async def tax_readiness(user=Depends(server.current_user)):
        """Audit READ-ONLY kesiapan PPN sebelum go-live (tidak menulis apa pun, tanpa nominal harga):
        - Jenis PPN Master Pajak yang belum lengkap (tidak dapat dipakai PO v2);
        - Supplier Non-PKP yang masih memiliki Default Pajak bertarif > 0;
        - Supplier Non-PKP yang memiliki PO aktif ber-PPN (dokumen lama) -> perlu dicek/dibetulkan status PKP-nya."""
        taxes = await db().taxes.find({"is_active": {"$ne": False}}, {"_id": 0}).to_list(500)
        incomplete = [{"id": t.get("id"), "code": t.get("code"), "name": t.get("name"), "issues": po_tax.tax_master_issues(t)}
                      for t in taxes if po_tax.tax_master_issues(t)]
        rated = {t.get("id") for t in taxes if float(t.get("rate") or 0) > 0}
        sups = await db().suppliers.find({"pkp": {"$ne": True}}, {"_id": 0, "id": 1, "code": 1, "name": 1, "pkp": 1, "default_tax_id": 1,
                                                                   "is_active": 1}).to_list(5000)
        sup_ids = [s["id"] for s in sups if s.get("id")]
        pos = await db().po.find({"supplier_id": {"$in": sup_ids}, "cancelled": {"$ne": True}, "tax_total": {"$gt": 0}},
                                 {"_id": 0, "no": 1, "supplier_id": 1, "status": 1}).to_list(20000) if sup_ids else []
        by_sup = {}
        for p in pos:
            by_sup.setdefault(p.get("supplier_id"), []).append(p.get("no"))
        rows = []
        for s in sups:
            reasons = []
            if s.get("default_tax_id") in rated:
                reasons.append("Default Pajak bertarif PPN")
            if by_sup.get(s.get("id")):
                reasons.append("Memiliki PO ber-PPN")
            if reasons:
                nos = sorted(x for x in by_sup.get(s.get("id"), []) if x)
                rows.append({"id": s.get("id"), "code": s.get("code"), "name": s.get("name"), "reasons": reasons,
                             "po_count": len(by_sup.get(s.get("id"), [])), "po_numbers": nos[:10]})
        rows.sort(key=lambda r: (-r["po_count"], str(r.get("name") or "")))
        return {"read_only": True, "incomplete_taxes": incomplete, "non_pkp_suppliers": rows,
                "ready": not incomplete and not rows}

    for path, fn, meth in (("/api/po/tax-options", tax_options, "GET"), ("/api/po/tax-preview", tax_preview, "POST"),
                           ("/api/po/tax-readiness", tax_readiness, "GET")):
        app.add_api_route(path, fn, methods=[meth], tags=["po-tax"])
        # Harus didahulukan dari route generik /api/po/{did}.
        r = app.router.routes.pop()
        app.router.routes.insert(0, r)
