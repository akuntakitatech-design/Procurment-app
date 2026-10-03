"""Hak Akses per Modul & per Aksi + Cakupan Divisi (Tahap 2).

Extends the existing RBAC (server.has_perm / require / is_global, user.role / permissions / scope / divisions):
- granular keys `module.action` stored per tenant role in `role_permissions` (tenant-scoped by the isolation proxy);
- user overrides `permission_overrides` {key: allow|deny} and `division_override` (None = Ikuti Role);
- legacy users without explicit overrides are resolved from their legacy permission list (no access change);
- authoritative server-side check per request (route -> module/action) inside `server.current_user`;
- division scope enforced on lists, detail, create/edit/delete/bulk and source pickers.
Admin role is always full access. Business rules still run after the permission check.
"""
from __future__ import annotations

import inspect

from fastapi import Depends, HTTPException

import receipt_control_layer as RC

A_VIEW, A_CREATE, A_EDIT, A_DELETE = "view", "create", "edit", "delete"
CRUD = [A_VIEW, A_CREATE, A_EDIT, A_DELETE]
TXN_ACTIONS = CRUD + ["post", "cancel", "print"]
ACTION_LABELS = {"view": "Lihat", "create": "Tambah", "edit": "Edit", "delete": "Hapus", "post": "Posting",
                 "cancel": "Batalkan / Reversal", "print": "Cetak", "approve": "Setujui", "reject": "Tolak",
                 "send_email": "Kirim Email", "direct": "MI Langsung (Direct)", "pay": "Catat Pembayaran"}
ACTION_VERB = {"view": "melihat", "create": "menambah", "edit": "mengubah", "delete": "menghapus", "post": "memposting",
               "cancel": "membatalkan / reversal", "print": "mencetak", "approve": "menyetujui", "reject": "menolak",
               "send_email": "mengirim email", "direct": "membuat MI Langsung", "pay": "mencatat pembayaran"}

GROUPS = [
    ("transaksi", "Transaksi", [
        ("mro", "MRO", TXN_ACTIONS), ("ro", "RO", TXN_ACTIONS),
        ("po", "PO", TXN_ACTIONS + ["approve", "reject", "send_email"]), ("do", "DO", TXN_ACTIONS),
        ("mi", "MI", TXN_ACTIONS + ["direct"]), ("transfer", "Transfer Antar Gudang", TXN_ACTIONS),
        ("loan", "Pinjam Antar Gudang", TXN_ACTIONS), ("adjustment", "Penyesuaian Stok", TXN_ACTIONS),
        ("opname", "Stock Opname", TXN_ACTIONS)]),
    ("keuangan", "Keuangan", [("invoice", "Invoice Vendor", CRUD + ["pay", "print"])]),
    ("procurement", "Master Procurement", [("spk", "SPK", CRUD), ("vendor_contracts", "Kontrak Harga Vendor", CRUD)]),
    ("barang", "Master Barang & Persediaan", [("items", "Barang", CRUD), ("item_categories", "Kategori Barang", CRUD),
                                             ("uoms", "Satuan", CRUD), ("stock_minmax", "Stok Min/Max", CRUD)]),
    ("supplier", "Master Supplier & Pembelian", [("suppliers", "Supplier", CRUD), ("supplier_categories", "Kategori Supplier", CRUD),
                                                 ("taxes", "Pajak", CRUD)]),
    ("organisasi", "Master Organisasi & Operasional", [("divisions", "Divisi", CRUD), ("contacts", "Kontak Internal", CRUD),
                                                       ("warehouses", "Gudang", CRUD), ("projects", "Proyek", CRUD),
                                                       ("units", "Unit / Aset", CRUD)]),
    ("pengaturan", "Pengaturan", [("users", "Pengguna & Hak Akses", CRUD)]),
]
SPECIALS = [
    ("export", "Ekspor Data"), ("upload_attachment", "Unggah Lampiran"), ("view_purchase_price", "Lihat Harga Beli"),
    ("edit_purchase_price", "Ubah Harga Beli"), ("override_qty", "Override Qty"), ("close", "Tutup Dokumen"),
    ("view_all_warehouse", "Lihat Semua Gudang"), ("procurement_budget_policy:view", "Lihat Kebijakan Budget"),
    ("procurement_budget_policy:manage", "Kelola Kebijakan Budget"), ("spk_addendum:view", "Lihat Addendum SPK"),
    ("spk_addendum:manage", "Kelola Addendum SPK"), ("spk_addendum:finalize", "Finalisasi Addendum SPK"),
    ("spk_allocation:view", "Lihat Alokasi SPK"), ("spk_allocation:manage", "Kelola Alokasi SPK"),
    ("spk_allocation:verify", "Verifikasi Alokasi SPK"), ("vendor_contract:activate", "Aktivasi Kontrak Harga"),
    ("vendor_contract_price:manage", "Kelola Harga Kontrak"),
]
MODULES = {m: (label, acts) for _, _, mods in GROUPS for m, label, acts in mods}
ALL_KEYS = {f"{m}.{a}" for m, (_, acts) in MODULES.items() for a in acts} | {k for k, _ in SPECIALS}
MASTER_SIMPLE = ["items", "item_categories", "uoms", "stock_minmax", "suppliers", "supplier_categories", "taxes",
                 "divisions", "contacts", "warehouses", "projects", "units"]
TXN = ["mro", "ro", "po", "do", "mi", "transfer", "loan", "adjustment", "opname"]
STOCK_POSTING = {"do", "mi", "transfer", "loan", "adjustment"}  # save == posting (no draft workflow)
STOCK_REVERSAL = STOCK_POSTING | {"opname"}
WAREHOUSE_DOCS = {"transfer", "loan", "adjustment", "opname"}
BASE = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi", "transfers": "transfer", "loans": "loan",
        "adjustments": "adjustment", "opname": "opname"}
COLL = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi", "transfer": "transfers", "loan": "loans",
        "adjustment": "adjustments", "opname": "opname"}
TXN_ALIAS = {"transfers": "transfer", "loans": "loan", "adjustments": "adjustment"}
MASTER_NAME = {"item_warehouse": "stock_minmax"}
DIV_MASTERS = {"items", "warehouses", "units", "contacts", "projects"}
LEGACY_ACTION = {"view": "view", "create": "create", "edit": "edit", "delete": "delete", "submit": "post",
                 "cancel": "cancel", "approve": "approve", "reject": "reject", "print": "print"}
