"""JWT email/password authentication utilities."""
import os
import uuid
import hashlib
import secrets
import logging
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, token_version: int = 0) -> str:
    payload = {
        "sub": user_id, "email": email, "ver": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60), "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, token_version: int = 0) -> str:
    payload = {
        "sub": user_id, "ver": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(days=7), "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


# COOKIE_SECURE: auto (default) | true | false.
# auto = flag Secure mengikuti protokol request (X-Forwarded-Proto dari Nginx/Traefik).
# SameSite: "none" hanya bila Secure (lintas domain + HTTPS), selain itu "lax".
COOKIE_SECURE_SETTING = os.environ.get("COOKIE_SECURE", "auto").strip().lower()


def is_secure_request(request) -> bool:
    if COOKIE_SECURE_SETTING == "true":
        return True
    if COOKIE_SECURE_SETTING == "false":
        return False
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower() if request is not None else ""
    if proto:
        return proto == "https"
    return bool(request is not None and request.url.scheme == "https")


def cookie_params(request=None) -> dict:
    secure = is_secure_request(request)
    return {"httponly": True, "secure": secure, "samesite": "none" if secure else "lax", "path": "/"}


def set_auth_cookies(response, access_token: str, refresh_token: str, request=None):
    params = cookie_params(request)
    response.set_cookie(key="access_token", value=access_token, max_age=3600, **params)
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=604800, **params)


def clear_auth_cookies(response, request=None):
    params = cookie_params(request)
    response.delete_cookie("access_token", path="/", secure=params["secure"], samesite=params["samesite"], httponly=True)
    response.delete_cookie("refresh_token", path="/", secure=params["secure"], samesite=params["samesite"], httponly=True)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_current_user(request: Request, db) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if payload.get("ver", 0) != user.get("token_version", 0):
            raise HTTPException(status_code=401, detail="Session expired")
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def seed_admin(db):
    """Create the initial admin once; never overwrite an existing user's password.

    ADMIN_PASSWORD is a bootstrap credential only. After the admin account exists,
    password changes made through the application must survive container restarts,
    rebuilds, and deployments.
    """
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        doc = {
            "id": str(uuid.uuid4()), "email": admin_email,
            "password_hash": hash_password(admin_password), "name": "Administrator",
            "role": "admin", "divisions": [], "warehouses": [], "permissions": [],
            "scope": "global", "is_active": True, "token_version": 0,
            "signature_url": None, "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(doc)
        logger.info("Seeded admin user")
    else:
        logger.info("Admin user already exists; preserving current password")
