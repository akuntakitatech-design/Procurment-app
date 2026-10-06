"""Source picker reservation & aggregate source guard (RO<-MRO, PO<-RO, DO<-PO, MI<-MRO).

1. Pull endpoints menerima `current_doc_id` (opsional). Saat Edit, allocation milik dokumen yang
   sedang diedit tidak dihitung sebagai "sudah dipakai", sehingga picker menampilkan sisa yang
   tersedia UNTUK dokumen ini (Qty Sumber - allocation aktif dokumen LAIN). Frontend lalu
   mengurangi qty yang sedang dipakai di form aktif. `current_doc_id` divalidasi:
   tenant-scoped (proxy DB tenant), modul sesuai endpoint, dan cakupan divisi user.
2. MI dari MRO: qty diagregasi per baris MRO untuk SELURUH payload sebelum mutasi (create);
   edit memakai validasi agregat di transaction_mutation_layer._validate_sources_total.
3. DO & MI: named lock lintas proses per baris sumber (pola ro_source_lock existing) di sekitar
   validasi + mutasi. RO/PO sudah memakai lock existing (pfro:/pfpo:) dan tidak diubah.
"""
from contextvars import ContextVar
from copy import deepcopy

from fastapi import Depends, HTTPException, Query

EPS = 1e-6
_EXCLUDE: ContextVar = ContextVar("pull_exclude_current_doc", default=None)

PULLS = {  # path -> modul dokumen target (dokumen yang sedang dibuat/diedit)
    "/api/pull/mro-for-ro": "ro",
    "/api/pull/mro-for-mi": "mi",
    "/api/pull/ro-for-po": "po",
    "/api/pull/po-for-do": "do",
}
TARGET_COLL = {"ro": "ro", "po": "po", "do": "do", "mi": "mi"}
DO_LOCK, MI_LOCK = "pfdo:", "pfmi:"


def excluded_doc(target_type):
    """ID dokumen target yang allocation-nya dikecualikan pada request pull saat ini (atau None)."""
    v = _EXCLUDE.get()
    return v[1] if v and v[0] == target_type else None


async def current_do_po_ids(server):
    did = excluded_doc("do")
    if not did:
        return set()
    rows = await server.db.do_lines.find({"do_id": did}, {"_id": 0, "po_id": 1}).to_list(5000)
    return {r.get("po_id") for r in rows if r.get("po_id")}


async def current_do_pos(server, supplier_id=None):
    """PO yang dirujuk DO yang sedang diedit (boleh berstatus Fully Received karena DO ini sendiri)."""
    ids = await current_do_po_ids(server)
    if not ids:
        return []
    out = []
    for d in await server.db.po.find({"id": {"$in": list(ids)}}, {"_id": 0}).to_list(len(ids) + 5):
        st = str(d.get("status") or "").strip().lower()
        if d.get("cancelled") is True or st in ("cancelled", "canceled", "rejected", "draft", "waiting approval") \
                or str(d.get("approval_status") or "") in ("Waiting Approval", "Rejected"):
            continue
        if supplier_id and d.get("supplier_id") != supplier_id:
            continue
        out.append(d)
    return out


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def _wrap(app, path, method, factory, tag):
    route = _find_route(app, path, method)
    if not route:
        return False
    app.router.routes.remove(route)
    app.add_api_route(path, factory(route.endpoint), methods=[method], tags=[tag])
    return True


async def _resolve_current(server, target, did, user):
    if not did:
        return None
    did = str(did)
    doc = await getattr(server.db, TARGET_COLL[target]).find_one({"id": did}, {"_id": 0, "id": 1})  # tenant-scoped proxy
    if not doc:
        raise HTTPException(404, "Dokumen yang sedang diedit tidak ditemukan")
    check = getattr(server, "require_doc_access", None)
    if check:
        await check(target, did, user)  # cakupan divisi (403 bila di luar cakupan)
    return did


def _line_source_id(line, key):
    src = ((line.get("sources") or [None])[0]) or {}
    return line.get(key) or src.get("line_id") or src.get(key)


async def _lock_ids(server, body, target, key, did=None):
    ids = set()
    for l in (body or {}).get("lines") or []:
        if not isinstance(l, dict):
            continue
        sid = _line_source_id(l, key)
        if sid:
            ids.add(str(sid))
        for s in l.get("sources") or []:
            if isinstance(s, dict) and (s.get("line_id") or s.get(key)):
                ids.add(str(s.get("line_id") or s.get(key)))
    if did:
        old = await server.db.allocations.find({"target_doc_id": did, "target_type": target}, {"_id": 0, "source_line_id": 1}).to_list(5000)
        ids |= {a.get("source_line_id") for a in old if a.get("source_line_id")}
    return ids