TRANSLATE = {"direct_mi": ["mi.direct"], "post_stock_opname": ["opname.post"], "stock_adjustment": ["adjustment.create"],
             "spk:view": ["spk.view"], "spk:manage": ["spk.create", "spk.edit"],
             "vendor_contract:view": ["vendor_contracts.view"], "vendor_contract:manage": ["vendor_contracts.create", "vendor_contracts.edit"]}
ROLE_LABELS = {"admin": "Admin", "director": "Direktur", "manager": "Manajer", "purchasing": "Purchasing", "warehouse": "Gudang"}
_CFG_CACHE: dict = {}


def legacy_to_granular(perms, role=None) -> set:
    p, out = set(perms or []), set()
    for m in MASTER_SIMPLE:
        out |= {f"{m}.{a}" for a in CRUD if a in p}
    for m, v, mg in (("spk", "spk:view", "spk:manage"), ("vendor_contracts", "vendor_contract:view", "vendor_contract:manage")):
        if v in p or mg in p:
            out.add(f"{m}.view")
        if mg in p:
            out |= {f"{m}.create", f"{m}.edit"}
        if "delete" in p and (v in p or mg in p):
            out.add(f"{m}.delete")
    for m in TXN:
        out |= {f"{m}.{a}" for a in ("view", "create", "edit", "delete", "print") if a in p}
        if m in ("mro", "ro", "po"):
            out |= {f"{m}.post" for _ in [0] if "submit" in p} | {f"{m}.cancel" for _ in [0] if "cancel" in p}
        if m in STOCK_POSTING and "create" in p:
            out.add(f"{m}.post")
        if m in STOCK_REVERSAL and "delete" in p:
            out.add(f"{m}.cancel")
    out.discard("adjustment.create"); out.discard("adjustment.post")
    if "stock_adjustment" in p:
        out |= {"adjustment.create", "adjustment.post"}
    out.discard("opname.post")
    if "post_stock_opname" in p:
        out.add("opname.post")
    out |= {k for k, a in (("po.approve", "approve"), ("po.reject", "reject"), ("po.send_email", "print"), ("mi.direct", "direct_mi")) if a in p}
    if "view" in p:
        out.add("users.view")
    if role == "director":
        out |= {f"users.{a}" for a in ("create", "edit", "delete") if a in p}
    out |= {k for k, _ in SPECIALS if k in p}
    if role in ("director", "purchasing"):
        out |= {f"invoice.{a}" for a in ("view", "create", "edit", "pay", "print")} | ({"invoice.delete"} if "delete" in p else set())
    elif role == "manager":
        out |= {"invoice.view", "invoice.print"}
    return out & ALL_KEYS


