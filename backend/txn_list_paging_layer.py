"""Server-side pagination, search, filter & sort untuk list transaksi.

Aktif hanya bila query `page` dikirim (tanpa `page` respons tetap array lama untuk print/export).
Dipasang paling akhir sehingga baris sudah melewati tenant -> permission -> division scope
dan enrichment existing; layer ini hanya menyaring, mengurutkan dan memotong di backend,
lalu mengirim maksimal page_size baris ke browser.
Respons: {items, total, page, page_size, facets}.
"""
import asyncio

from fastapi import Depends, Request
from fastapi.routing import APIRoute

LISTS = {"/api/mro": "mro", "/api/ro": "ro", "/api/po": "po", "/api/do": "do", "/api/mi": "mi",
         "/api/transfers": "transfer", "/api/loans": "loan", "/api/adjustments": "adjustment", "/api/opname": "opname",
         "/api/vendor-invoices": "invoice", "/api/vendor-invoices/do-billing": "do_billing"}
SIZES = (25, 50, 100)
DATE_FIELD = {"invoice": "invoice_date"}
NO_SEARCH = {"id", "tenant_id", "items", "lines", "trace_division_ids", "trace_project_ids", "lifecycle"}


def _split(v):
    if v is None:
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _get(row, key):
    cur = row
    for part in key.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _hay(r):
    vals = [str(v) for k, v in r.items() if k not in NO_SEARCH and not k.endswith("_id")
            and isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    return " ".join(vals).lower()


def _sort_key(v):
    if v is None or v == "":
        return (2, 0, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (0, float(v), "")
    return (1, 0, str(v).lower())


def _stage(t):
    req, ro, po, rec, mi = (float(t.get(k) or 0) for k in ("request", "qty_ro", "qty_po", "qty_received", "qty_mi"))
    if req > 0 and mi >= req:
        return "Completed"
    return "MI" if mi > 0 else "DO" if rec > 0 else "PO" if po > 0 else "RO" if ro > 0 else "MRO"


async def _mro_lifecycle(rows):
    """Request/RO/PO/DO/MI per MRO (rumus sama dgn /reports/mro-traceability), 5 query batch."""
    import doc_procurement as dp
    by_doc = await dp.lines_by_doc("mro_lines", "mro_id", [r["id"] for r in rows])
    lids = [l["id"] for v in by_doc.values() for l in v]
    to_ro, to_mi = await asyncio.gather(dp.allocs_from(lids, "ro"), dp.allocs_from(lids, "mi"))
    to_po = await dp.allocs_from([a["target_line_id"] for v in to_ro.values() for a in v], "po")
    to_do = await dp.allocs_from([a["target_line_id"] for v in to_po.values() for a in v], "do")
    for r in rows:
        t = {"request": 0.0, "qty_ro": 0.0, "qty_po": 0.0, "qty_received": 0.0, "qty_mi": 0.0}
        for l in by_doc.get(r["id"], []):
            t["request"] += float(l.get("qty") or 0)
            for a in to_ro.get(l["id"], []):
                t["qty_ro"] += float(a.get("qty") or 0)
                for pa in to_po.get(a["target_line_id"], []):
                    t["qty_po"] += float(pa.get("qty") or 0)
                    t["qty_received"] += sum(float(d.get("qty") or 0) for d in to_do.get(pa["target_line_id"], []))
            t["qty_mi"] += sum(float(a.get("qty") or 0) for a in to_mi.get(l["id"], []))
        t["outstanding"] = max(0.0, t["request"] - t["qty_mi"])
        r["lifecycle"] = t
        r["lifecycle_stage"] = _stage(t)


async def paginate(module, rows, qp):
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if module == "mro":
        await _mro_lifecycle(rows)
    facets = {}
    for key in _split(qp.get("facets")):
        facets[key] = sorted({x for r in rows for x in _split(_get(r, key))}, key=str.lower)
    if qp.get("counts"):
        key = qp["counts"]
        cnt = {}
        for r in rows:
            cnt[str(_get(r, key))] = cnt.get(str(_get(r, key)), 0) + 1
        facets[f"count:{key}"] = cnt
    for k, v in qp.items():
        if k.startswith("f_") and v:
            key = k[2:]
            rows = [r for r in rows if v in _split(_get(r, key)) or str(_get(r, key)) == v]
    dkey = qp.get("date_field") or DATE_FIELD.get(module, "date")
    lo, hi = qp.get("date_from"), qp.get("date_to")
    if lo or hi:
        rows = [r for r in rows if (not lo or str(r.get(dkey) or "")[:10] >= lo) and (not hi or str(r.get(dkey) or "")[:10] <= hi)]
    terms = (qp.get("q") or "").strip().lower().split()
    if terms:
        rows = [r for r in rows if all(t in _hay(r) for t in terms)]
    sort = qp.get("sort")
    if sort:
        desc = qp.get("dir") == "desc"
        filled = [r for r in rows if _get(r, sort) not in (None, "")]
        empty = [r for r in rows if _get(r, sort) in (None, "")]
        filled.sort(key=lambda r: (_sort_key(_get(r, sort)), str(r.get("no") or "")), reverse=desc)
        rows = filled + empty
    else:  # default: terbaru terlebih dahulu
        rows.sort(key=lambda r: (str(r.get("created_at") or r.get(dkey) or ""), str(r.get("no") or "")), reverse=True)
    try:
        size = int(qp.get("page_size") or 25)
    except ValueError:
        size = 25
    size = size if size in SIZES else 25
    total = len(rows)
    try:
        page = max(1, int(qp.get("page") or 1))
    except ValueError:
        page = 1
    page = min(page, max(1, -(-total // size)))
    return {"items": rows[(page - 1) * size: page * size], "total": total, "page": page, "page_size": size, "facets": facets}


def install(server):
    app = server.app
    for path, module in LISTS.items():
        route = next((r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path and "GET" in r.methods), None)
        if not route:
            continue
        orig = route.endpoint
        idx = app.router.routes.index(route)
        app.router.routes.remove(route)

        def make(orig=orig, module=module):
            async def listing(request: Request, user=Depends(server.current_user)):
                rows = await orig(user=user)
                qp = dict(request.query_params)
                if getattr(server, "REPORT_LIST_FILTER", None) and any(k.startswith("rf_") and v for k, v in qp.items()):
                    rows = await server.REPORT_LIST_FILTER(module, rows or [], qp)  # drill-down Dashboard (predikat sama)
                if "page" not in qp:
                    return rows
                return await paginate(module, rows, qp)
            listing.__name__ = f"list_{module}_paged"
            return listing
        app.add_api_route(path, make(), methods=["GET"], tags=["list-paging"])
        app.router.routes.insert(idx, app.router.routes.pop())  # pertahankan urutan (mis. /do-billing sebelum /{id})
