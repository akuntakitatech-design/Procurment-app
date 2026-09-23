"""Automatic tenant isolation for the SaaS migration.

The original application was built as a single-company system. This layer adds a
request-scoped Motor/Mongo proxy so existing routes become tenant-aware without a risky
one-shot rewrite of every transaction module.

Activation is deliberately delayed until startup has finished seeding and the additive
PT REAL tenant backfill has completed. After activation, business collections are scoped
by ``tenant_id`` for reads, writes, counts, deletes, upserts, and aggregations.
"""
from __future__ import annotations

from contextvars import ContextVar
import copy
import inspect
import sys
from typing import Any

from fastapi import Depends, HTTPException, Request

import auth as A
import tenant_foundation_layer as T


_current_tenant: ContextVar[str | None] = ContextVar("procurement_tenant_id", default=None)
_current_company: ContextVar[str | None] = ContextVar("procurement_company_id", default=None)

GLOBAL_COLLECTIONS = {
    "tenants",
    "plans",
    "tenant_migrations",
    "login_attempts",
}

# Before login we do not yet know the tenant. Email/user-id lookup therefore remains
# global only while there is no active request tenant. After authentication, users is
# scoped exactly like every other tenant-owned collection.
GLOBAL_READ_IF_NO_CONTEXT = {"users"}

PASSTHROUGH_COLLECTION_METHODS = {
    "create_index",
    "create_indexes",
    "drop_index",
    "drop_indexes",
    "index_information",
    "options",
    "rename",
}


def current_tenant_id() -> str | None:
    return _current_tenant.get()


def current_company_id() -> str | None:
    return _current_company.get()


def _is_backend_module_file(module_file: str) -> bool:
    normalized = str(module_file or "").replace("\\", "/")
    # Repository/dev layout: .../backend/foo.py. Production Docker layout copies the
    # backend directory into /app, so modules become /app/foo.py.
    return "/backend/" in normalized or normalized.startswith("/app/")


def _is_collection_from(value: Any, raw_db: Any) -> bool:
    try:
        if value.__class__.__name__ == "TenantCollectionProxy":
            return False
        return getattr(value, "database", None) is raw_db and isinstance(getattr(value, "name", None), str)
    except Exception:
        return False


def _scoped_filter(name: str, raw_filter: Any, *, for_write: bool = False) -> Any:
    if name in GLOBAL_COLLECTIONS:
        return raw_filter if raw_filter is not None else {}

    tenant_id = _current_tenant.get()
    if not tenant_id:
        if name in GLOBAL_READ_IF_NO_CONTEXT and not for_write:
            return raw_filter if raw_filter is not None else {}
        tenant_id = T.DEFAULT_TENANT_ID

    base = raw_filter if raw_filter is not None else {}
    if not base:
        return {"tenant_id": tenant_id}
    return {"$and": [base, {"tenant_id": tenant_id}]}


def _tag_document(name: str, document: dict) -> dict:
    doc = copy.deepcopy(document)
    if name not in GLOBAL_COLLECTIONS:
        tenant_id = _current_tenant.get() or T.DEFAULT_TENANT_ID
        doc.setdefault("tenant_id", tenant_id)
        if name == "users":
            doc.setdefault("company_id", _current_company.get() or T.DEFAULT_COMPANY_ID)
    return doc


def _tag_update(name: str, update: Any, *, upsert: bool = False) -> Any:
    if name in GLOBAL_COLLECTIONS or not isinstance(update, dict):
        return update
    tagged = copy.deepcopy(update)
    if upsert:
        tenant_id = _current_tenant.get() or T.DEFAULT_TENANT_ID
        set_on_insert = tagged.setdefault("$setOnInsert", {})
        if isinstance(set_on_insert, dict):
            set_on_insert.setdefault("tenant_id", tenant_id)
            if name == "users":
                set_on_insert.setdefault("company_id", _current_company.get() or T.DEFAULT_COMPANY_ID)
    return tagged


