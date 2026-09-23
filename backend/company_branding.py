"""Company branding and local logo upload for self-hosted production."""
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

import storage as S


ALLOWED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
MAX_LOGO_SIZE = 5 * 1024 * 1024


def install(server):
    @server.app.get("/api/branding")
    async def get_branding():
        company = await server.db.settings.find_one({"id": "company"}, {"_id": 0}) or {}
        return {
            "name": company.get("name") or "App Proc",
            "subtitle": company.get("app_subtitle") or "Procurement & Inventory",
            "logo_available": bool(company.get("logo_path")),
            "logo_version": company.get("logo_version"),
        }

    @server.app.get("/api/company/logo")
    async def get_company_logo():
        company = await server.db.settings.find_one({"id": "company"}, {"_id": 0}) or {}
        path = company.get("logo_path")
        if not path:
            raise HTTPException(status_code=404, detail="Logo perusahaan belum diupload")
        try:
            data, detected_type = S.get_object(path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File logo tidak ditemukan")
        content_type = company.get("logo_content_type") or detected_type or "image/png"
        return Response(content=data, media_type=content_type, headers={"Cache-Control": "no-cache"})

    @server.app.post("/api/settings/company/logo")
    async def upload_company_logo(
        file: UploadFile = File(...),
        user=Depends(server.current_user),
    ):
        server.require(user, "edit")
        content_type = (file.content_type or "").lower()
        ext = ALLOWED_TYPES.get(content_type)
        if not ext:
            raise HTTPException(status_code=400, detail="Logo harus PNG, JPG/JPEG, atau WEBP")

        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="File logo kosong")
        if len(data) > MAX_LOGO_SIZE:
            raise HTTPException(status_code=400, detail="Ukuran logo maksimal 5 MB")

        path = f"{S.APP_NAME}/branding/company-logo.{ext}"
        result = S.put_object(path, data, content_type)
        version = server.now_iso()
        update = {
            "logo_path": result["path"],
            "logo_filename": Path(file.filename or f"logo.{ext}").name,
            "logo_content_type": content_type,
            "logo_size": result.get("size", len(data)),
            "logo_version": version,
            "logo_url": None,
        }
        await server.db.settings.update_one(
            {"id": "company"},
            {"$set": update, "$setOnInsert": {"id": "company", "name": "App Proc"}},
            upsert=True,
        )
        await server.audit(user, "upload_logo", "settings", "company", after={"file": update["logo_filename"]})
        company = await server.db.settings.find_one({"id": "company"}, {"_id": 0})
        return company

    @server.app.delete("/api/settings/company/logo")
    async def delete_company_logo(user=Depends(server.current_user)):
        server.require(user, "edit")
        await server.db.settings.update_one(
            {"id": "company"},
            {"$unset": {
                "logo_path": "",
                "logo_filename": "",
                "logo_content_type": "",
                "logo_size": "",
                "logo_version": "",
                "logo_url": "",
            }},
        )
        await server.audit(user, "delete_logo", "settings", "company")
        return {"ok": True}