def install(server):
    app, db = server.app, lambda: server.db

    def role_default(role):
        return legacy_to_granular(server.ROLE_DEFAULTS.get(role, []), role)

    async def role_cfg(role):
        import tenant_isolation_layer as TI
        key = (TI.current_tenant_id(), role)
        if key not in _CFG_CACHE:
            _CFG_CACHE[key] = await db().role_permissions.find_one({"role": role}, {"_id": 0})
        return _CFG_CACHE[key]

    def role_div_default(role):
        return {"mode": "all", "divisions": []} if role in ("admin", "director", "purchasing") else {"mode": "selected", "divisions": []}

    def derived_overrides(user):
        leg, d = legacy_to_granular(user.get("permissions") or [], user.get("role")), role_default(user.get("role"))
        return {**{k: "allow" for k in leg - d}, **{k: "deny" for k in d - leg}}

    def derived_div_override(user):
        perms = user.get("permissions") or []
        if user.get("scope") == "global" or "view_all_division" in perms:
            return {"mode": "all", "divisions": []}
        if user.get("role") in ("admin", "director", "purchasing"):
            return None
        return {"mode": "selected", "divisions": list(user.get("divisions") or [])}

    async def resolve(user):
        role = user.get("role")
        cfg = await role_cfg(role) if role != "admin" else None
        base = set(cfg["permissions"]) if cfg and cfg.get("permissions") is not None else role_default(role)
        ov = user["permission_overrides"] if isinstance(user.get("permission_overrides"), dict) else derived_overrides(user)
        eff = ALL_KEYS if role == "admin" else (base | {k for k, v in ov.items() if v == "allow"}) - {k for k, v in ov.items() if v == "deny"}
        rdiv = (cfg or {}).get("division_scope") or role_div_default(role)
        dov = user.get("division_override") if "division_override" in user else derived_div_override(user)
        ediv = {"mode": "all", "divisions": []} if role == "admin" else (dov or rdiv)
        return {"role_permissions": sorted(base & ALL_KEYS), "overrides": ov, "effective": sorted(eff & ALL_KEYS),
                "role_division_scope": rdiv, "division_override": dov, "division_scope": ediv}

    def check(user, perm):
        eff = set(user.get("effective_permissions") or [])
        if perm in eff or perm in (user.get("_implied") or []):
            return True
        if perm == "view_all_division":
            return bool(user.get("_div_all"))
        if perm in TRANSLATE:
            return any(k in eff for k in TRANSLATE[perm])
        act = LEGACY_ACTION.get(perm)
        if act:
            mod = user.get("_mod")
            return f"{mod}.{act}" in eff if mod else any(k.endswith("." + act) for k in eff)
        return False

    def classify(method, tmpl, params, body):
        """Return (module, [required actions], implied legacy perms) for a route, or (None, [], [])."""
        seg = tmpl.split("/")[2:] if tmpl.startswith("/api/") else []
        if not seg:
            return None, [], []
        head = seg[0]
        if head in ("master", "master-delete-check", "master-bulk-delete", "master-code"):
            name = params.get("name")
            mod = MASTER_NAME.get(name, name)
            if mod not in MODULES:
                return None, [], []
            if head == "master-code":
                return mod, ["create"], []
            if head != "master":
                return mod, ["delete"], []
            return mod, [{"GET": "view", "POST": "create", "PUT": "edit", "DELETE": "delete"}.get(method, "view")], []
        if head == "item-warehouse":
            if len(seg) > 1:
                return "stock_minmax", ["delete"], []
            return ("stock_minmax", ["edit"], []) if method == "POST" else (None, [], [])
        if head in ("spk", "vendor-contracts"):
            mod = "spk" if head == "spk" else "vendor_contracts"
            if len(seg) > 1 and seg[1] in ("resolve-price",):
                return None, [], []
            if len(seg) <= 2:
                act = {"GET": "view", "POST": "create", "PUT": "edit", "DELETE": "delete", "PATCH": "edit"}[method]
                return mod, [act if (len(seg) == 2 or method in ("GET", "POST")) else "view"], []
            return mod, ["view"], []
        if head == "transactions" and len(seg) >= 3:
            mod = TXN_ALIAS.get(params.get("module"), params.get("module"))
            if mod not in TXN:
                return None, [], []
            if len(seg) == 4:
                return mod, ["view"], []
            if method == "DELETE":
                return mod, ["delete"] + (["cancel"] if mod in STOCK_POSTING else []), []
            return mod, ["edit"], []
        if head == "pull" and len(seg) > 1:
            tgt = {"mro-for-ro": "ro", "mro-for-mi": "mi", "ro-for-po": "po", "po-for-do": "do"}.get(seg[1])
            return (tgt, ["create"], []) if tgt else (None, [], [])
        if head == "users":
            return "users", [{"GET": "view", "POST": "create", "PUT": "edit", "DELETE": "delete"}[method]], []
        if head == "permissions" or head == "access":
            if len(seg) > 1 and seg[1] == "me":
                return None, [], []
            return "users", ["view" if method == "GET" else "edit"], []
        if head == "lookup":
            return None, [], []  # authorised inside the lookup endpoint (functional reason)
        if head == "vendor-invoices":
            sub = seg[1] if len(seg) > 1 else None
            if sub == "eligible-dos":
                return None, [], []  # create OR edit, checked inside the endpoint
            if len(seg) == 1:
                return "invoice", ["view" if method == "GET" else "create"], []
            if len(seg) == 2 or sub == "do":
                return "invoice", [{"PUT": "edit", "DELETE": "delete"}.get(method, "view")], []
            act = {"payments": "pay", "print": "print"}.get(seg[2], "view")
            return "invoice", [act], []
        if head == "verify" and method == "POST":
            mod = str((body or {}).get("doc_type") or "").lower()
            mod = TXN_ALIAS.get(mod, mod)
            return (mod, ["print"], []) if mod in TXN else (None, [], [])
        mod = BASE.get(head)
        if not mod:
            return None, [], []
        if len(seg) == 1:
            if method == "GET":
                return mod, ["view"], []
            acts = ["create"] + (["post"] if mod in STOCK_POSTING or (mod in ("mro", "ro", "po") and (body or {}).get("submitted")) else [])
            return mod, acts, []
        if len(seg) == 2:
            return mod, ["view"], []
        sub = seg[2]
        if mod == "po" and sub in ("email", "email-context"):
            return mod, ["send_email"], ["edit", "view", "print"]
        if mod == "loan" and sub == "return":
            return mod, ["post"], ["create", "edit"]
        if mod == "opname" and sub == "count":
            return mod, ["edit"], []
        if mod == "opname" and sub == "submit":
            return mod, ["edit"], ["submit"]
        act = {"submit": "post", "post": "post", "cancel": "cancel", "approve": "approve", "reject": "reject"}.get(sub)
        return mod, [act or "view"], []

    async def hook(request, user):
        # Tenant first (session), then module/action permission. Division scope + business rules run later.
        res = await resolve(user)
        user["effective_permissions"], user["division_scope"] = res["effective"], res["division_scope"]
        user["_div_all"] = res["division_scope"]["mode"] == "all"
        if not user["_div_all"]:
            user["divisions"], user["scope"] = list(res["division_scope"].get("divisions") or []), "limited"
        route = request.scope.get("route")
        if not route or user.get("role") == "admin":
            return
        body = None
        if request.method in ("POST", "PUT") and route.path in ("/api/verify/generate", "/api/mro", "/api/ro", "/api/po"):
            try:
                body = await request.json()
            except Exception:
                body = None
        mod, acts, implied = classify(request.method, route.path, request.path_params, body)
        if mod == "opname" and request.method == "DELETE":
            doc = await db().opname.find_one({"id": request.path_params.get("did")}, {"_id": 0, "status": 1}) or {}
            if str(doc.get("status") or "").lower() == "posted":
                acts = acts + ["cancel"]
        user["_mod"], user["_implied"] = mod, implied
        for a in acts:
            if f"{mod}.{a}" not in user["effective_permissions"]:
                raise HTTPException(403, f"Anda tidak memiliki izin untuk {ACTION_VERB.get(a, a)} data {MODULES[mod][0]}.")

    server.ACCESS_HOOK = hook
    server.PERM_CHECK = check

    # ----------------------------------------------------------- division scope helpers
    def allowed(user):
        return None if server.is_global(user) else {str(x) for x in (user.get("divisions") or []) if x}

    async def wh_divs(ids):
        ids = [i for i in ids if i]
        if not ids:
            return set()
        rows = await db().warehouses.find({"id": {"$in": ids}}, {"_id": 0, "division_id": 1}).to_list(len(ids) + 5)
        return {r["division_id"] for r in rows if r.get("division_id")}

    async def doc_divisions(mod, doc):
        rows = await RC.enrich_list(server, mod, [dict(doc)])
        divs = set((rows[0] if rows else {}).get("trace_division_ids") or [])
        if doc.get("division_id"):
            divs.add(doc["division_id"])
        if mod in WAREHOUSE_DOCS:
            divs |= await wh_divs([doc.get(k) for k in ("warehouse_id", "from_warehouse_id", "to_warehouse_id")])
        return divs

    def visible(mod, divs, alw):
        if alw is None:
            return True
        if not divs:
            return mod in WAREHOUSE_DOCS
        return set(divs) <= alw

    async def assigned(mod, user):
        if mod not in ("mro", "ro", "po"):
            return set()
        rows = await db().approval_tasks.find({"module": mod, "approver_email": str(user.get("email") or "").lower()},
                                              {"_id": 0, "document_id": 1}).to_list(5000)
        return {r.get("document_id") for r in rows}

    async def require_doc(mod, did, user):
        alw = allowed(user)
        if alw is None:
            return
        doc = await getattr(db(), COLL[mod]).find_one({"id": did}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Dokumen tidak ditemukan")
        if not visible(mod, await doc_divisions(mod, doc), alw) and did not in await assigned(mod, user):
            raise HTTPException(403, "Dokumen ini berada di luar cakupan divisi Anda.")

    async def require_body(mod, body, user):
        alw = allowed(user)
        if alw is None or not isinstance(body, dict):
            return
        divs = {body["division_id"]} if body.get("division_id") else set()
        lines = body.get("lines") or []
        if mod in WAREHOUSE_DOCS:
            divs |= await wh_divs([body.get(k) for k in ("warehouse_id", "from_warehouse_id", "to_warehouse_id")]
                                  + [ln.get("warehouse_id") for ln in lines if isinstance(ln, dict)])
        if not divs <= alw:
            raise HTTPException(403, "Tidak dapat menggunakan divisi di luar cakupan divisi Anda.")
        for ln in lines:
            for src in [ln] + list((ln or {}).get("sources") or []):
                for key, smod in (("mro_id", "mro"), ("ro_id", "ro"), ("po_id", "po")):
                    if isinstance(src, dict) and src.get(key):
                        await require_doc(smod, src[key], user)

    async def require_master(name, rid, user, body=None):
        alw = allowed(user)
        if alw is None or name not in DIV_MASTERS | {"spk"}:
            return
        if rid:
            coll = db().spk if name == "spk" else server._mc(name)
            rec = await coll.find_one({"id": rid}, {"_id": 0, "division_id": 1})
            if rec and rec.get("division_id") and rec["division_id"] not in alw:
                raise HTTPException(403, "Data ini berada di luar cakupan divisi Anda.")
        if isinstance(body, dict) and body.get("division_id") and body["division_id"] not in alw:
            raise HTTPException(403, "Tidak dapat menggunakan divisi di luar cakupan divisi Anda.")

    def coerce(orig, body):
        ann = inspect.signature(orig, eval_str=True).parameters["body"].annotation
        return ann(**body) if isinstance(body, dict) and hasattr(ann, "model_validate") else body

    def in_scope(rec, alw):
        return alw is None or not rec.get("division_id") or rec["division_id"] in alw

    # ----------------------------------------------------------- route wrappers
    def wrap(path, method, make):
        r = next((x for x in app.router.routes if getattr(x, "path", None) == path
                  and method in (getattr(x, "methods", set()) or set())), None)
        if r is None:
            return
        app.router.routes.remove(r)
        app.add_api_route(path, make(r.endpoint), methods=[method], tags=["access-control"])

    for base, mod in BASE.items():
        def mk_list(orig, mod=mod):
            async def ep(user=Depends(server.current_user)):
                rows = await orig(user=user)
                alw = allowed(user)
                if alw is None:
                    return rows
                ok_ids = await assigned(mod, user)
                whd = {w["id"]: w.get("division_id") for w in await db().warehouses.find({}, {"_id": 0, "id": 1, "division_id": 1}).to_list(5000)} \
                    if mod in WAREHOUSE_DOCS else {}
                out = []
                for r in rows or []:
                    divs = set(r.get("trace_division_ids") or [])
                    if r.get("division_id"):
                        divs.add(r["division_id"])
                    divs |= {whd.get(r.get(k)) for k in ("warehouse_id", "from_warehouse_id", "to_warehouse_id") if whd.get(r.get(k))}
                    if visible(mod, divs, alw) or r.get("id") in ok_ids:
                        out.append(r)
                return out
            return ep
        wrap(f"/api/{base}", "GET", mk_list)

        def mk_detail(orig, mod=mod):
            async def ep(did: str, user=Depends(server.current_user)):
                await require_doc(mod, did, user)
                return await orig(did=did, user=user)
            return ep
        wrap(f"/api/{base}/{{did}}", "GET", mk_detail)

        def mk_create(orig, mod=mod):
            async def ep(body: dict, user=Depends(server.current_user)):
                await require_body(mod, body, user)
                return await orig(body=body, user=user)
            return ep
        wrap(f"/api/{base}", "POST", mk_create)

        for sub in ("submit", "cancel", "approve", "reject", "post", "email", "return"):
            def mk_action(orig, mod=mod):
                if "body" in inspect.signature(orig).parameters:
                    async def ep(did: str, body: dict = None, user=Depends(server.current_user)):
                        await require_doc(mod, did, user)
                        return await orig(did=did, body=body or {}, user=user)
                else:
                    async def ep(did: str, user=Depends(server.current_user)):
                        await require_doc(mod, did, user)
                        return await orig(did=did, user=user)
                return ep
            wrap(f"/api/{base}/{{did}}/{sub}", "POST", mk_action)
        for sub, meth in (("email-context", "GET"), ("returnable", "GET"), ("count", "PUT")):
            def mk_sub(orig, mod=mod, meth=meth):
                if meth == "PUT":
                    async def ep(did: str, body: dict, user=Depends(server.current_user)):
                        await require_doc(mod, did, user)
                        return await orig(did=did, body=body, user=user)
                else:
                    async def ep(did: str, user=Depends(server.current_user)):
                        await require_doc(mod, did, user)
                        return await orig(did=did, user=user)
                return ep
            wrap(f"/api/{base}/{{did}}/{sub}", meth, mk_sub)

    def mk_txn(orig, meth):
        if meth == "PUT":
            async def ep(module: str, did: str, body: dict, user=Depends(server.current_user)):
                mod = TXN_ALIAS.get(module, module)
                if mod in COLL:
                    await require_doc(mod, did, user)
                    await require_body(mod, body, user)
                return await orig(module=module, did=did, body=body, user=user)
        else:
            async def ep(module: str, did: str, user=Depends(server.current_user)):
                mod = TXN_ALIAS.get(module, module)
                if mod in COLL:
                    await require_doc(mod, did, user)
                return await orig(module=module, did=did, user=user)
        return ep
    wrap("/api/transactions/{module}/{did}", "PUT", lambda o: mk_txn(o, "PUT"))
    wrap("/api/transactions/{module}/{did}", "DELETE", lambda o: mk_txn(o, "DELETE"))
    wrap("/api/transactions/{module}/{did}/capability", "GET", lambda o: mk_txn(o, "GET"))

    def mk_pull(orig, mod, key):
        async def ep(request_supplier_id: str = None, user=Depends(server.current_user)):
            rows = await (orig(supplier_id=request_supplier_id, user=user) if mod == "po" else orig(user=user))
            alw = allowed(user)
            if alw is None:
                return rows
            out, seen = [], {}
            for r in rows or []:
                did = r.get(key)
                if did not in seen:
                    try:
                        await require_doc(mod, did, user)
                        seen[did] = True
                    except HTTPException:
                        seen[did] = False
                if seen[did]:
                    out.append(r)
            return out
        if mod == "po":
            async def ep_po(supplier_id: str = None, user=Depends(server.current_user)):
                return await ep(request_supplier_id=supplier_id, user=user)
            return ep_po
        return ep
    for path, mod, key in (("/api/pull/mro-for-ro", "mro", "mro_id"), ("/api/pull/mro-for-mi", "mro", "mro_id"),
                           ("/api/pull/ro-for-po", "ro", "ro_id"), ("/api/pull/po-for-do", "po", "po_id")):
        wrap(path, "GET", lambda o, mod=mod, key=key: mk_pull(o, mod, key))

    # Masters
    def mk_mlist(orig):
        async def ep(name: str, user=Depends(server.current_user), q: str = None, active_only: bool = False):
            rows = await orig(name=name, user=user, q=q, active_only=active_only)
            alw = allowed(user)
            return rows if alw is None or name not in DIV_MASTERS else [r for r in rows if in_scope(r, alw)]
        return ep
    wrap("/api/master/{name}", "GET", mk_mlist)

    def mk_mcreate(orig):
        async def ep(name: str, body: dict, user=Depends(server.current_user)):
            await require_master(name, None, user, body)
            return await orig(name=name, body=body, user=user)
        return ep
    wrap("/api/master/{name}", "POST", mk_mcreate)

    def mk_mrid(orig, meth):
        if meth == "PUT":
            async def ep(name: str, rid: str, body: dict, user=Depends(server.current_user)):
                await require_master(name, rid, user, body)
                return await orig(name=name, rid=rid, body=body, user=user)
        else:
            async def ep(name: str, rid: str, user=Depends(server.current_user)):
                await require_master(name, rid, user)
                return await orig(name=name, rid=rid, user=user)
        return ep
    wrap("/api/master/{name}/{rid}", "PUT", lambda o: mk_mrid(o, "PUT"))
    wrap("/api/master/{name}/{rid}", "DELETE", lambda o: mk_mrid(o, "DELETE"))

    async def check_ids(name, ids, user):
        for rid in ids or []:
            if name == "item_warehouse":
                alw = allowed(user)
                if alw is not None and (await wh_divs([str(rid).partition("|")[2]]) - alw):
                    raise HTTPException(403, "Data ini berada di luar cakupan divisi Anda.")
            else:
                await require_master(name, rid, user)

    for p in ("/api/master-delete-check/{name}", "/api/master-bulk-delete/{name}"):
        def mk_bulk(orig):
            async def ep(name: str, body: dict, user=Depends(server.current_user)):
                await check_ids(name, (body or {}).get("ids"), user)
                return await orig(name=name, body=body, user=user)
            return ep
        wrap(p, "POST", mk_bulk)

    def mk_iw(orig):
        async def ep(user=Depends(server.current_user), warehouse_id: str = None, item_id: str = None):
            rows = await orig(user=user, warehouse_id=warehouse_id, item_id=item_id)
            alw = allowed(user)
            if alw is None:
                return rows
            whs = {w["id"]: w for w in await db().warehouses.find({}, {"_id": 0, "id": 1, "division_id": 1}).to_list(5000)}
            return [r for r in rows if in_scope(whs.get(r.get("warehouse_id"), {}), alw) and in_scope(r, alw)]
        return ep
    wrap("/api/item-warehouse", "GET", mk_iw)

    def mk_iwset(orig):
        async def ep(body: dict, user=Depends(server.current_user)):
            await check_ids("item_warehouse", [f"{(body or {}).get('item_id')}|{(body or {}).get('warehouse_id')}"], user)
            return await orig(body=body, user=user)
        return ep
    wrap("/api/item-warehouse", "POST", mk_iwset)

    # Info stok per gudang (read-only, tanpa nilai): Tenant -> Permission -> Divisi barang -> Gudang (divisi gudang)
    def mk_stock(orig):
        async def ep(item_id: str, user=Depends(server.current_user)):
            res = await orig(item_id=item_id, user=user)
            item = await db().items.find_one({"id": item_id}, {"_id": 0, "id": 1, "division_id": 1, "base_uom_id": 1, "unit": 1})
            if not item:
                raise HTTPException(404, "Barang tidak ditemukan")
            alw = allowed(user)
            if not in_scope(item, alw):
                raise HTTPException(403, "Barang ini berada di luar cakupan divisi Anda.")
            uom = await db().uoms.find_one({"id": item.get("base_uom_id")}, {"_id": 0, "symbol": 1, "code": 1, "name": 1}) if item.get("base_uom_id") else None
            whs = {w["id"]: w for w in await db().warehouses.find({}, {"_id": 0, "id": 1, "division_id": 1}).to_list(5000)}
            rows = [r for r in res.get("warehouses") or [] if r.get("warehouse_id") in whs and in_scope(whs[r["warehouse_id"]], alw)]
            unit = (uom or {}).get("symbol") or (uom or {}).get("code") or (uom or {}).get("name") or item.get("unit") or ""
            return {"item_id": item_id, "unit": unit, "warehouses": [{**r, "unit": unit} for r in rows]}
        return ep
    wrap("/api/stock/by-warehouse/{item_id}", "GET", mk_stock)

    @app.get("/api/stock/warehouse/{warehouse_id}", tags=["access-control"])
    async def stock_of_warehouse(warehouse_id: str, user=Depends(server.current_user)):
        """Saldo semua barang di satu gudang (1 query, untuk kolom Stok Tersedia di pemilih Barang)."""
        server.require(user, "view")
        wh = await db().warehouses.find_one({"id": warehouse_id}, {"_id": 0, "id": 1, "division_id": 1})
        if not wh:
            raise HTTPException(404, "Gudang tidak ditemukan")
        alw = allowed(user)
        if not in_scope(wh, alw):
            raise HTTPException(403, "Gudang ini berada di luar cakupan divisi Anda.")
        rows = await db().item_warehouse.find({"warehouse_id": warehouse_id}, {"_id": 0, "item_id": 1, "current_stock": 1}).to_list(100000)
        if alw is not None:
            items = {i["id"]: i for i in await db().items.find({}, {"_id": 0, "id": 1, "division_id": 1}).to_list(100000)}
            rows = [r for r in rows if in_scope(items.get(r["item_id"], {}), alw)]
        return {r["item_id"]: float(r.get("current_stock") or 0) for r in rows}

    # SPK (division-scoped master)
    spk_list = next((r for r in app.router.routes if getattr(r, "path", "") == "/api/spk" and "GET" in r.methods), None)
    if spk_list:
        orig_spk_list = spk_list.endpoint
        app.router.routes.remove(spk_list)

        async def list_spk(q: str = "", status: str = "", division_id: str = "", period_start: str = "",
                           period_end: str = "", sort: str = "-created_at", page: int = 1, page_size: int = 20,
                           user=Depends(server.current_user)):
            kw = dict(q=q, status=status, division_id=division_id, period_start=period_start, period_end=period_end, sort=sort)
            alw = allowed(user)
            if alw is None:
                return await orig_spk_list(**kw, page=page, page_size=page_size, user=user)
            items, pg = [], 1
            while True:
                res = await orig_spk_list(**kw, page=pg, page_size=200, user=user)
                batch = (res or {}).get("items") or []
                items += [x for x in batch if in_scope(x, alw)]
                if len(batch) < 200:
                    break
                pg += 1
            size = max(1, int(page_size))
            return {**res, "items": items[(page - 1) * size: page * size], "total": len(items), "page": page, "page_size": size}
        app.add_api_route("/api/spk", list_spk, methods=["GET"], tags=["access-control"])

    for meth in ("GET", "PUT", "DELETE"):
        def mk_spk(orig, meth=meth):
            if meth == "PUT":
                async def ep(spk_id: str, body: dict, user=Depends(server.current_user)):
                    await require_master("spk", spk_id, user, body)
                    return await orig(spk_id=spk_id, body=coerce(orig, body), user=user)
            else:
                async def ep(spk_id: str, user=Depends(server.current_user)):
                    await require_master("spk", spk_id, user)
                    return await orig(spk_id=spk_id, user=user)
            return ep
        wrap("/api/spk/{spk_id}", meth, mk_spk)

    def mk_spk_create(orig):
        async def ep(body: dict, user=Depends(server.current_user)):
            await require_master("spk", None, user, body)
            return await orig(body=coerce(orig, body), user=user)
        return ep
    wrap("/api/spk", "POST", mk_spk_create)

    def mk_search(orig):
        async def ep(q: str, user=Depends(server.current_user)):
            rows = await orig(q=q, user=user)
            eff = set(user.get("effective_permissions") or [])
            if user.get("role") == "admin":
                return rows
            return [r for r in rows or [] if r.get("type") not in COLL or f"{r['type']}.view" in eff]
        return ep
    wrap("/api/search", "GET", mk_search)

    async def doc_visible(mod, did, user):
        try:
            await require_doc(mod, did, user)
            return True
        except HTTPException:
            return False

    async def visible_ids(mod, user):
        """Ids of documents the user may see (None = all). Multi-division docs need every division in scope."""
        alw = allowed(user)
        if alw is None:
            return None
        docs = await getattr(db(), COLL[mod]).find({}, {"_id": 0}).to_list(100000)
        rows = await RC.enrich_list(server, mod, docs) if docs else []
        whd = {w["id"]: w.get("division_id") for w in await db().warehouses.find({}, {"_id": 0, "id": 1, "division_id": 1}).to_list(5000)} \
            if mod in WAREHOUSE_DOCS else {}
        ok_ids, out = await assigned(mod, user), set()
        for r in rows:
            divs = set(r.get("trace_division_ids") or []) | ({r["division_id"]} if r.get("division_id") else set())
            divs |= {whd.get(r.get(k)) for k in ("warehouse_id", "from_warehouse_id", "to_warehouse_id") if whd.get(r.get(k))}
            if visible(mod, divs, alw) or r.get("id") in ok_ids:
                out.add(r.get("id"))
        return out

    AUDIT_MOD = {"mro": "mro", "ro": "ro", "po": "po", "do": "do", "mi": "mi", "transfer": "transfer", "transfers": "transfer",
                 "loan": "loan", "loans": "loan", "adjustment": "adjustment", "adjustments": "adjustment", "opname": "opname"}

    async def audit_filter(rows, user, limit):
        """Audit rows visible in the user's division scope (own actions, visible docs, in-scope masters)."""
        alw = allowed(user)
        if alw is None:
            return rows[:limit]
        cache, out, me = {}, [], str(user.get("email") or "").lower()
        for row in rows:
            ent, eid = str(row.get("entity") or "").lower(), row.get("entity_id")
            ok = str(row.get("user") or "").lower() == me
            if not ok and ent in AUDIT_MOD and eid:
                m = AUDIT_MOD[ent]
                if m not in cache:
                    cache[m] = await visible_ids(m, user)
                ok = eid in cache[m]
            elif not ok and (ent in DIV_MASTERS or ent == "spk") and eid:
                coll = db().spk if ent == "spk" else server._mc(ent)
                rec = await coll.find_one({"id": eid}, {"_id": 0, "division_id": 1})
                ok = bool(rec) and in_scope(rec, alw)
            if ok:
                out.append(row)
            if len(out) >= limit:
                break
        return out

    server.ACCESS_DOC_VISIBLE, server.ACCESS_VISIBLE_IDS, server.ACCESS_AUDIT_FILTER = doc_visible, visible_ids, audit_filter

    def mk_verify(orig):
        async def ep(body: dict, user=Depends(server.current_user)):
            mod = TXN_ALIAS.get(str((body or {}).get("doc_type") or "").lower(), str((body or {}).get("doc_type") or "").lower())
            if mod in COLL and (body or {}).get("doc_id"):
                await require_doc(mod, body["doc_id"], user)
            elif mod == "spk" and (body or {}).get("doc_id"):
                await require_master("spk", body["doc_id"], user)
            return await orig(body=body, user=user)
        return ep
    wrap("/api/verify/generate", "POST", mk_verify)

    _install_lookup(server, allowed, in_scope)
    _install_admin_api(server, resolve, role_default, role_div_default)


OV_LABEL = {None: "Ikuti Role", "allow": "Izinkan", "deny": "Tolak"}


def _scope_label(sc):
    if sc is None:
        return "Ikuti Role"
    return "Semua Divisi" if sc.get("mode") == "all" else f"Divisi Tertentu ({len(sc.get('divisions') or [])})"


def _install_admin_api(server, resolve, role_default, role_div_default):
    app = server.app
    db = lambda: server.db  # noqa: E731

    async def clean_scope(sc):
        if sc is None:
            return None
        if not isinstance(sc, dict) or sc.get("mode") not in ("all", "selected"):
            raise HTTPException(400, "Cakupan divisi tidak valid")
        divs = list(dict.fromkeys(sc.get("divisions") or [])) if sc["mode"] == "selected" else []
        if divs:
            found = await db().divisions.find({"id": {"$in": divs}}, {"_id": 0, "id": 1}).to_list(len(divs) + 5)
            if len(found) != len(divs):
                raise HTTPException(400, "Divisi yang dipilih tidak ditemukan")
        return {"mode": sc["mode"], "divisions": divs}

    @app.get("/api/access/me", tags=["access-control"])
    async def access_me(user=Depends(server.current_user)):
        return {"role": user.get("role"), "effective": user.get("effective_permissions"), "division_scope": user.get("division_scope")}

    @app.get("/api/access/catalog", tags=["access-control"])
    async def access_catalog(user=Depends(server.current_user)):
        return {"groups": [{"key": g, "label": gl, "modules": [{"key": m, "label": ml, "actions": acts} for m, ml, acts in mods]}
                           for g, gl, mods in GROUPS],
                "specials": [{"key": k, "label": lbl} for k, lbl in SPECIALS], "actions": ACTION_LABELS,
                "roles": [{"key": r, "label": ROLE_LABELS.get(r, r)} for r in server.ROLE_DEFAULTS]}

    @app.get("/api/access/roles", tags=["access-control"])
    async def access_roles(user=Depends(server.current_user)):
        out = []
        for role in server.ROLE_DEFAULTS:
            cfg = await db().role_permissions.find_one({"role": role}, {"_id": 0}) if role != "admin" else None
            perms = sorted(ALL_KEYS) if role == "admin" else sorted(set(cfg["permissions"]) if cfg else role_default(role))
            out.append({"role": role, "label": ROLE_LABELS.get(role, role), "locked": role == "admin", "configured": bool(cfg),
                        "permissions": perms, "division_scope": (cfg or {}).get("division_scope") or role_div_default(role)})
        return out

    @app.put("/api/access/roles/{role}", tags=["access-control"])
    async def access_role_save(role: str, body: dict, user=Depends(server.current_user)):
        if role not in server.ROLE_DEFAULTS:
            raise HTTPException(404, "Role tidak ditemukan")
        if role == "admin":
            raise HTTPException(400, "Role Admin selalu memiliki akses penuh dan tidak dapat diubah")
        perms = set((body or {}).get("permissions") or [])
        if perms - ALL_KEYS:
            raise HTTPException(400, "Terdapat hak akses yang tidak dikenal")
        scope = await clean_scope((body or {}).get("division_scope") or role_div_default(role))
        cfg = await db().role_permissions.find_one({"role": role}, {"_id": 0})
        old = set(cfg["permissions"]) if cfg else role_default(role)
        old_scope = (cfg or {}).get("division_scope") or role_div_default(role)
        changed = sorted(old ^ perms)
        await db().role_permissions.update_one({"role": role}, {"$set": {
            "role": role, "permissions": sorted(perms), "division_scope": scope,
            "updated_by": user.get("email"), "updated_at": server.now_iso()}}, upsert=True)
        import tenant_isolation_layer as TI
        _CFG_CACHE.pop((TI.current_tenant_id(), role), None)
        if changed or old_scope != scope:
            before = {k: k in old for k in changed}
            after = {k: k in perms for k in changed}
            if old_scope != scope:
                before["cakupan_divisi"], after["cakupan_divisi"] = old_scope, scope
            await server.audit(user, "edit", "role_permission", role, f"Role {ROLE_LABELS.get(role, role)}",
                               before=before, after=after, reason=f"Perubahan Hak Akses Role ({len(changed)} izin)")
        return {"ok": True, "changed": len(changed)}

    async def target_user(uid, actor):
        u = await db().users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(404, "Pengguna tidak ditemukan")
        if u.get("is_platform_admin"):
            raise HTTPException(403, "Pengguna platform tidak dapat diubah dari pengaturan tenant")
        if u.get("role") == "admin" and actor.get("role") != "admin":
            raise HTTPException(403, "Hanya Admin yang dapat mengubah pengguna Admin")
        return u

    @app.get("/api/access/users/{uid}", tags=["access-control"])
    async def access_user(uid: str, user=Depends(server.current_user)):
        u = await db().users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(404, "Pengguna tidak ditemukan")
        res = await resolve(u)
        return {"id": uid, "name": u.get("name"), "email": u.get("email"), "role": u.get("role"),
                "explicit": isinstance(u.get("permission_overrides"), dict), **res}

    @app.put("/api/access/users/{uid}", tags=["access-control"])
    async def access_user_save(uid: str, body: dict, user=Depends(server.current_user)):
        u = await target_user(uid, user)
        ov = {k: v for k, v in ((body or {}).get("overrides") or {}).items() if v in ("allow", "deny")}
        if set(ov) - ALL_KEYS:
            raise HTTPException(400, "Terdapat hak akses yang tidak dikenal")
        scope = await clean_scope((body or {}).get("division_override"))
        prev = await resolve(u)
        old_ov = prev["overrides"]
        keys = sorted(set(old_ov) | set(ov))
        changed = [k for k in keys if old_ov.get(k) != ov.get(k)]
        await db().users.update_one({"id": uid}, {"$set": {"permission_overrides": ov, "division_override": scope}})
        if changed or prev["division_override"] != scope:
            before = {k: OV_LABEL[old_ov.get(k)] for k in changed}
            after = {k: OV_LABEL[ov.get(k)] for k in changed}
            if prev["division_override"] != scope:
                before["cakupan_divisi"], after["cakupan_divisi"] = _scope_label(prev["division_override"]), _scope_label(scope)
            await server.audit(user, "edit", "user_permission", uid, u.get("email"), before=before, after=after,
                               reason=f"Perubahan Pengaturan Khusus Pengguna ({len(changed)} izin)")
        return {"ok": True, **(await resolve({**u, "permission_overrides": ov, "division_override": scope}))}

    def find(path, method):
        return next((r for r in app.router.routes if getattr(r, "path", "") == path and method in (getattr(r, "methods", set()) or set())), None)

    r = find("/api/users/{uid}", "PUT")
    if r:
        orig_put = r.endpoint
        app.router.routes.remove(r)

        async def update_user(uid: str, body: dict, user=Depends(server.current_user)):
            u = await target_user(uid, user)
            if (body or {}).get("role") == "admin" and user.get("role") != "admin":
                raise HTTPException(403, "Hanya Admin yang dapat memberikan role Admin")
            if body.get("role") and body["role"] not in server.ROLE_DEFAULTS:
                raise HTTPException(400, "Role tidak valid")
            res = await orig_put(uid=uid, body=body, user=user)
            if body.get("role") and body["role"] != u.get("role"):
                await server.audit(user, "edit", "user_role", uid, u.get("email"), before={"role": u.get("role")},
                                   after={"role": body["role"]}, reason="Perubahan Role Pengguna")
            return res
        app.add_api_route("/api/users/{uid}", update_user, methods=["PUT"], tags=["access-control"])

    r = find("/api/users/{uid}", "DELETE")
    if r:
        orig_del = r.endpoint
        app.router.routes.remove(r)

        async def delete_user(uid: str, user=Depends(server.current_user)):
            await target_user(uid, user)
            return await orig_del(uid=uid, user=user)
        app.add_api_route("/api/users/{uid}", delete_user, methods=["DELETE"], tags=["access-control"])

    r = find("/api/users", "POST")
    if r:
        orig_post = r.endpoint
        app.router.routes.remove(r)

        async def create_user(body: dict, user=Depends(server.current_user)):
            if (body or {}).get("role") == "admin" and user.get("role") != "admin":
                raise HTTPException(403, "Hanya Admin yang dapat memberikan role Admin")
            if (body or {}).get("role", "warehouse") not in server.ROLE_DEFAULTS:
                raise HTTPException(400, "Role tidak valid")
            return await orig_post(body=body, user=user)
        app.add_api_route("/api/users", create_user, methods=["POST"], tags=["access-control"])


STOCK_MODS = ["do", "mi", "transfer", "loan", "adjustment", "opname"]
_TX = TXN
# lookup name -> (modules whose Tambah/Edit justify it, modules whose Lihat justify it)
LOOKUP_REASONS = {
    "items": (_TX + ["stock_minmax", "vendor_contracts"], STOCK_MODS + ["stock_minmax", "vendor_contracts"]),
    "warehouses": (_TX + ["stock_minmax", "users"], STOCK_MODS + ["stock_minmax", "users"]),
    "projects": (["mro", "ro", "po", "do", "mi", "loan", "units", "spk"], ["units", "spk"]),
    "units": (["mro", "ro", "po", "mi", "loan"], []),
    "suppliers": (["po", "do", "ro", "vendor_contracts", "invoice"], ["vendor_contracts", "invoice"]),
    "contacts": (["mro", "ro", "po", "projects", "divisions", "spk"], ["projects", "divisions", "spk"]),
    "divisions": (_TX + ["items", "warehouses", "projects", "units", "contacts", "spk", "users"],
                  _TX + ["items", "warehouses", "projects", "units", "contacts", "spk", "users"]),
    "uoms": (_TX + ["items", "vendor_contracts"], STOCK_MODS + ["items", "vendor_contracts"]),
    "taxes": (["po", "suppliers"], ["suppliers"]),
    "item_categories": (["po", "mro", "ro", "items", "suppliers"], STOCK_MODS + ["items", "suppliers"]),
    "supplier_categories": (["po", "suppliers"], ["suppliers"]),
    "spk": (["mro", "ro", "po", "mi", "do"], ["mro", "ro", "po", "mi", "do"]),
}
_COMMON = ["id", "code", "name", "is_active", "division_id"]
LOOKUP_FIELDS = {
    "items": ["unit", "base_uom_id", "uom_id", "uom_name", "uom_conversions", "conversions", "category_id", "specification", "brand", "part_number", "item_type", "uoms"],
    "warehouses": ["location"],
    "projects": ["pic_id", "pic_name", "status", "default_global_budget_policy", "default_category_budget_policy"],
    "units": ["project_id", "plate_no", "unit_type", "type"],
    "suppliers": ["legal_name", "banks", "address", "phone", "email", "contacts", "currency", "payment_term", "lead_time_days", "min_order", "pkp", "npwp",
                  "country", "supplier_type", "supplier_category_id", "supplier_category_name", "supplied_category_ids",
                  "default_tax_id", "default_tax_name", "default_tax_rate"],
    "contacts": ["email", "phone", "position"],
    "divisions": [],
    "uoms": ["symbol", "factor", "base_uom_id"],
    "taxes": ["rate", "type", "is_default"],
    "item_categories": ["parent_id"],
    "supplier_categories": [],
    "spk": ["spk_number", "project_name", "project_id", "status", "start_date", "end_date"],
}


def _install_lookup(server, allowed, in_scope):
    app = server.app

    @app.get("/api/lookup/{name}", tags=["access-control"])
    async def lookup(name: str, q: str = "", active_only: bool = True, limit: int = 0, user=Depends(server.current_user)):
        # Reference data for forms: Tenant -> functional permission -> Division Scope. Minimal fields only.
        if name not in LOOKUP_REASONS:
            raise HTTPException(404, "Data referensi tidak ditemukan")
        eff = set(user.get("effective_permissions") or [])
        edit_mods, view_mods = LOOKUP_REASONS[name]
        ok = user.get("role") == "admin" or f"{name}.view" in eff \
            or any(f"{m}.{a}" in eff for m in edit_mods for a in ("create", "edit")) \
            or any(f"{m}.view" in eff for m in view_mods) \
            or (name == "spk" and any(k.startswith("spk_allocation:") for k in eff))
        if not ok:
            raise HTTPException(403, f"Anda tidak memiliki izin untuk memilih data {MODULES[name][0]}.")
        coll = server.db.spk if name == "spk" else server._mc(name)
        rows = await coll.find({}, {"_id": 0}).to_list(50000)
        alw = allowed(user)
        scoped = name in DIV_MASTERS or name == "spk"
        ql, fields, out = (q or "").strip().lower(), _COMMON + LOOKUP_FIELDS[name], []
        for r in rows:
            if active_only and (r.get("is_active") is False or (name == "spk" and str(r.get("status") or "").lower() not in ("active", "aktif"))):
                continue
            if scoped and not in_scope(r, alw):
                continue
            label = f"{r.get('spk_number')} — {r.get('project_name') or ''}" if name == "spk" else \
                f"{r.get('code') + ' — ' if r.get('code') else ''}{r.get('name') or ''}"
            if ql and ql not in label.lower():
                continue
            out.append({**{k: r[k] for k in fields if k in r}, "label": label})
        out.sort(key=lambda x: x["label"].lower())
        return out[:limit] if limit and limit > 0 else out