class TenantCollectionProxy:
    def __init__(self, raw_collection: Any):
        self._raw = raw_collection
        self.name = raw_collection.name

    @property
    def database(self):
        return getattr(self._raw, "database", None)

    def find(self, filter: Any = None, *args, **kwargs):
        return self._raw.find(_scoped_filter(self.name, filter), *args, **kwargs)

    async def find_one(self, filter: Any = None, *args, **kwargs):
        return await self._raw.find_one(_scoped_filter(self.name, filter), *args, **kwargs)

    async def count_documents(self, filter: Any, *args, **kwargs):
        return await self._raw.count_documents(_scoped_filter(self.name, filter), *args, **kwargs)

    async def estimated_document_count(self, *args, **kwargs):
        if self.name in GLOBAL_COLLECTIONS:
            return await self._raw.estimated_document_count(*args, **kwargs)
        return await self._raw.count_documents(_scoped_filter(self.name, {}))

    async def insert_one(self, document: dict, *args, **kwargs):
        return await self._raw.insert_one(_tag_document(self.name, document), *args, **kwargs)

    async def insert_many(self, documents, *args, **kwargs):
        return await self._raw.insert_many([_tag_document(self.name, d) for d in documents], *args, **kwargs)

    async def update_one(self, filter: Any, update: Any, *args, **kwargs):
        upsert = bool(kwargs.get("upsert", False))
        return await self._raw.update_one(
            _scoped_filter(self.name, filter, for_write=True),
            _tag_update(self.name, update, upsert=upsert),
            *args, **kwargs,
        )

    async def update_many(self, filter: Any, update: Any, *args, **kwargs):
        upsert = bool(kwargs.get("upsert", False))
        return await self._raw.update_many(
            _scoped_filter(self.name, filter, for_write=True),
            _tag_update(self.name, update, upsert=upsert),
            *args, **kwargs,
        )

    async def replace_one(self, filter: Any, replacement: dict, *args, **kwargs):
        return await self._raw.replace_one(
            _scoped_filter(self.name, filter, for_write=True),
            _tag_document(self.name, replacement),
            *args, **kwargs,
        )

    async def delete_one(self, filter: Any, *args, **kwargs):
        return await self._raw.delete_one(_scoped_filter(self.name, filter, for_write=True), *args, **kwargs)

    async def delete_many(self, filter: Any, *args, **kwargs):
        return await self._raw.delete_many(_scoped_filter(self.name, filter, for_write=True), *args, **kwargs)

    async def find_one_and_update(self, filter: Any, update: Any, *args, **kwargs):
        upsert = bool(kwargs.get("upsert", False))
        return await self._raw.find_one_and_update(
            _scoped_filter(self.name, filter, for_write=True),
            _tag_update(self.name, update, upsert=upsert),
            *args, **kwargs,
        )

    async def find_one_and_replace(self, filter: Any, replacement: dict, *args, **kwargs):
        return await self._raw.find_one_and_replace(
            _scoped_filter(self.name, filter, for_write=True),
            _tag_document(self.name, replacement),
            *args, **kwargs,
        )

    async def find_one_and_delete(self, filter: Any, *args, **kwargs):
        return await self._raw.find_one_and_delete(
            _scoped_filter(self.name, filter, for_write=True), *args, **kwargs
        )

    def aggregate(self, pipeline, *args, **kwargs):
        stages = list(copy.deepcopy(pipeline or []))
        if self.name not in GLOBAL_COLLECTIONS:
            tenant_id = _current_tenant.get() or T.DEFAULT_TENANT_ID
            tenant_match = {"$match": {"tenant_id": tenant_id}}
            if stages and "$geoNear" in stages[0]:
                stages.insert(1, tenant_match)
            else:
                stages.insert(0, tenant_match)
        return self._raw.aggregate(stages, *args, **kwargs)

    async def distinct(self, key: str, filter: Any = None, *args, **kwargs):
        return await self._raw.distinct(key, _scoped_filter(self.name, filter), *args, **kwargs)

    def __getattr__(self, name: str):
        if name in PASSTHROUGH_COLLECTION_METHODS:
            return getattr(self._raw, name)
        # Do not silently allow an unscoped data operation. If a future feature uses one
        # of these methods, it must first be implemented here with tenant awareness.
        if name in {"bulk_write", "find_raw_batches", "aggregate_raw_batches", "watch"}:
            raise RuntimeError(
                f"Collection method '{name}' harus dibuat tenant-aware sebelum digunakan pada {self.name}"
            )
        return getattr(self._raw, name)


class TenantDatabaseProxy:
    def __init__(self, raw_db: Any):
        self._raw = raw_db
        self._collections: dict[str, TenantCollectionProxy] = {}

    def _collection(self, name: str) -> TenantCollectionProxy:
        if name not in self._collections:
            self._collections[name] = TenantCollectionProxy(self._raw[name])
        return self._collections[name]

    def __getitem__(self, name: str):
        return self._collection(name)

    def __getattr__(self, name: str):
        if name in {
            "client", "name", "codec_options", "read_preference", "write_concern", "read_concern",
            "list_collection_names", "list_collections", "command", "create_collection",
            "drop_collection", "validate_collection", "watch", "with_options",
        }:
            return getattr(self._raw, name)
        return self._collection(name)


def _patch_cached_value(value: Any, raw_db: Any, proxy_db: TenantDatabaseProxy, depth: int = 0):
    if value is raw_db:
        return proxy_db, True
    if _is_collection_from(value, raw_db):
        return proxy_db[getattr(value, "name")], True
    if depth >= 2:
        return value, False
    if isinstance(value, dict):
        changed = False
        for key, item in list(value.items()):
            new_item, item_changed = _patch_cached_value(item, raw_db, proxy_db, depth + 1)
            if item_changed:
                value[key] = new_item
                changed = True
        return value, changed
    if isinstance(value, list):
        changed = False
        for idx, item in enumerate(list(value)):
            new_item, item_changed = _patch_cached_value(item, raw_db, proxy_db, depth + 1)
            if item_changed:
                value[idx] = new_item
                changed = True
        return value, changed
    return value, False


