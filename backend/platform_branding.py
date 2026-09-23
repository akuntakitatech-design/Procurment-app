"""Global application branding for KelolaKita Procurement."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import storage as S


BRANDING_ID = "platform-branding"

ALLOWED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

MAX_LOGO_SIZE = 5 * 1024 * 1024


def _global_db(server):
    db = server.db
    raw = getattr(db, "_raw", None)
    return raw if raw is not None else db


def _global_put_object(path: str, data: bytes, content_type: str):
    fn = getattr(S, "_tenant_storage_original_put", S.put_object)
    return fn(path, data, content_type)


def _global_get_object(path: str):
    fn = getattr(S, "_tenant_storage_original_get", S.get_object)

    raw = str(path or "").strip()
    clean = raw.lstrip("/")

    for prefix in ("/app/data/uploads/", "app/data/uploads/", "/data/", "data/"):
        if clean.startswith(prefix.lstrip("/")):
            clean = clean[len(prefix.lstrip("/")):]

    candidates = [clean]

    platform_prefix = f"{S.APP_NAME}/tenants/platform-root/branding/"
    global_prefix = f"{S.APP_NAME}/branding/"

    if clean.startswith(platform_prefix):
        candidates.append(global_prefix + Path(clean).name)
    elif clean.startswith(global_prefix):
        candidates.append(platform_prefix + Path(clean).name)

    last_error = None
    for candidate in dict.fromkeys(candidates):
        try:
            return fn(candidate)
        except FileNotFoundError as e:
            last_error = e

    raise last_error or FileNotFoundError(clean)


def _require_platform_admin(user):
    if not user or not user.get("is_platform_admin"):
        raise HTTPException(
            status_code=403,
            detail="Akses khusus Super Admin platform",
        )


def _defaults():
    return {
        "id": BRANDING_ID,
        "name": "KelolaKita Procurement",
        "tagline": "Kelola Bersama. Tumbuh Bersama.",
        "subtitle": "Procurement • Warehouse • Inventory",
        "logo_available": False,
        "logo_version": None,
    }


class PlatformBrandingPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    tagline: str | None = Field(default=None, max_length=180)
    subtitle: str | None = Field(default=None, max_length=180)


def install(server):
    app = server.app

    @app.get("/api/platform-branding", tags=["platform-branding"])
    async def public_platform_branding():
        db = _global_db(server)
        row = await db.platform_settings.find_one(
            {"id": BRANDING_ID},
            {"_id": 0},
        ) or {}

        defaults = _defaults()

        return {
            "name": row.get("name") or defaults["name"],
            "tagline": row.get("tagline") or defaults["tagline"],
            "subtitle": row.get("subtitle") or defaults["subtitle"],
            "logo_available": bool(row.get("logo_path")),
            "logo_version": row.get("logo_version"),
        }

    @app.get("/api/platform-branding/logo", tags=["platform-branding"])
    async def public_platform_logo():
        db = _global_db(server)

        row = await db.platform_settings.find_one(
            {"id": BRANDING_ID},
            {"_id": 0},
        ) or {}

        path = row.get("logo_path")

        if not path:
            raise HTTPException(
                status_code=404,
                detail="Logo aplikasi belum diupload",
            )

        try:
            data, detected_type = _global_get_object(path)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="File logo aplikasi tidak ditemukan",
            )

        content_type = (
            row.get("logo_content_type")
            or detected_type
            or "image/png"
        )

        return Response(
            content=data,
            media_type=content_type,
            headers={"Cache-Control": "no-cache"},
        )

    @app.patch("/api/platform/branding", tags=["platform"])
    async def update_platform_branding(
        body: PlatformBrandingPatch,
        user=Depends(server.current_user),
    ):
        _require_platform_admin(user)
        db = _global_db(server)

        update = {}

        if body.name is not None:
            update["name"] = body.name.strip()

        if body.tagline is not None:
            update["tagline"] = body.tagline.strip()

        if body.subtitle is not None:
            update["subtitle"] = body.subtitle.strip()

        if update:
            update["updated_at"] = server.now_iso()

            await db.platform_settings.update_one(
                {"id": BRANDING_ID},
                {
                    "$set": update,
                    "$setOnInsert": {"id": BRANDING_ID},
                },
                upsert=True,
            )

        await db.platform_audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "action": "platform.branding.update",
            "tenant_id": None,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "after": update,
            "at": server.now_iso(),
        })

        return await public_platform_branding()

    @app.post("/api/platform/branding/logo", tags=["platform"])
    async def upload_platform_logo(
        file: UploadFile = File(...),
        user=Depends(server.current_user),
    ):
        _require_platform_admin(user)
        db = _global_db(server)

        content_type = (file.content_type or "").lower()
        ext = ALLOWED_TYPES.get(content_type)

        if not ext:
            raise HTTPException(
                status_code=400,
                detail="Logo harus PNG, JPG/JPEG, atau WEBP",
            )

        data = await file.read()

        if not data:
            raise HTTPException(
                status_code=400,
                detail="File logo kosong",
            )

        if len(data) > MAX_LOGO_SIZE:
            raise HTTPException(
                status_code=400,
                detail="Ukuran logo maksimal 5 MB",
            )

        path = f"{S.APP_NAME}/branding/platform-logo.{ext}"
        result = _global_put_object(path, data, content_type)
        version = server.now_iso()

        update = {
            "logo_path": result["path"],
            "logo_filename": Path(
                file.filename or f"platform-logo.{ext}"
            ).name,
            "logo_content_type": content_type,
            "logo_size": result.get("size", len(data)),
            "logo_version": version,
            "updated_at": version,
        }

        await db.platform_settings.update_one(
            {"id": BRANDING_ID},
            {
                "$set": update,
                "$setOnInsert": {
                    "id": BRANDING_ID,
                    "name": "KelolaKita Procurement",
                    "tagline": "Kelola Bersama. Tumbuh Bersama.",
                    "subtitle": "Procurement • Warehouse • Inventory",
                },
            },
            upsert=True,
        )

        await db.platform_audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "action": "platform.branding.logo.upload",
            "tenant_id": None,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "after": {
                "filename": update["logo_filename"],
                "size": update["logo_size"],
            },
            "at": server.now_iso(),
        })

        return await public_platform_branding()

    @app.delete("/api/platform/branding/logo", tags=["platform"])
    async def delete_platform_logo(
        user=Depends(server.current_user),
    ):
        _require_platform_admin(user)
        db = _global_db(server)

        await db.platform_settings.update_one(
            {"id": BRANDING_ID},
            {
                "$unset": {
                    "logo_path": "",
                    "logo_filename": "",
                    "logo_content_type": "",
                    "logo_size": "",
                    "logo_version": "",
                },
                "$set": {
                    "updated_at": server.now_iso(),
                },
            },
            upsert=True,
        )

        await db.platform_audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "action": "platform.branding.logo.delete",
            "tenant_id": None,
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "after": {},
            "at": server.now_iso(),
        })

        return {"ok": True}
