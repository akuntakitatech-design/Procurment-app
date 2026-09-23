"""PO outbound email and configurable PO signature image.

Rules:
- PO email can only be sent after approval (Approved/Partially Received/Fully Received).
- Draft/waiting/rejected/cancelled POs are rejected server-side, not only hidden in UI.
- PO signature is stored using the configured attachment storage driver and referenced
  from a dedicated settings record so layout saves cannot make it disappear.
"""
from email.message import EmailMessage
from html import escape

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

import email_outbound_layer as E
import storage as S

APPROVED_STATUSES = {"approved", "partially received", "fully received"}
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
SIGNATURE_SETTING_ID = "po_signature"
LEGACY_LAYOUT_SETTING_ID = "print_layouts"


def _is_approved(doc):
    return str((doc or {}).get("status") or "").strip().lower() in APPROVED_STATUSES


def _money(v):
    try:
        return f"{float(v or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    except Exception:
        return str(v or "0")


async def _signature_row(server):
    """Read dedicated signature settings, with fallback for already-uploaded legacy data."""
    row = await server.db.settings.find_one({"id": SIGNATURE_SETTING_ID}, {"_id": 0}) or {}
    if row.get("po_signature_path"):
        return row
    legacy = await server.db.settings.find_one({"id": LEGACY_LAYOUT_SETTING_ID}, {"_id": 0}) or {}
    return legacy


def _po_html(doc, company):
    rows = []
    for i, line in enumerate(doc.get("lines") or [], 1):
        factor = float(line.get("conversion_factor") or 1)
        qty = line.get("display_qty")
        if qty is None:
            qty = float(line.get("qty") or 0) / factor
        unit = line.get("display_unit") or line.get("unit") or ""
        price = line.get("display_price")
        if price is None:
            price = float(line.get("price") or 0) * factor
        total = line.get("dpp")
        if total is None:
            total = float(qty or 0) * float(price or 0) - float(line.get("discount") or 0)
        rows.append(
            "<tr>"
            f"<td>{i}</td><td>{escape(str(line.get('item_name') or line.get('item_code') or ''))}</td>"
            f"<td style='text-align:right'>{escape(str(qty))}</td><td>{escape(str(unit))}</td>"
            f"<td style='text-align:right'>Rp {_money(price)}</td><td style='text-align:right'>{_money(total)}</td>"
            "</tr>"
        )
    msg = escape(str(doc.get("document_message") or "")).replace("\n", "<br>")
    return f"""<!doctype html><html><body style='font-family:Arial,sans-serif;color:#17396f'>
    <h2>PURCHASE ORDER</h2>
    <p><b>{escape(str(company.get('name') or ''))}</b><br>{escape(str(company.get('address') or ''))}</p>
    <table style='border-collapse:collapse;width:100%;margin:14px 0'>
      <tr><td><b>PO No.</b></td><td>{escape(str(doc.get('no') or ''))}</td><td><b>PO Date</b></td><td>{escape(str(doc.get('date') or ''))}</td></tr>
      <tr><td><b>Supplier</b></td><td>{escape(str(doc.get('supplier_name') or ''))}</td><td><b>Supplier Ref</b></td><td>{escape(str(doc.get('supplier_ref') or ''))}</td></tr>
      <tr><td><b>Buyer Contact</b></td><td>{escape(str(doc.get('buyer_contact_name') or ''))}</td><td><b>Delivery Term</b></td><td>{escape(str(doc.get('delivery_term') or ''))}</td></tr>
    </table>
    <table style='border-collapse:collapse;width:100%' border='1' cellpadding='6'>
      <thead><tr><th>No</th><th>Description</th><th>Qty</th><th>Unit</th><th>Price</th><th>Amount</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p style='text-align:right;font-size:16px'><b>Grand Total: Rp {_money(doc.get('grand_total'))}</b></p>
    {f"<div style='margin-top:18px'>{msg}</div>" if msg else ''}
    </body></html>"""