def _backend_modules():
    for module_name, module in list(sys.modules.items()):
        if module is None:
            continue
        if _is_backend_module_file(str(getattr(module, "__file__", "") or "")):
            yield module_name, module


def _patch_loaded_backend_modules(raw_db: Any, proxy_db: TenantDatabaseProxy):
    patched = []
    for module_name, module in _backend_modules():
        module_changed = False
        for key, value in list(vars(module).items()):
            # Never rewrite this layer's own raw/proxy state.
            if module is sys.modules.get(__name__) and key.startswith("_"):
                continue
            new_value, changed = _patch_cached_value(value, raw_db, proxy_db)
            if changed:
                try:
                    setattr(module, key, new_value)
                    module_changed = True
                except Exception:
                    pass
        if module_changed:
            patched.append(module_name)
    return sorted(set(patched))


def _find_raw_references(raw_db: Any, app: Any):
    leftovers = []
    for module_name, module in _backend_modules():
        for key, value in list(vars(module).items()):
            if module is sys.modules.get(__name__) and key.startswith("_"):
                continue
            if value is raw_db or _is_collection_from(value, raw_db):
                leftovers.append(f"{module_name}.{key}")
            elif isinstance(value, dict):
                for dict_key, item in value.items():
                    if item is raw_db or _is_collection_from(item, raw_db):
                        leftovers.append(f"{module_name}.{key}[{dict_key!r}]")

    # A layer may capture a raw collection/database in a FastAPI endpoint closure instead
    # of storing it as a module global. Detect such closures so we fail review rather than
    # declaring isolation complete while a bypass remains.
    for route in getattr(app, "routes", []):
        endpoint = getattr(route, "endpoint", None)
        closure = getattr(endpoint, "__closure__", None) if endpoint else None
        if not closure:
            continue
        for idx, cell in enumerate(closure):
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if value is raw_db or _is_collection_from(value, raw_db):
                path = getattr(route, "path", "?")
                leftovers.append(f"route:{path}:closure[{idx}]")
    return sorted(set(leftovers))


def install(server):
    app = server.app
    raw_db = server.db
    proxy_db = TenantDatabaseProxy(raw_db)
    state = {"installed": False, "patched_modules": [], "raw_references": []}

    @app.middleware("http")
    async def tenant_context_middleware(request: Request, call_next):
        tenant_token = None
        company_token = None
        try:
            try:
                # Resolve identity against the raw users collection before tenant scope is known.
                user = await A.get_current_user(request, raw_db)
            except HTTPException:
                user = None

            if user:
                tenant_token = _current_tenant.set(user.get("tenant_id") or T.DEFAULT_TENANT_ID)
                company_token = _current_company.set(user.get("company_id") or T.DEFAULT_COMPANY_ID)
            return await call_next(request)
        finally:
            if company_token is not None:
                _current_company.reset(company_token)
            if tenant_token is not None:
                _current_tenant.reset(tenant_token)

    @app.on_event("startup")
    async def activate_tenant_isolation():
        # Registered after server.startup and tenant_foundation startup: migration runs raw,
        # runtime requests run through the scoped proxy.
        server.raw_db = raw_db
        server.db = proxy_db
        patched = _patch_loaded_backend_modules(raw_db, proxy_db)
        leftovers = _find_raw_references(raw_db, app)
        state.update(installed=True, patched_modules=patched, raw_references=leftovers)

        await raw_db.tenants.update_one(
            {"id": T.DEFAULT_TENANT_ID},
            {"$set": {
                "isolation_layer_installed": True,
                "isolation_ready": False,
                "isolation_pending_reason": (
                    "integration-test-required" if not leftovers else "raw-database-references-detected"
                ),
                "isolation_raw_reference_count": len(leftovers),
                "isolation_updated_at": T.now_iso(),
            }},
        )
        server.logger.info(
            "Tenant isolation installed; patched_modules=%s raw_refs=%s",
            len(patched), len(leftovers),
        )

    @app.get("/api/tenant/isolation-status", tags=["tenant"])
    async def isolation_status(user=Depends(server.current_user)):
        server.require(user, "view")
        tenant_id = T.tenant_id_of(user)
        # The status endpoint reads only the global tenant catalog. Use the proxy's
        # explicitly-global tenants collection so the self-check does not report its own
        # diagnostic endpoint as a raw-database bypass.
        tenant = await proxy_db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
        return {
            "tenant_id": tenant_id,
            "installed": state["installed"],
            "ready": bool(tenant.get("isolation_ready")),
            "pending_reason": tenant.get("isolation_pending_reason"),
            "patched_module_count": len(state["patched_modules"]),
            "patched_modules": state["patched_modules"],
            "raw_reference_count": len(state["raw_references"]),
            "raw_references": state["raw_references"][:100],
        }