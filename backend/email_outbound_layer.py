"""Editable outbound-email configuration stored in application settings.

The application setting takes precedence over legacy SMTP_* environment variables.
SMTP passwords are encrypted at rest using a Fernet key derived from JWT_SECRET and
are never returned to the frontend.
"""
import asyncio
import base64
import hashlib
import os
import smtplib
import ssl
from email.message import EmailMessage

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException

SETTINGS_ID = "email_outbound"
SUPPORTED_PROVIDERS = {"gmail", "smtp"}
SUPPORTED_SECURITY = {"starttls", "ssl", "none"}


def _fernet():
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET belum dikonfigurasi")
    digest = hashlib.sha256(("procureflow-email-outbound:" + secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_password(value):
    text = str(value or "")
    if not text:
        return None
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def _decrypt_password(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(str(value).encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def _env_config():
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    sender = os.environ.get("SMTP_FROM", "").strip() or username
    password = os.environ.get("SMTP_PASSWORD", "")
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
    provider = "gmail" if not host or host.lower() == "smtp.gmail.com" else "smtp"
    return {
        "enabled": bool(host or sender or username),
        "provider": provider,
        "host": host or ("smtp.gmail.com" if provider == "gmail" else ""),
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "username": username,
        "password": password,
        "from_email": sender,
        "from_name": os.environ.get("SMTP_FROM_NAME", "Procurement").strip(),
        "security": "starttls" if use_tls else "none",
        "source": "environment" if (host or sender or username or password) else "default",
    }


def _normalize_public(raw):
    provider = str(raw.get("provider") or "smtp").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        provider = "smtp"
    security = str(raw.get("security") or "starttls").strip().lower()
    if security not in SUPPORTED_SECURITY:
        security = "starttls"
    try:
        port = int(raw.get("port") or (587 if security != "ssl" else 465))
    except (TypeError, ValueError):
        port = 587
    if provider == "gmail":
        return {
            "enabled": bool(raw.get("enabled", True)),
            "provider": "gmail",
            "host": "smtp.gmail.com",
            "port": 587,
            "username": str(raw.get("username") or "").strip(),
            "from_email": str(raw.get("from_email") or raw.get("username") or "").strip(),
            "from_name": str(raw.get("from_name") or "Procurement").strip(),
            "security": "starttls",
        }
    return {
        "enabled": bool(raw.get("enabled", True)),
        "provider": "smtp",
        "host": str(raw.get("host") or "").strip(),
        "port": port,
        "username": str(raw.get("username") or "").strip(),
        "from_email": str(raw.get("from_email") or "").strip(),
        "from_name": str(raw.get("from_name") or "Procurement").strip(),
        "security": security,
    }


def _validate(cfg, password, require_ready=True):
    if cfg["port"] < 1 or cfg["port"] > 65535:
        raise HTTPException(400, "Port SMTP harus antara 1 dan 65535")
    if not cfg.get("enabled") and not require_ready:
        return
    if cfg["provider"] == "gmail":
        if not cfg.get("username") or "@" not in cfg["username"]:
            raise HTTPException(400, "Email akun Gmail wajib diisi")
        if not cfg.get("from_email"):
            cfg["from_email"] = cfg["username"]
        if require_ready and not password:
            raise HTTPException(400, "App Password Gmail belum diisi")
    else:
        if not cfg.get("host"):
            raise HTTPException(400, "SMTP Host wajib diisi")
        if not cfg.get("from_email") or "@" not in cfg["from_email"]:
            raise HTTPException(400, "Email pengirim wajib diisi")
        if require_ready and cfg.get("username") and not password:
            raise HTTPException(400, "Password SMTP belum diisi")


async def _effective_config(server):
    env = _env_config()
    row = await server.db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {}
    if not row:
        public = _normalize_public(env)
        return {**public, "password": env.get("password") or "", "source": env.get("source", "default")}

    public = _normalize_public(row)
    stored_password = _decrypt_password(row.get("password_encrypted"))
    password = stored_password or env.get("password") or ""
    return {
        **public,
        "password": password,
        "source": "application",
        "password_source": "application" if stored_password else ("environment" if env.get("password") else None),
    }


async def public_config(server):
    cfg = await _effective_config(server)
    out = {k: cfg.get(k) for k in ("enabled", "provider", "host", "port", "username", "from_email", "from_name", "security", "source")}
    out["password_set"] = bool(cfg.get("password"))
    out["password_source"] = cfg.get("password_source")
    out["configured"] = bool(cfg.get("enabled") and cfg.get("from_email") and (cfg.get("provider") == "gmail" or cfg.get("host")))
    password_required = cfg.get("provider") == "gmail" or bool(cfg.get("username"))
    out["ready"] = bool(out["configured"] and (out["password_set"] or not password_required))
    row = await server.db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0, "password_encrypted": 0}) or {}
    out["updated_at"] = row.get("updated_at")
    out["updated_by"] = row.get("updated_by")
    out["last_test_at"] = row.get("last_test_at")
    out["last_test_to"] = row.get("last_test_to")
    return out


def _smtp_send(cfg, message, recipients):
    if cfg["security"] == "ssl":
        smtp = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=25, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(cfg["host"], cfg["port"], timeout=25)
    try:
        if cfg["security"] == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if cfg.get("username"):
            smtp.login(cfg["username"], cfg.get("password") or "")
        smtp.send_message(message, to_addrs=recipients)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


async def send_message(server, message: EmailMessage, recipients):
    cfg = await _effective_config(server)
    if not cfg.get("enabled"):
        raise HTTPException(503, "Email outbound sedang dinonaktifkan di System Settings")
    _validate(cfg, cfg.get("password"), require_ready=True)
    if not message.get("From"):
        sender = cfg["from_email"]
        message["From"] = f"{cfg['from_name']} <{sender}>" if cfg.get("from_name") else sender
    recipients = [str(x).strip() for x in (recipients or []) if str(x).strip()]
    if not recipients:
        raise HTTPException(400, "Penerima email belum diisi")
    try:
        await asyncio.to_thread(_smtp_send, cfg, message, recipients)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Gagal mengirim email: {exc}")


def install(server):
    app = server.app

    @app.get("/api/settings/email_outbound", tags=["settings"])
    async def get_email_outbound(user=Depends(server.current_user)):
        server.require(user, "view")
        return await public_config(server)

    @app.put("/api/settings/email_outbound", tags=["settings"])
    async def put_email_outbound(body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        body = body or {}
        current = await _effective_config(server)
        incoming = {
            "enabled": body.get("enabled", current.get("enabled", True)),
            "provider": body.get("provider", current.get("provider", "gmail")),
            "host": body.get("host", current.get("host", "")),
            "port": body.get("port", current.get("port", 587)),
            "username": body.get("username", current.get("username", "")),
            "from_email": body.get("from_email", current.get("from_email", "")),
            "from_name": body.get("from_name", current.get("from_name", "Procurement")),
            "security": body.get("security", current.get("security", "starttls")),
        }
        cfg = _normalize_public(incoming)
        new_password = str(body.get("password") or "")
        credentials_changed = (
            cfg.get("provider") != current.get("provider")
            or cfg.get("username") != current.get("username")
        )
        effective_password = new_password or ("" if credentials_changed else current.get("password") or "")
        _validate(cfg, effective_password, require_ready=bool(cfg.get("enabled")))

        existing = await server.db.settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {}
        update = {
            "id": SETTINGS_ID,
            **cfg,
            "updated_at": server.now_iso(),
            "updated_by": user.get("email"),
        }
        unset = {}
        if new_password:
            update["password_encrypted"] = _encrypt_password(new_password)
        elif existing.get("password_encrypted") and not credentials_changed:
            update["password_encrypted"] = existing["password_encrypted"]
        elif credentials_changed and existing.get("password_encrypted"):
            unset["password_encrypted"] = ""

        before = {k: existing.get(k) for k in ("enabled", "provider", "host", "port", "username", "from_email", "from_name", "security")}
        write = {"$set": update}
        if unset:
            write["$unset"] = unset
        await server.db.settings.update_one({"id": SETTINGS_ID}, write, upsert=True)
        await server.audit(
            user, "edit", "settings", SETTINGS_ID,
            reason="Pengaturan email outbound diperbarui",
            before=before,
            after=cfg,
        )
        return await public_config(server)

    @app.post("/api/settings/email_outbound/test", tags=["settings"])
    async def test_email_outbound(body: dict = None, user=Depends(server.current_user)):
        server.require(user, "edit")
        target = str((body or {}).get("to") or user.get("email") or "").strip()
        if not target or "@" not in target:
            raise HTTPException(400, "Email tujuan tes wajib diisi")
        msg = EmailMessage()
        msg["Subject"] = "Tes Email Outbound - Procurement PT REAL"
        msg["To"] = target
        msg.set_content("Email outbound Procurement PT REAL berhasil terhubung dan dapat digunakan.")
        msg.add_alternative(
            "<div style='font-family:Arial,sans-serif'><h3>Email Outbound Berhasil</h3>"
            "<p>Konfigurasi email Procurement PT REAL berhasil terhubung dan siap digunakan.</p></div>",
            subtype="html",
        )
        await send_message(server, msg, [target])
        now = server.now_iso()
        await server.db.settings.update_one(
            {"id": SETTINGS_ID},
            {"$set": {"last_test_at": now, "last_test_to": target, "last_test_by": user.get("email")}},
            upsert=True,
        )
        await server.audit(user, "test", "settings", SETTINGS_ID, reason=f"Email tes dikirim ke {target}")
        return {"ok": True, "to": target, "sent_at": now}
