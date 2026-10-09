"""Pusat Laporan: builder bersama + route JSON berpaginasi + export Excel/PDF server-side.

Alur tunggal: parse & validasi filter -> spec.builder (SELURUH baris, scope server-side) -> pencarian -> proyeksi kolom
(kolom harga dibuang tanpa view_purchase_price) -> total atas SELURUH baris -> (a) JSON: potong halaman,
(b) Excel/PDF: seluruh baris (batas tegas, tidak dipotong diam-diam). UI, Excel, dan PDF memakai hasil `run()` yang sama.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

import report_control_scope_layer as RCS
from reporting import registry as R
from reporting.exporters import to_pdf, to_xlsx

WIB = ZoneInfo("Asia/Jakarta")
EXPORT_LIMITS = {"xlsx": 100_000, "pdf": 5_000}
PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX = 50, 500
RESERVED = {"page", "page_size", "q"}


def _iso(v, label):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(400, f"{label} harus berformat YYYY-MM-DD.")


def _int(v, default, lo, hi, label):
    if v in (None, ""):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{label} harus berupa angka.")
    return max(lo, min(hi, n))


async def parse_params(server, user, spec, qp) -> dict:
    """Filter tervalidasi server-side. Tanggal = tanggal bisnis WIB (YYYY-MM-DD, inklusif)."""
    allowed = {f.key for f in spec.filters}
    p = {k: (str(v).strip() if v is not None else "") for k, v in qp.items() if k in allowed}
    if "date_from" in allowed or "date_to" in allowed:
        p["date_from"], p["date_to"] = _iso(qp.get("date_from"), "Tanggal Awal"), _iso(qp.get("date_to"), "Tanggal Akhir")
        if p["date_from"] and p["date_to"] and p["date_from"] > p["date_to"]:
            raise HTTPException(400, "Tanggal Awal tidak boleh melebihi Tanggal Akhir.")
    if p.get("division_id") and not RCS._division_allowed(server, user, p["division_id"]):
        raise HTTPException(403, "Divisi yang dipilih berada di luar cakupan Anda.")
    for f in spec.filters:
        if f.type == "select" and p.get(f.key) and p[f.key] not in {v for v, _ in f.options}:
            raise HTTPException(400, f"Nilai filter {f.label} tidak valid.")
    return p


async def _filters_applied(server, spec, p, q):
    out = []
    labels = {f.key: f for f in spec.filters}
    if p.get("date_from") or p.get("date_to"):
        out.append({"key": "period", "label": "Periode", "value": f"{p.get('date_from') or 'awal'} s/d {p.get('date_to') or 'akhir'}"})
    for k, v in p.items():
        if not v or k in ("date_from", "date_to"):
            continue
        f = labels.get(k)
        val = v
        if k == "division_id":
            d = await server.db.divisions.find_one({"id": v}, {"_id": 0, "name": 1})
            val = (d or {}).get("name") or v
        elif f and f.type == "select":
            val = dict(f.options).get(v, v)
        out.append({"key": k, "label": f.label if f else k, "value": val})
    if q:
        out.append({"key": "q", "label": "Pencarian", "value": q})
    return out


def _round(v, typ):
    return round(v, 2) if typ == "money" else round(v, 6)


async def run(server, user, key, qp) -> dict:
    spec = R.REGISTRY.get(key)
    if not spec:
        raise HTTPException(404, "Laporan tidak ditemukan.")
    server.require(user, spec.permission)
    p = await parse_params(server, user, spec, qp)
    q = (qp.get("q") or "").strip()
    price_visible = bool(server.has_perm(user, "view_purchase_price"))
    rows = await spec.builder(server, user, p)
    if q and spec.search_keys:
        terms = q.lower().split()
        rows = [r for r in rows if all(t in " ".join(str(r.get(k) or "") for k in spec.search_keys).lower() for t in terms)]
    cols = spec.visible_columns(price_visible)
    keys = [c.key for c in cols]
    out_rows = []
    for r in rows:
        o = {k: r.get(k) for k in keys}
        if spec.drill:
            o["_drill"] = spec.drill(r)
        out_rows.append(o)
    totals = {}
    for c in cols:
        if c.total:
            totals[c.key] = _round(sum(float(r.get(c.key) or 0) for r in out_rows), c.type)
    company = await server.db.settings.find_one({"id": "company"}, {"_id": 0, "name": 1}) or {}
    group_title = next((g["title"] for g in R.GROUPS if g["key"] == spec.group), spec.group)
    return {
        "meta": {"report_key": spec.key, "title": spec.title, "description": spec.description, "group": spec.group,
                 "group_title": group_title, "date_basis": spec.date_basis, "company": company.get("name") or "-",
                 "sheet": spec.title, "generated_by": user.get("name") or user.get("email") or "-",
                 "generated_at": datetime.now(WIB).strftime("%d-%m-%Y %H:%M")},
        "columns": [c.public() for c in cols],
        "filters": [f.public() for f in spec.filters],
        "filters_applied": await _filters_applied(server, spec, p, q),
        "rows": out_rows, "totals": totals, "total_rows": len(out_rows), "price_visible": price_visible,
        "export_limits": EXPORT_LIMITS,
    }


def page_of(res, qp):
    size = _int(qp.get("page_size"), PAGE_SIZE_DEFAULT, 1, PAGE_SIZE_MAX, "Ukuran halaman")
    pages = max(1, math.ceil(res["total_rows"] / size))
    page = _int(qp.get("page"), 1, 1, pages, "Halaman")
    return {**res, "rows": res["rows"][(page - 1) * size: page * size], "page": page, "page_size": size, "pages": pages}


def check_limit(res, fmt):
    lim = EXPORT_LIMITS[fmt]
    if res["total_rows"] > lim:
        other = " atau gunakan Export Excel" if fmt == "pdf" else ""
        raise HTTPException(422, f"Data {res['total_rows']:,} baris melebihi batas Export {fmt.upper() if fmt == 'pdf' else 'Excel'} "
                                 f"({lim:,} baris). Persempit filter{other}. Tidak ada data yang dipotong.".replace(",", "."))


def install(server):
    import reporting.reports_procurement  # noqa: F401  (mendaftarkan laporan ke REGISTRY)
    app = server.app

    async def catalog(user=Depends(server.current_user)):
        server.require(user, "view")
        groups = []
        for g in R.GROUPS:
            reps = [{"key": s.key, "title": s.title, "description": s.description}
                    for s in R.REGISTRY.values() if s.group == g["key"] and server.has_perm(user, s.permission)]
            groups.append({**g, "reports": reps})
        return {"groups": groups, "export_limits": EXPORT_LIMITS,
                "can_export": bool(server.has_perm(user, "export")),
                "price_visible": bool(server.has_perm(user, "view_purchase_price"))}

    async def report(key: str, request: Request, user=Depends(server.current_user)):
        qp = dict(request.query_params)
        return page_of(await run(server, user, key, qp), qp)

    async def export(key: str, fmt: str, request: Request, user=Depends(server.current_user)):
        if fmt not in EXPORT_LIMITS:
            raise HTTPException(404, "Format export tidak dikenal.")
        server.require(user, "export")
        res = await run(server, user, key, dict(request.query_params))
        check_limit(res, fmt)
        buf = to_xlsx(res) if fmt == "xlsx" else to_pdf(res)
        await server.audit(user, "export", "report", key, doc_no=f"{key}.{fmt}",
                           after={"format": fmt, "rows": res["total_rows"], "filters": res["filters_applied"],
                                  "price_visible": res["price_visible"]})
        stamp = datetime.now(WIB).strftime("%Y%m%d-%H%M")
        media = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "application/pdf")
        return StreamingResponse(buf, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="{key}_{stamp}.{fmt}"', "X-Report-Rows": str(res["total_rows"])})

    async def export_xlsx(key: str, request: Request, user=Depends(server.current_user)):
        return await export(key, "xlsx", request, user)

    async def export_pdf(key: str, request: Request, user=Depends(server.current_user)):
        return await export(key, "pdf", request, user)

    app.add_api_route("/api/report-center/catalog", catalog, methods=["GET"], tags=["report-center"])
    app.add_api_route("/api/report-center/{key}/export.xlsx", export_xlsx, methods=["GET"], tags=["report-center"])
    app.add_api_route("/api/report-center/{key}/export.pdf", export_pdf, methods=["GET"], tags=["report-center"])
    app.add_api_route("/api/report-center/{key}", report, methods=["GET"], tags=["report-center"])
