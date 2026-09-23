"""Security hardening on top of tenant isolation.

This layer closes bypass/integrity gaps that are not solved by adding a root tenant filter:
- tenant_id ownership cannot be injected/mutated through collection proxy writes
- update pipelines and cross-collection aggregation stages are rejected until tenant-aware
- raw collection.database / raw DB command/client/watch shortcuts are blocked
- transaction source references must resolve inside the active tenant before any write occurs
- attachment downloads require authentication and storage keys are tenant-prefixed

It is intentionally additive and installed only on the multi-tenant feature branch for testing.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from fastapi.responses import JSONResponse

import auth as A
import storage as S
import tenant_foundation_layer as T
import tenant_isolation_layer as I


BLOCKED_AGGREGATION_STAGES = {"$lookup", "$unionWith", "$graphLookup", "$out", "$merge", "$geoNear"}
SAFE_COLLECTION_PASSTHROUGH = {
    "create_index", "create_indexes", "drop_index", "drop_indexes",
    "index_information", "options", "full_name", "codec_options",
    "read_preference", "write_concern", "read_concern",
}
BLOCKED_DB_SHORTCUTS = {
    "client", "command", "watch", "with_options", "create_collection",
    "drop_collection", "validate_collection",
}


def _tenant_id() -> str:
    return I.current_tenant_id() or T.DEFAULT_TENANT_ID


def _company_id() -> str:
    return I.current_company_id() or T.DEFAULT_COMPANY_ID


def _hardened_tag_document(name: str, document: dict) -> dict:
    doc = copy.deepcopy(document)
    if name in I.GLOBAL_COLLECTIONS:
        return doc
    doc["tenant_id"] = _tenant_id()
    if name == "users" and not doc.get("company_id"):
        doc["company_id"] = _company_id()
    return doc


def _hardened_tag_update(name: str, update: Any, *, upsert: bool = False) -> Any:
    if name in I.GLOBAL_COLLECTIONS:
        return copy.deepcopy(update)
    if isinstance(update, list):
        raise RuntimeError("Update pipeline belum diizinkan pada collection tenant-scoped")
    if not isinstance(update, dict):
        raise RuntimeError("Update tenant-scoped harus berupa operator update MongoDB")

    tagged = copy.deepcopy(update)
    tenant_id = _tenant_id()

    # Replacement-style updates belong in replace_one/find_one_and_replace, where the
    # replacement document is force-tagged. Reject ambiguous replacement updates here.
    if tagged and not any(str(k).startswith("$") for k in tagged):
        raise RuntimeError("Replacement update harus menggunakan replace_one agar ownership aman")

    set_doc = tagged.setdefault("$set", {})
    if not isinstance(set_doc, dict):
        raise RuntimeError("Operator $set tidak valid")
    # $set berlaku juga pada dokumen hasil upsert, jadi tenant_id cukup dipaksa di sini.
    # Jangan menaruh tenant_id lagi di $setOnInsert karena MongoDB akan menolak dua
    # operator yang mengubah path yang sama pada satu update.
    set_doc["tenant_id"] = tenant_id

    unset_doc = tagged.get("$unset")
    if isinstance(unset_doc, dict):
        unset_doc.pop("tenant_id", None)
        if not unset_doc:
            tagged.pop("$unset", None)

    rename_doc = tagged.get("$rename")
    if isinstance(rename_doc, dict):
        for source, target in list(rename_doc.items()):
            if source == "tenant_id" or target == "tenant_id":
                raise RuntimeError("tenant_id tidak boleh di-rename")

    if upsert:
        soi = tagged.setdefault("$setOnInsert", {})
        if not isinstance(soi, dict):
            raise RuntimeError("Operator $setOnInsert tidak valid")
        # Hapus tenant_id dari payload $setOnInsert user/caller untuk mencegah konflik
        # dengan $set di atas sekaligus mencegah ownership injection.
        soi.pop("tenant_id", None)
        if name == "users" and not soi.get("company_id"):
            soi["company_id"] = _company_id()
        if not soi:
            tagged.pop("$setOnInsert", None)

    return tagged


def _contains_blocked_stage(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in BLOCKED_AGGREGATION_STAGES:
                return key
            found = _contains_blocked_stage(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _contains_blocked_stage(item)
            if found:
                return found
    return None


def _hardened_aggregate(self, pipeline, *args, **kwargs):
    stages = list(copy.deepcopy(pipeline or []))
    if self.name not in I.GLOBAL_COLLECTIONS:
        blocked = _contains_blocked_stage(stages)
        if blocked:
            raise RuntimeError(
                f"Aggregation stage '{blocked}' diblokir sampai memiliki tenant-scope eksplisit"
            )
        stages.insert(0, {"$match": {"tenant_id": _tenant_id()}})
    return self._raw.aggregate(stages, *args, **kwargs)


def _blocked_collection_database(self):
    raise RuntimeError("Akses raw collection.database diblokir pada tenant-scoped runtime")


def _hardened_collection_getattr(self, name: str):
    if name in SAFE_COLLECTION_PASSTHROUGH:
        return getattr(self._raw, name)
    if name in {"bulk_write", "find_raw_batches", "aggregate_raw_batches", "watch", "rename", "drop"}:
        raise RuntimeError(
            f"Collection method '{name}' harus dibuat tenant-aware sebelum digunakan pada {self.name}"
        )
    # Fail closed for any new/unreviewed collection operation.
    raise RuntimeError(
        f"Collection attribute/method '{name}' belum diizinkan pada tenant-scoped runtime ({self.name})"
    )


def _hardened_database_getattr(self, name: str):
    if name in BLOCKED_DB_SHORTCUTS:
        raise RuntimeError(f"Raw database shortcut '{name}' diblokir pada tenant-scoped runtime")
    if name in {"name", "codec_options", "read_preference", "write_concern", "read_concern", "list_collection_names", "list_collections"}:
        return getattr(self._raw, name)
    return self._collection(name)


def _install_proxy_hardening():
    I._tag_document = _hardened_tag_document
    I._tag_update = _hardened_tag_update
    I.TenantCollectionProxy.aggregate = _hardened_aggregate
    I.TenantCollectionProxy.database = property(_blocked_collection_database)
    I.TenantCollectionProxy.__getattr__ = _hardened_collection_getattr
    I.TenantDatabaseProxy.__getattr__ = _hardened_database_getattr


def _install_storage_hardening():
    if getattr(S, "_tenant_storage_hardening_installed", False):
        return

    original_put = S.put_object
    original_get = S.get_object

    def scoped_put_object(path: str, data: bytes, content_type: str):
        tenant_id = _tenant_id()
        normalized = str(path or "").replace("\\", "/").lstrip("/")
        prefix = f"{S.APP_NAME}/tenants/{tenant_id}/"
        if normalized.startswith(prefix):
            target = normalized
        else:
            app_prefix = f"{S.APP_NAME}/"
            suffix = normalized[len(app_prefix):] if normalized.startswith(app_prefix) else normalized
            target = f"{prefix}{suffix}"
        result = original_put(target, data, content_type)
        result["path"] = target
        return result

    def scoped_get_object(path: str):
        tenant_id = _tenant_id()
        normalized = str(path or "").replace("\\", "/").lstrip("/")
        own_prefix = f"{S.APP_NAME}/tenants/{tenant_id}/"
        tenants_root = f"{S.APP_NAME}/tenants/"

        if normalized.startswith(tenants_root) and not normalized.startswith(own_prefix):
            raise FileNotFoundError(path)
        # Backward compatibility: legacy unprefixed files belong only to the original tenant.
        if not normalized.startswith(tenants_root) and tenant_id != T.DEFAULT_TENANT_ID:
            raise FileNotFoundError(path)
        return original_get(normalized)

    S.put_object = scoped_put_object
    S.get_object = scoped_get_object
    S._tenant_storage_hardening_installed = True


async def _user_from_query_token(server, token: str):
    try:
        payload = A.jwt.decode(token, A.get_jwt_secret(), algorithms=[A.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        raw_db = getattr(server, "raw_db", None)
        if raw_db is None:
            return None
        user = await raw_db.users.find_one({"id": payload.get("sub")})
        if not user or payload.get("ver", 0) != user.get("token_version", 0):
            return None
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except Exception:
        return None


async def _validate_transaction_sources(server, path: str, body: dict):
    db = server.db
    lines = body.get("lines") or []

    if path == "/api/ro":
        for line in lines:
            for src in line.get("sources") or []:
                mline = await db.mro_lines.find_one({"id": src.get("line_id"), "mro_id": src.get("mro_id")})
                if not mline:
                    return "Sumber MRO tidak ditemukan pada tenant aktif"
                if mline.get("item_id") != line.get("item_id"):
                    return "Item sumber MRO tidak sesuai dengan item RO"
                mro = await db.mro.find_one({"id": src.get("mro_id")})
                if not mro:
                    return "Dokumen MRO sumber tidak ditemukan pada tenant aktif"

    elif path == "/api/po":
        for line in lines:
            for src in line.get("sources") or []:
                rline = await db.ro_lines.find_one({"id": src.get("line_id"), "ro_id": src.get("ro_id")})
                if not rline:
                    return "Sumber RO tidak ditemukan pada tenant aktif"
                if rline.get("item_id") != line.get("item_id"):
                    return "Item sumber RO tidak sesuai dengan item PO"
                ro = await db.ro.find_one({"id": src.get("ro_id")})
                if not ro:
                    return "Dokumen RO sumber tidak ditemukan pada tenant aktif"

    elif path == "/api/do":
        for line in lines:
            if float(line.get("qty") or 0) <= 0:
                continue
            if not line.get("po_line_id") or not line.get("po_id"):
                return "DO wajib memiliki referensi PO dan baris PO"
            pline = await db.po_lines.find_one({"id": line.get("po_line_id"), "po_id": line.get("po_id")})
            if not pline:
                return "Sumber PO tidak ditemukan pada tenant aktif"
            if pline.get("item_id") != line.get("item_id"):
                return "Item sumber PO tidak sesuai dengan item DO"
            po = await db.po.find_one({"id": line.get("po_id")})
            if not po:
                return "Dokumen PO sumber tidak ditemukan pada tenant aktif"

    elif path == "/api/mi":
        for line in lines:
            if not line.get("mro_line_id"):
                continue
            if not line.get("mro_id"):
                return "MI berbasis MRO wajib memiliki referensi dokumen MRO"
            mline = await db.mro_lines.find_one({"id": line.get("mro_line_id"), "mro_id": line.get("mro_id")})
            if not mline:
                return "Sumber MRO untuk MI tidak ditemukan pada tenant aktif"
            if mline.get("item_id") != line.get("item_id"):
                return "Item sumber MRO tidak sesuai dengan item MI"
            mro = await db.mro.find_one({"id": line.get("mro_id")})
            if not mro:
                return "Dokumen MRO sumber untuk MI tidak ditemukan pada tenant aktif"

    return None


def install(server):
    _install_proxy_hardening()
    _install_storage_hardening()
    app = server.app

    @app.middleware("http")
    async def tenant_security_gate(request, call_next):
        path = request.url.path

        # Backward-compatible attachment query-token support, but no anonymous download.
        query_tenant_token = None
        query_company_token = None
        if request.method.upper() == "GET" and re.fullmatch(r"/api/attachments/[^/]+/download", path):
            try:
                await server.current_user(request)
            except Exception:
                token = request.query_params.get("auth")
                user = await _user_from_query_token(server, token) if token else None
                if not user:
                    return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
                query_tenant_token = I._current_tenant.set(user.get("tenant_id") or T.DEFAULT_TENANT_ID)
                query_company_token = I._current_company.set(user.get("company_id") or T.DEFAULT_COMPANY_ID)

        try:
            if request.method.upper() == "POST" and path in {"/api/ro", "/api/po", "/api/do", "/api/mi"}:
                try:
                    body = await request.json()
                except Exception:
                    body = None
                if isinstance(body, dict):
                    message = await _validate_transaction_sources(server, path, body)
                    if message:
                        return JSONResponse(status_code=404, content={"detail": message})
            return await call_next(request)
        finally:
            if query_company_token is not None:
                I._current_company.reset(query_company_token)
            if query_tenant_token is not None:
                I._current_tenant.reset(query_tenant_token)
