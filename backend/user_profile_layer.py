"""Profil Saya (self-service) + Ganti Password, memakai auth/user system existing.

- GET  /api/profile            : data profil user yang sedang login.
- PUT  /api/profile            : ubah Nama / Email / Nomor Telepon (field lain DITOLAK — role, permission,
                                 division scope, tenant, status aktif, user ID hanya lewat User Management).
- POST /api/auth/change-password: password saat ini wajib benar, policy existing (8-128 karakter), konfirmasi sama,
                                 hash bcrypt existing. token_version dirotasi: seluruh token lama invalid, sesi
                                 saat ini menerima token baru (tidak logout).
Audit: update_profile (field berubah) dan change_password (tanpa nilai/hash password).
"""
from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request, Response

import auth as A

EDITABLE = ("name", "email", "phone")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s.]{6,30}$")
PW_MIN, PW_MAX = 8, 128
FIELD_LABEL = {"role": "Role", "permissions": "Permission", "permission_overrides": "Permission", "effective_permissions": "Permission",
               "divisions": "Division Scope", "division_override": "Division Scope", "division_scope": "Division Scope",
               "scope": "Division Scope", "warehouses": "Gudang", "tenant_id": "Tenant", "company_id": "Tenant",
               "is_active": "Status Aktif", "id": "User ID", "token_version": "Sesi", "password_hash": "Password",
               "password": "Password"}


def _public(u: dict) -> dict:
    return {"id": u.get("id"), "name": u.get("name") or "", "email": u.get("email") or "", "phone": u.get("phone") or "",
            "role": u.get("role"), "tenant_id": u.get("tenant_id"), "is_active": u.get("is_active", True)}


def install(server):
    app = server.app
    db = lambda: server.db  # noqa: E731
    cu = server.current_user

    @app.get("/api/profile", tags=["profile"])
    async def get_profile(user=Depends(cu)):
        u = await db().users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(404, "User tidak ditemukan")
        return _public(u)

    @app.put("/api/profile", tags=["profile"])
    async def update_profile(body: dict, user=Depends(cu)):
        body = body if isinstance(body, dict) else {}
        blocked = [k for k in body if k not in EDITABLE]
        if blocked:
            labels = sorted({FIELD_LABEL.get(k, k) for k in blocked})
            raise HTTPException(400, f"Field berikut tidak dapat diubah melalui Profil Saya: {', '.join(labels)}. Hubungi Admin melalui User Management.")
        cur = await db().users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
        if not cur:
            raise HTTPException(404, "User tidak ditemukan")
        patch = {}
        if "name" in body:
            name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()
            if len(name) < 2:
                raise HTTPException(400, "Nama minimal 2 karakter.")
            if len(name) > 120:
                raise HTTPException(400, "Nama maksimal 120 karakter.")
            patch["name"] = name
        if "email" in body:
            email = str(body.get("email") or "").strip().lower()
            if not EMAIL_RE.match(email) or len(email) > 190:
                raise HTTPException(400, "Format email tidak valid.")
            if email != str(cur.get("email") or "").lower():
                taken = await getattr(server, "raw_db", server.db).users.find_one({"email": email, "id": {"$ne": cur["id"]}}, {"_id": 0, "id": 1})
                if taken:
                    raise HTTPException(409, "Email sudah digunakan oleh akun lain.")
                pending = await db().approval_tasks.find_one({"approver_email": str(cur.get("email") or "").lower(),
                                                              "status": {"$in": ["Pending", "Waiting"]}}, {"_id": 0, "id": 1})
                if pending:
                    raise HTTPException(409, "Email tidak dapat diubah karena masih ada tugas approval yang menunggu atas email ini. Hubungi Admin.")
            patch["email"] = email
        if "phone" in body:
            phone = str(body.get("phone") or "").strip()
            if phone and not PHONE_RE.match(phone):
                raise HTTPException(400, "Format nomor telepon tidak valid.")
            patch["phone"] = phone
        changed = {k: v for k, v in patch.items() if (cur.get(k) or "") != v}
        if changed:
            await db().users.update_one({"id": cur["id"]}, {"$set": {**changed, "updated_at": server.now_iso()}})
            await server.audit(user, "update_profile", "user", cur["id"], cur.get("email"),
                               before={k: cur.get(k) or "" for k in changed}, after=changed)
        u = await db().users.find_one({"id": cur["id"]}, {"_id": 0, "password_hash": 0})
        return {**_public(u), "changed_fields": sorted(changed)}

    @app.post("/api/auth/change-password", tags=["profile"])
    async def change_password(body: dict, request: Request, response: Response, user=Depends(cu)):
        body = body if isinstance(body, dict) else {}
        current = str(body.get("current_password") or "")
        new = str(body.get("new_password") or "")
        confirm = str(body.get("confirm_password") or "")
        if not current:
            raise HTTPException(400, "Password saat ini wajib diisi.")
        u = await db().users.find_one({"id": user["id"]}, {"_id": 0})
        if not u or not A.verify_password(current, u.get("password_hash", "")):
            raise HTTPException(400, "Password saat ini salah.")
        if len(new) < PW_MIN:
            raise HTTPException(400, f"Password baru minimal {PW_MIN} karakter.")
        if len(new) > PW_MAX:
            raise HTTPException(400, f"Password baru maksimal {PW_MAX} karakter.")
        if new != confirm:
            raise HTTPException(400, "Konfirmasi password baru tidak sama.")
        if A.verify_password(new, u.get("password_hash", "")):
            raise HTTPException(400, "Password baru harus berbeda dari password saat ini.")
        # Rotasi sesi: hash baru + token_version +1 (semua token lama invalid), sesi ini menerima token baru.
        flt = {"id": u["id"]}
        if "token_version" in u:
            flt["token_version"] = u.get("token_version")
        upd = await db().users.find_one_and_update(
            flt,
            {"$set": {"password_hash": A.hash_password(new), "password_changed_at": server.now_iso()}, "$inc": {"token_version": 1}},
            return_document=True)
        if not upd:
            raise HTTPException(409, A.SESSION_REPLACED_MSG)
        tv = int(upd.get("token_version") or 0)
        access = A.create_access_token(u["id"], u.get("email"), tv)
        A.set_auth_cookies(response, access, A.create_refresh_token(u["id"], tv), request)
        await server.audit(user, "change_password", "user", u["id"], u.get("email"))
        return {"ok": True, "token": access, "message": "Password berhasil diubah."}
