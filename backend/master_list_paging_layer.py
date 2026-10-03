"""Server-side pagination, search, filter & sort untuk 14 Master Data (pola sama dgn txn_list_paging_layer).

Dipasang paling akhir: baris sudah melewati tenant -> permission -> cakupan divisi.
- /api/master/{name}, /api/item-warehouse: aktif hanya bila query `page` dikirim; tanpa `page` = array lama.
- /api/spk, /api/vendor-contracts: sudah ber-envelope; bila `page` dikirim page_size dinormalisasi ke 25/50/100.
Label referensi (kategori/divisi/satuan) ditambahkan agar search & sort berlaku pada nama yang tampil.
Endpoint /api/lookup/* tidak disentuh.
"""
import asyncio
import inspect

from fastapi import Depends, Request
from fastapi.routing import APIRoute

from txn_list_paging_layer import SIZES, paginate

REFS = {
    "items": {"category_id": "item_categories", "division_id": "divisions", "base_uom_id": "uoms"},
    "warehouses": {"division_id": "divisions"},
    "units": {"division_id": "divisions"},
    "contacts": {"division_id": "divisions"},
    "suppliers": {"supplier_category_id": "supplier_categories"},
}


def _size(v):
    try:
        v = int(v or 25)
    except ValueError:
        return 25
    return v if v in SIZES else 25


def _swap(app, path, make):
    route = next((r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path and "GET" in r.methods), None)
    if not route:
        return
    idx = app.router.routes.index(route)
    app.router.routes.remove(route)
    app.add_api_route(path, make(route.endpoint), methods=["GET"], tags=["master-paging"])
    app.router.routes.insert(idx, app.router.routes.pop())


async def _labels(db, name, rows):
    refs = REFS.get(name, {})
    colls = sorted(set(refs.values()))
    found = await asyncio.gather(*[getattr(db, c).find({}, {"_id": 0, "id": 1, "name": 1}).to_list(None) for c in colls])
    names = {c: {d["id"]: d.get("name") for d in docs} for c, docs in zip(colls, found)}
    for r in rows:
        r["status_label"] = "Aktif" if r.get("is_active") else "Nonaktif"
        for key, coll in refs.items():
            r[f"{key[:-3]}_label"] = names[coll].get(r.get(key)) if r.get(key) else None


def install(server):
    app = server.app

    def mk_master(orig):
        async def ep(name: str, request: Request, user=Depends(server.current_user), q: str = None, active_only: bool = False):
            qp = dict(request.query_params)
            if "page" not in qp:
                return await orig(name=name, user=user, q=q, active_only=active_only)
            rows = await orig(name=name, user=user, q=None, active_only=active_only)
            await _labels(server.db, name, rows)
            return await paginate(name, rows, qp)
        return ep
    _swap(app, "/api/master/{name}", mk_master)

    def mk_iw(orig):
        async def ep(request: Request, user=Depends(server.current_user), warehouse_id: str = None, item_id: str = None):
            rows = await orig(user=user, warehouse_id=warehouse_id, item_id=item_id)
            qp = dict(request.query_params)
            if "page" not in qp:
                return rows
            rows = list(reversed(rows))  # urutan DB created_at ASC -> terbaru dahulu (sort stabil)
            return await paginate("item_warehouse", rows, qp)
        return ep
    _swap(app, "/api/item-warehouse", mk_iw)

    def mk_env(orig):
        params = set(inspect.signature(orig).parameters) - {"user"}
        async def ep(request: Request, user=Depends(server.current_user)):
            qp = dict(request.query_params)
            kw = {k: v for k, v in qp.items() if k in params and k not in ("page", "page_size")}
            if "page" in qp:
                try:
                    kw["page"] = max(1, int(qp["page"]))
                except ValueError:
                    kw["page"] = 1
                kw["page_size"] = _size(qp.get("page_size"))
            elif "page_size" in qp:
                kw["page_size"] = int(qp["page_size"])
            res = await orig(user=user, **kw)
            if isinstance(res, dict) and "page" in qp and res.get("total") is not None:
                pages = max(1, -(-res["total"] // kw["page_size"]))
                if kw["page"] > pages:  # halaman di luar jangkauan -> halaman terakhir
                    kw["page"] = pages
                    res = await orig(user=user, **kw)
            return res
        return ep
    _swap(app, "/api/spk", mk_env)
    _swap(app, "/api/vendor-contracts", mk_env)
