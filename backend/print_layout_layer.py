"""Editable print layout configuration for all operational transaction documents."""
from fastapi import Depends, HTTPException

MODULES = {
    "mro": ("MRO", "Material Request Order"),
    "ro": ("RO", "Request Order"),
    "po": ("PO", "Purchase Order"),
    "do": ("DO", "Delivery Order / Penerimaan"),
    "mi": ("MI", "Material Issued"),
    "transfer": ("TRF", "Transfer Antar Gudang"),
    "loan": ("LOAN", "Pinjam Antar Gudang"),
    "adjustment": ("ADJ", "Stock Adjustment"),
    "opname": ("OPN", "Stock Opname"),
}

SECTIONS = ["header", "meta", "items", "message", "signatures", "footer"]
COLUMNS = ["item", "qty", "unit", "spk", "price", "discount", "tax", "total", "notes"]
META = ["date", "status", "requester", "receiver", "supplier", "buyer", "payment_term", "delivery_term", "division", "warehouse", "project", "unit", "supplier_invoice", "notes"]


def default_layout(code, title):
    is_po = code == "PO"
    return {
        "code": code,
        "title": "PURCHASE ORDER" if is_po else title,
        "paper_size": "A4",
        "orientation": "portrait",
        "font_family": "Arial",
        "font_size": 11,
        "primary_color": "#17396f" if is_po else "#1e3a8a",
        "margin_mm": 10 if is_po else 12,
        "logo_width_mm": 24 if is_po else 28,
        "header_style": "classic",
        "template_style": "real_reference" if is_po else "generic",
        "show_logo": True,
        "show_company_address": True,
        "show_qr": False if is_po else True,
        "show_message": True,
        "show_signatures": True,
        "sections": list(SECTIONS),
        "columns": ["item", "qty", "unit", "price", "discount", "total"] if is_po else ["item", "qty", "unit", "spk", "price", "total"],
        "meta_fields": list(META),
        "signature_labels": ["Approved by,", "Signed by,"] if is_po else ["Dibuat Oleh", "Diperiksa Oleh", "Disetujui Oleh"],
        "footer_text": "" if is_po else "Dokumen ini dibuat oleh sistem ProcureFlow.",
        # PO REAL reference fields. Blank values fall back to company/master data.
        "po_delivery_company_name": "",
        "po_bill_company_name": "",
        "po_bill_address": "",
        "po_bill_contact": "",
        "po_bill_phone": "",
        "po_approved_name": "",
        "po_approved_company": "",
    }


def _normalize_one(raw, code, title):
    src = raw if isinstance(raw, dict) else {}
    out = default_layout(code, title)
    allowed_scalar = {
        "title", "paper_size", "orientation", "font_family", "font_size", "primary_color", "margin_mm", "logo_width_mm",
        "header_style", "template_style", "show_logo", "show_company_address", "show_qr", "show_message", "show_signatures", "footer_text",
        "po_delivery_company_name", "po_bill_company_name", "po_bill_address", "po_bill_contact", "po_bill_phone", "po_approved_name", "po_approved_company",
    }
    for k in allowed_scalar:
        if k in src:
            out[k] = src[k]
    sections = [x for x in (src.get("sections") or []) if x in SECTIONS]
    columns = [x for x in (src.get("columns") or []) if x in COLUMNS]
    meta = [x for x in (src.get("meta_fields") or []) if x in META]
    signatures = [str(x)[:100] for x in (src.get("signature_labels") or []) if str(x).strip()][:5]
    if sections:
        out["sections"] = sections
    if columns:
        out["columns"] = columns
    if meta:
        out["meta_fields"] = meta
    if signatures:
        out["signature_labels"] = signatures
    try:
        out["font_size"] = max(8, min(16, float(out["font_size"])))
        out["margin_mm"] = max(5, min(30, float(out["margin_mm"])))
        out["logo_width_mm"] = max(10, min(60, float(out["logo_width_mm"])))
    except (TypeError, ValueError):
        raise HTTPException(400, "Ukuran font, margin, atau logo tidak valid")
    if out["paper_size"] not in ("A4", "A5", "Letter"):
        out["paper_size"] = "A4"
    if out["orientation"] not in ("portrait", "landscape"):
        out["orientation"] = "portrait"
    if out["header_style"] not in ("classic", "minimal", "boxed"):
        out["header_style"] = "classic"
    if out["template_style"] not in ("generic", "real_reference"):
        out["template_style"] = "real_reference" if code == "PO" else "generic"
    if code != "PO" and out["template_style"] == "real_reference":
        out["template_style"] = "generic"
    if len(str(out.get("footer_text") or "")) > 1000:
        raise HTTPException(400, "Teks footer terlalu panjang")
    for k in ("po_delivery_company_name", "po_bill_company_name", "po_bill_address", "po_bill_contact", "po_bill_phone", "po_approved_name", "po_approved_company"):
        if len(str(out.get(k) or "")) > 1000:
            raise HTTPException(400, f"{k} terlalu panjang")
    return out


def _normalize_modules(raw):
    src = (raw or {}).get("modules") if isinstance(raw, dict) else {}
    src = src if isinstance(src, dict) else {}
    return {key: _normalize_one(src.get(key), code, title) for key, (code, title) in MODULES.items()}


def install(server):
    app = server.app

    @app.get("/api/settings/print_layouts", tags=["settings"])
    async def get_print_layouts(user=Depends(server.current_user)):
        server.require(user, "view")
        row = await server.db.settings.find_one({"id": "print_layouts"}, {"_id": 0}) or {}
        return {"id": "print_layouts", "modules": _normalize_modules(row)}

    @app.put("/api/settings/print_layouts", tags=["settings"])
    async def put_print_layouts(body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        modules = _normalize_modules(body)
        await server.db.settings.update_one(
            {"id": "print_layouts"},
            {"$set": {"id": "print_layouts", "modules": modules, "updated_by": user.get("email"), "updated_at": server.now_iso()}},
            upsert=True,
        )
        await server.audit(user, "edit", "settings", "print_layouts", "Layout Dokumen")
        return {"id": "print_layouts", "modules": modules}
