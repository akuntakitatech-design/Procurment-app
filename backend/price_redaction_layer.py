"""Redaksi harga server-side pada keluaran audit (Log Aktivitas & feed dashboard) untuk pengguna tanpa
izin existing `view_purchase_price`.

Audit menyimpan before/after apa adanya (jejak lengkap tetap utuh di DB). Saat DIBACA oleh pengguna tanpa
izin harga, kunci harga/nilai persediaan (mis. approved_unit_cost dari override biaya Penyesuaian Stok /
Stock Opname) dihapus dari before/after/extra sehingga harga tidak bocor lewat API. Dipasang PALING LUAR
(setelah seluruh layer scope/paging) agar berlaku atas hasil akhir route mana pun yang membungkusnya.
Tidak mengubah valuation engine, formula MWA, maupun data audit.
"""
from fastapi import Depends

PRICE_KEYS = frozenset({
    "approved_unit_cost", "unit_cost", "unit_cost_in", "avg_cost", "total_value", "value_in", "value_out",
    "unit_price", "price", "net_value", "surplus_value", "shortage_value", "posted_value", "posted_unit_cost",
    "value", "cost", "last_cost", "carrying_value", "purchase_price", "amount", "subtotal", "total", "grand_total",
})
AUDIT_PAYLOAD_KEYS = ("before", "after", "extra", "changes", "detail", "details")


def strip_prices(obj):
    if isinstance(obj, dict):
        return {k: strip_prices(v) for k, v in obj.items() if k not in PRICE_KEYS}
    if isinstance(obj, list):
        return [strip_prices(v) for v in obj]
    return obj


def redact_audit_rows(rows):
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            r = {**r, **{k: strip_prices(r[k]) for k in AUDIT_PAYLOAD_KEYS if k in r}}
        out.append(r)
    return out


def install(server):
    app = server.app

    def find(path, method):
        return next((r for r in app.router.routes if getattr(r, "path", None) == path
                     and method in (getattr(r, "methods", set()) or set())), None)

    def price_ok(user):
        return bool(server.has_perm(user, "view_purchase_price"))

    r = find("/api/audit", "GET")
    if r:
        orig_audit = r.endpoint
        app.router.routes.remove(r)

        async def audit_list(entity: str = None, entity_id: str = None, limit: int = 300, user=Depends(server.current_user)):
            rows = await orig_audit(entity=entity, entity_id=entity_id, limit=limit, user=user)
            if price_ok(user):
                return rows
            if isinstance(rows, dict) and isinstance(rows.get("items"), list):
                return {**rows, "items": redact_audit_rows(rows["items"])}
            return redact_audit_rows(rows)
        app.add_api_route("/api/audit", audit_list, methods=["GET"], tags=["price-redaction"])

    r = find("/api/dashboard-premium", "GET")
    if r:
        orig_premium = r.endpoint
        app.router.routes.remove(r)

        async def dashboard_premium(user=Depends(server.current_user)):
            data = await orig_premium(user=user)
            if price_ok(user) or not isinstance(data, dict) or not isinstance(data.get("recent"), list):
                return data
            return {**data, "recent": redact_audit_rows(data["recent"])}
        app.add_api_route("/api/dashboard-premium", dashboard_premium, methods=["GET"], tags=["price-redaction"])

    # Log Aktivitas (/api/activity-log) memakai audit_logs yang sama dengan /api/audit -> redaksi yang sama.
    wrap_get(app, find, "/api/activity-log", price_ok,
             lambda data: ({**data, "rows": redact_audit_rows(data["rows"])}
                           if isinstance(data, dict) and isinstance(data.get("rows"), list) else redact_audit_rows(data)
                           if isinstance(data, list) else data))
    # Daftar & detail PO: nilai turunan harga (gross/DPP/diskon/PPN/DP/harga tampilan) ikut disembunyikan.
    wrap_get(app, find, "/api/po", price_ok, redact_po_payload)
    wrap_get(app, find, "/api/po/{did}", price_ok, redact_po_payload)


# --- PO: kunci nilai yang diturunkan dari harga beli (header & baris) ---------------------------------------------
PO_HEADER_PRICE_KEYS = frozenset({
    "grand_total", "gross_total", "item_discount_total", "subtotal_after_item_discount", "final_discount_amount",
    "subtotal_after_discount", "tax_total", "dp_amount", "dp_remaining", "dp_paid", "dp_outstanding",
    "subtotal", "total", "dpp_total", "net_total", "price_total",
})
PO_LINE_PRICE_KEYS = frozenset({
    "price", "discount", "tax", "total", "display_price", "gross", "dpp", "discount_amount", "tax_amount",
    "contract_price_snapshot", "price_variance", "price_variance_pct", "unit_price", "net_price", "line_total",
    "subtotal", "last_price", "contract_price",
})
# Nilai yang berarti nominal uang hanya bila tipenya BUKAN persen (bila persen, tetap tampil sebagai ketentuan).
_PERCENT_TYPES = ("percent", "%", "persen", "pct", "percentage")
_NOMINAL_WHEN = (("final_discount_value", "final_discount_type"), ("dp_value", "dp_type"))


def redact_po_doc(d):
    if not isinstance(d, dict):
        return d
    out = {k: (None if k in PO_HEADER_PRICE_KEYS else v) for k, v in d.items()}
    for value_key, type_key in _NOMINAL_WHEN:
        typ = str(out.get(type_key) or "").strip().lower()
        if out.get(value_key) not in (None, "", 0) and typ not in _PERCENT_TYPES:
            out[value_key] = None
    if isinstance(out.get("lines"), list):
        out["lines"] = [_redact_po_line(ln) for ln in out["lines"]]
    return out


def _redact_po_line(ln):
    if not isinstance(ln, dict):
        return ln
    o = {k: (None if k in PO_LINE_PRICE_KEYS else v) for k, v in ln.items()}
    if o.get("discount_value") not in (None, "", 0) and str(o.get("discount_type") or "amount").strip().lower() not in _PERCENT_TYPES:
        o["discount_value"] = None  # diskon baris nominal (Rp) = turunan harga
    return o


def redact_po_payload(data):
    """Bentuk respon dipertahankan: list (legacy), {items: [...]} (paging), atau satu dokumen (detail)."""
    if isinstance(data, list):
        return [redact_po_doc(d) for d in data]
    if isinstance(data, dict) and isinstance(data.get("items"), list) and "id" not in data:
        return {**data, "items": [redact_po_doc(d) for d in data["items"]]}
    return redact_po_doc(data)


def wrap_get(app, find, path, price_ok, redact):
    """Bungkus route GET existing: signature/parameter asli dipertahankan, keluaran diredaksi untuk user tanpa izin harga."""
    import functools
    import inspect

    r = find(path, "GET")
    if not r:
        return
    orig = r.endpoint
    sig = inspect.signature(orig)
    if "user" not in sig.parameters:
        return
    app.router.routes.remove(r)

    @functools.wraps(orig)
    async def wrapped(*args, **kwargs):
        data = await orig(*args, **kwargs)
        user = kwargs.get("user")
        if user is None or price_ok(user):
            return data
        return redact(data)

    wrapped.__signature__ = sig
    app.add_api_route(path, wrapped, methods=["GET"], tags=list(getattr(r, "tags", []) or []) + ["price-redaction"],
                      response_model=getattr(r, "response_model", None), name=getattr(r, "name", None))
