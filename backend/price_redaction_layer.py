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