def install(server):
    app = server.app

    @app.post("/api/settings/print_layouts/po/signature", tags=["settings"])
    async def upload_po_signature(file: UploadFile = File(...), user=Depends(server.current_user)):
        server.require(user, "edit")
        ctype = (file.content_type or "").lower()
        if ctype not in IMAGE_TYPES:
            raise HTTPException(400, "Tanda tangan harus PNG, JPG/JPEG, atau WEBP")
        data = await file.read()
        if not data:
            raise HTTPException(400, "File tanda tangan kosong")
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(400, "Ukuran tanda tangan maksimal 5 MB")
        ext = IMAGE_TYPES[ctype]
        path = f"settings/po-signature.{ext}"
        S.put_object(path, data, ctype)
        version = server.now_iso()
        values = {
            "po_signature_path": path,
            "po_signature_content_type": ctype,
            "po_signature_version": version,
            "updated_by": user.get("email"),
            "updated_at": version,
        }
        # Dedicated settings record keeps the signature independent from Layout Dokumen saves.
        await server.db.settings.update_one(
            {"id": SIGNATURE_SETTING_ID},
            {"$set": {"id": SIGNATURE_SETTING_ID, **values}},
            upsert=True,
        )
        # Keep legacy fields in sync for backwards compatibility with an already-running frontend.
        await server.db.settings.update_one(
            {"id": LEGACY_LAYOUT_SETTING_ID},
            {"$set": {k: values[k] for k in ("po_signature_path", "po_signature_content_type", "po_signature_version")}},
            upsert=True,
        )
        await server.audit(user, "edit", "settings", SIGNATURE_SETTING_ID, reason="Tanda tangan PO diperbarui")
        return {"ok": True, "path": path, "version": version}

    @app.get("/api/settings/print_layouts/po/signature", tags=["settings"])
    async def get_po_signature(user=Depends(server.current_user)):
        server.require(user, "view")
        row = await _signature_row(server)
        path = row.get("po_signature_path")
        if not path:
            raise HTTPException(404, "Tanda tangan PO belum diupload")
        try:
            data, ctype = S.get_object(path)
        except FileNotFoundError:
            raise HTTPException(404, "File tanda tangan PO tidak ditemukan")
        return Response(
            content=data,
            media_type=row.get("po_signature_content_type") or ctype,
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.delete("/api/settings/print_layouts/po/signature", tags=["settings"])
    async def delete_po_signature(user=Depends(server.current_user)):
        server.require(user, "edit")
        await server.db.settings.delete_one({"id": SIGNATURE_SETTING_ID})
        await server.db.settings.update_one(
            {"id": LEGACY_LAYOUT_SETTING_ID},
            {"$unset": {"po_signature_path": "", "po_signature_content_type": "", "po_signature_version": ""}},
        )
        await server.audit(user, "edit", "settings", SIGNATURE_SETTING_ID, reason="Tanda tangan PO dihapus")
        return {"ok": True}

    @app.get("/api/settings/print_layouts/po/signature-status", tags=["settings"])
    async def po_signature_status(user=Depends(server.current_user)):
        server.require(user, "view")
        row = await _signature_row(server)
        path = row.get("po_signature_path")
        available = False
        if path:
            try:
                S.get_object(path)
                available = True
            except FileNotFoundError:
                available = False
        return {
            "available": available,
            "version": row.get("po_signature_version"),
            "stored": bool(path),
        }

    @app.post("/api/po/{did}/email", tags=["po"])
    async def send_po_email(did: str, body: dict, user=Depends(server.current_user)):
        server.require(user, "print")
        doc = await server.db.po.find_one({"id": did}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "PO tidak ditemukan")
        if not _is_approved(doc):
            raise HTTPException(409, "PO belum Approved. Email hanya dapat dikirim setelah approval selesai.")

        to = str(body.get("to") or "").strip()
        if not to or "@" not in to:
            raise HTTPException(400, "Email tujuan wajib diisi")
        cc = [x.strip() for x in str(body.get("cc") or "").split(",") if x.strip()]
        subject = str(body.get("subject") or f"Purchase Order {doc.get('no') or ''}").strip()
        intro = str(body.get("message") or "Terlampir informasi Purchase Order yang telah disetujui.").strip()

        company = await server.db.settings.find_one({"id": "company"}, {"_id": 0}) or {}
        po_html = _po_html(doc, company)
        html_body = f"<p>{escape(intro).replace(chr(10), '<br>')}</p>{po_html}"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg.set_content(intro + f"\n\nPO: {doc.get('no') or ''}\nSupplier: {doc.get('supplier_name') or ''}\nGrand Total: Rp {_money(doc.get('grand_total'))}")
        msg.add_alternative(html_body, subtype="html")
        # Attach a self-contained HTML copy of the approved PO. Browser print remains the
        # canonical pixel-perfect PDF/print view, while email retains the same approved data.
        filename = f"{str(doc.get('no') or 'PO').replace('/', '-')}.html"
        msg.add_attachment(po_html.encode("utf-8"), maintype="text", subtype="html", filename=filename)

        recipients = [to] + cc
        await E.send_message(server, msg, recipients)

        await server.audit(user, "email", "po", did, doc_no=doc.get("no"), reason=f"PO dikirim ke {to}")
        await server.db.po.update_one({"id": did}, {"$set": {"last_emailed_at": server.now_iso(), "last_emailed_to": to, "last_emailed_by": user.get("email")}})
        return {"ok": True, "to": to, "cc": cc}
