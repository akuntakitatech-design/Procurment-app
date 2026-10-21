"""Hapus Tenant dua tahap untuk Platform Super Admin.

Tahap 1 — Hapus (soft delete): status tenant `deleted`, workspace terkunci (subscription gate), seluruh sesi user
tenant dicabut (token_version +1), token aktivasi pending dicabut. Data tetap utuh dan tenant dapat dipulihkan.
Tahap 2 — Hapus Permanen (purge): hanya untuk tenant berstatus `deleted`. Menghapus semua objek storage di prefix
tenant (`procureflow/tenants/<tenant_id>/`), semua dokumen ber-`tenant_id` di seluruh koleksi, lalu dokumen tenant.
Jejak `platform_audit_logs` dipertahankan sebagai bukti audit.

Pengaman: khusus Platform Super Admin; tenant default (DEFAULT_TENANT_ID) dan tenant platform tidak pernah dapat
dihapus; konfirmasi wajib mengetik ulang kode tenant; setiap aksi tercatat di platform_audit_logs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import saas_platform_layer as P
import storage as S
import tenant_foundation_layer as T

PROTECTED_TENANT_IDS = {"platform-root"}
# Koleksi global/platform yang tidak pernah dibersihkan oleh purge tenant.
KEEP_COLLECTIONS = {"tenants", "plans", "platform_audit_logs", "platform_settings", "login_attempts"}
DELETED = "deleted"


class DeleteIn(BaseModel):
    confirm_code: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=3, max_length=500)


class PurgeIn(BaseModel):
    confirm_code: str = Field(min_length=1, max_length=60)


class RestoreIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def storage_prefix(tenant_id: str) -> str:
    return f"{S.APP_NAME}/tenants/{tenant_id}/"


def is_protected(tenant_id: str | None) -> bool:
    return not tenant_id or tenant_id == T.DEFAULT_TENANT_ID or tenant_id in PROTECTED_TENANT_IDS


def _confirm_code(tenant: dict) -> str:
    return str(tenant.get("tenant_code") or tenant.get("id") or "").strip()


def _check_confirm(tenant: dict, code: str):
    expected = _confirm_code(tenant)
    if not expected or (code or "").strip().upper() != expected.upper():
        raise HTTPException(status_code=400, detail=f"Kode konfirmasi tidak sesuai. Ketik kode tenant persis: {expected}")


def _tenant_filter(name: str, tenant_id: str) -> dict:
    flt = {"tenant_id": tenant_id}
    if name == "users":
        flt["is_platform_admin"] = {"$ne": True}
    return flt


async def _collections(db) -> list:
    names = await db.list_collection_names()
    return sorted(n for n in names if n and not n.startswith("_") and n not in KEEP_COLLECTIONS)


async def _count_by_collection(db, tenant_id: str) -> dict:
    sem = asyncio.Semaphore(8)

    async def one(name):
        async with sem:
            return name, await db[name].count_documents(_tenant_filter(name, tenant_id))

    rows = await asyncio.gather(*(one(n) for n in await _collections(db)))
    return {n: c for n, c in rows if c}


async def _storage_summary(tenant_id: str) -> dict:
    objs = await asyncio.to_thread(S.list_prefix, storage_prefix(tenant_id))
    return {"prefix": storage_prefix(tenant_id), "objects": len(objs), "bytes": sum(size for _, size in objs)}


async def _get_tenant(db, tenant_id: str) -> dict:
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
    return tenant


def install(server):
    app = server.app

    def guard(tenant: dict):
        if is_protected(tenant.get("id")):
            raise HTTPException(status_code=409, detail="Tenant default/utama platform tidak dapat dihapus")

    # ---- PREVIEW DAMPAK ----
    @app.get("/api/platform/tenants/{tenant_id}/delete-preview", tags=["platform"])
    async def delete_preview(tenant_id: str, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await _get_tenant(db, tenant_id)
        protected = is_protected(tenant_id)
        counts = {} if protected else await _count_by_collection(db, tenant_id)
        try:
            storage = {} if protected else await _storage_summary(tenant_id)
        except Exception as exc:  # storage tidak terjangkau -> preview tetap tampil
            storage = {"prefix": storage_prefix(tenant_id), "objects": None, "bytes": None, "error": str(exc)[:200]}
        return {
            "tenant_id": tenant_id,
            "tenant_code": tenant.get("tenant_code"),
            "name": tenant.get("name"),
            "status": tenant.get("status"),
            "confirm_code": _confirm_code(tenant),
            "deletable": not protected and tenant.get("status") != DELETED,
            "purgeable": not protected and tenant.get("status") == DELETED,
            "protected": protected,
            "users": counts.get("users", 0),
            "collections": counts,
            "total_documents": sum(counts.values()),
            "storage": storage,
            "deleted_at": tenant.get("deleted_at"),
            "deleted_by": tenant.get("deleted_by"),
            "deleted_reason": tenant.get("deleted_reason"),
        }

    # ---- TAHAP 1: HAPUS (SOFT DELETE) ----
    @app.post("/api/platform/tenants/{tenant_id}/delete", tags=["platform"])
    async def soft_delete_tenant(tenant_id: str, body: DeleteIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await _get_tenant(db, tenant_id)
        guard(tenant)
        if tenant.get("status") == DELETED:
            raise HTTPException(status_code=409, detail="Tenant sudah berstatus dihapus")
        _check_confirm(tenant, body.confirm_code)
        now, reason = _now_iso(), body.reason.strip()
        sub = tenant.get("subscription") or {}
        entry = {"action": "delete", "reason": reason, "at": now, "by": user.get("email"),
                 "prev_status": tenant.get("status"), "prev_subscription_status": sub.get("status")}
        await db.tenants.update_one({"id": tenant_id}, {
            "$set": {"status": DELETED, "subscription.status": DELETED, "deleted_at": now,
                     "deleted_by": user.get("email"), "deleted_reason": reason,
                     "deleted_prev_status": tenant.get("status"),
                     "deleted_prev_subscription_status": sub.get("status"), "updated_at": now},
            "$push": {"deletion_history": entry},
        })
        # Cabut seluruh sesi aktif user tenant & token aktivasi yang masih menunggu.
        revoked = await db.users.update_many(_tenant_filter("users", tenant_id), {"$inc": {"token_version": 1}})
        await db.tenant_activations.update_many({"tenant_id": tenant_id, "status": "pending"},
                                                {"$set": {"status": "revoked", "revoked_at": now}})
        await P._platform_audit(server, user, "tenant.deleted", tenant_id, {
            "tenant_code": tenant.get("tenant_code"), "name": tenant.get("name"), "reason": reason,
            "prev_status": tenant.get("status"), "sessions_revoked": getattr(revoked, "modified_count", None)})
        return {"ok": True, "tenant_id": tenant_id, "status": DELETED,
                "message": f"Tenant {tenant.get('tenant_code')} dihapus (dapat dipulihkan atau dihapus permanen)."}

    # ---- PULIHKAN ----
    @app.post("/api/platform/tenants/{tenant_id}/restore", tags=["platform"])
    async def restore_tenant(tenant_id: str, body: RestoreIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await _get_tenant(db, tenant_id)
        if tenant.get("status") != DELETED:
            raise HTTPException(status_code=409, detail="Hanya tenant berstatus dihapus yang dapat dipulihkan")
        if tenant.get("purge_started_at"):
            raise HTTPException(status_code=409, detail="Hapus permanen sudah dimulai; tenant tidak dapat dipulihkan")
        now = _now_iso()
        prev_status = tenant.get("deleted_prev_status")
        prev_status = prev_status if prev_status and prev_status != DELETED else "active"
        prev_sub = tenant.get("deleted_prev_subscription_status")
        prev_sub = prev_sub if prev_sub and prev_sub != DELETED else "active"
        entry = {"action": "restore", "reason": (body.reason or "").strip() or None, "at": now, "by": user.get("email")}
        await db.tenants.update_one({"id": tenant_id}, {
            "$set": {"status": prev_status, "subscription.status": prev_sub, "updated_at": now},
            "$unset": {"deleted_at": "", "deleted_by": "", "deleted_reason": "",
                       "deleted_prev_status": "", "deleted_prev_subscription_status": ""},
            "$push": {"deletion_history": entry},
        })
        await P._platform_audit(server, user, "tenant.restored", tenant_id, {
            "tenant_code": tenant.get("tenant_code"), "status": prev_status, "subscription_status": prev_sub,
            "reason": entry["reason"]})
        return {"ok": True, "tenant_id": tenant_id, "status": prev_status,
                "message": f"Tenant {tenant.get('tenant_code')} dipulihkan."}

    # ---- TAHAP 2: HAPUS PERMANEN ----
    @app.post("/api/platform/tenants/{tenant_id}/purge", tags=["platform"])
    async def purge_tenant(tenant_id: str, body: PurgeIn, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await _get_tenant(db, tenant_id)
        guard(tenant)
        if tenant.get("status") != DELETED:
            raise HTTPException(status_code=409, detail="Hapus tenant terlebih dahulu sebelum hapus permanen")
        _check_confirm(tenant, body.confirm_code)
        await db.tenants.update_one({"id": tenant_id}, {"$set": {"purge_started_at": _now_iso(),
                                                                 "purge_started_by": user.get("email")}})
        # Storage dulu: bila gagal, data DB masih utuh dan purge dapat diulang (idempoten).
        try:
            objs = await asyncio.to_thread(S.list_prefix, storage_prefix(tenant_id))
            deleted_objects = await asyncio.to_thread(S.delete_keys, [k for k, _ in objs])
        except Exception as exc:
            server.logger.error("purge tenant %s: storage gagal: %s", tenant_id, exc)
            raise HTTPException(status_code=502, detail=f"Gagal menghapus file storage tenant; tidak ada data yang dihapus. ({str(exc)[:160]})")
        deleted_docs = {}
        for name in await _collections(db):
            res = await db[name].delete_many(_tenant_filter(name, tenant_id))
            n = int(getattr(res, "deleted_count", 0) or 0)
            if n:
                deleted_docs[name] = n
        await db.tenants.delete_one({"id": tenant_id})
        summary = {"tenant_code": tenant.get("tenant_code"), "name": tenant.get("name"),
                   "documents_deleted": sum(deleted_docs.values()), "collections": deleted_docs,
                   "storage_objects_deleted": deleted_objects,
                   "storage_bytes_deleted": sum(size for _, size in objs)}
        await P._platform_audit(server, user, "tenant.purged", tenant_id, summary)
        server.logger.info("Tenant %s (%s) dihapus permanen: %s dokumen, %s objek storage",
                           tenant_id, tenant.get("tenant_code"), summary["documents_deleted"], deleted_objects)
        return {"ok": True, "tenant_id": tenant_id, **summary,
                "message": f"Tenant {tenant.get('tenant_code')} dihapus permanen."}

    server.logger.info("Tenant delete (soft + purge) layer installed")