async def validate_mi_body(server, body, user, did=None):
    """MI Dari MRO: total qty per baris MRO (seluruh payload, satuan dasar) <= sisa MRO untuk dokumen ini."""
    import uom_layer
    import transaction_mutation_layer as Mutation
    if (body or {}).get("source_type", "MRO") != "MRO":
        return
    normalized, _ = await uom_layer._normalize_body(server, deepcopy(body or {}))
    total, mlines = {}, {}
    for l in normalized.get("lines") or []:
        try:
            q = float(l.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        sl = _line_source_id(l, "mro_line_id")
        if q <= EPS or not sl:
            continue  # validasi wajib-sumber/barang tetap oleh endpoint existing
        ml = mlines.get(sl) or await server.db.mro_lines.find_one({"id": sl}, {"_id": 0})
        if not ml:
            continue
        mlines[sl] = ml
        total[sl] = total.get(sl, 0.0) + q
    if server.has_perm(user, "override_qty"):
        return  # rule existing: override_qty boleh melewati batas kebutuhan MRO
    for sl, q in total.items():
        ml = mlines[sl]
        avail = float(ml.get("qty") or 0) - float(await Mutation._allocated_elsewhere(server, sl, "mi", did) or 0)
        if q > avail + EPS:
            head = await server.db.mro.find_one({"id": ml.get("mro_id")}, {"_id": 0, "no": 1}) or {}
            raise HTTPException(400, f"Total Qty MI dari {head.get('no') or 'MRO'} ({q:g}) melebihi sisa kebutuhan MRO ({max(avail, 0.0):g}). "
                                     "Sumber yang sama tidak boleh ditarik melebihi sisanya.")


def install_guards(server):
    """Dipasang SEBELUM access_control (izin/divisi tetap dievaluasi lebih dulu)."""
    from ro_source_lock import source_line_locks
    app = server.app

    def mk_create_mi(orig):
        async def create_mi_guarded(body: dict, user=Depends(server.current_user)):
            async with source_line_locks(server, await _lock_ids(server, body, "mi", "mro_line_id"), MI_LOCK):
                await validate_mi_body(server, body, user)
                return await orig(body=body, user=user)
        return create_mi_guarded

    def mk_create_do(orig):
        async def create_do_locked(body: dict, user=Depends(server.current_user)):
            async with source_line_locks(server, await _lock_ids(server, body, "do", "po_line_id"), DO_LOCK):
                return await orig(body=body, user=user)
        return create_do_locked

    def mk_put(orig):
        async def put_transaction_locked(module: str, did: str, body: dict, user=Depends(server.current_user)):
            if module == "mi":
                async with source_line_locks(server, await _lock_ids(server, body, "mi", "mro_line_id", did), MI_LOCK):
                    return await orig(module=module, did=did, body=body, user=user)
            if module == "do":
                async with source_line_locks(server, await _lock_ids(server, body, "do", "po_line_id", did), DO_LOCK):
                    return await orig(module=module, did=did, body=body, user=user)
            return await orig(module=module, did=did, body=body, user=user)
        return put_transaction_locked

    _wrap(app, "/api/mi", "POST", mk_create_mi, "source-reservation")
    _wrap(app, "/api/do", "POST", mk_create_do, "source-reservation")
    _wrap(app, "/api/transactions/{module}/{did}", "PUT", mk_put, "source-reservation")


def install_pulls(server):
    """Dipasang SETELAH access_control: parameter current_doc_id hanya mengubah perhitungan sisa;
    filter izin & cakupan divisi baris sumber tetap dari layer existing."""
    app = server.app

    def mk_pull(orig, target, with_supplier):
        async def run(did, user, call):
            did = await _resolve_current(server, target, did, user)
            tok = _EXCLUDE.set((target, did) if did else None)
            try:
                return await call()
            finally:
                _EXCLUDE.reset(tok)
        if with_supplier:
            async def pull_with_current(supplier_id: str = Query(None), current_doc_id: str = Query(None), user=Depends(server.current_user)):
                return await run(current_doc_id, user, lambda: orig(supplier_id=supplier_id, user=user))
        else:
            async def pull_with_current(current_doc_id: str = Query(None), user=Depends(server.current_user)):
                return await run(current_doc_id, user, lambda: orig(user=user))
        return pull_with_current

    for path, target in PULLS.items():
        _wrap(app, path, "GET", lambda o, t=target, p=path: mk_pull(o, t, p.endswith("po-for-do")), "source-reservation")
