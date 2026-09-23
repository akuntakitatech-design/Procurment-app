"""Subscription expiry lifecycle, reminders, and platform visibility.

Trial and paid subscriptions use the same post-expiry policy:
- while the deadline is still valid, access is full
- after the deadline, access is read-only/limited for a configurable number of days
- after that window, the workspace is locked
- suspended workspaces are locked immediately
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException

import saas_platform_layer as SaaS
import tenant_foundation_layer as T


DEFAULT_POST_EXPIRY_ACCESS_DAYS = max(
    0, int(os.environ.get("SUBSCRIPTION_POST_EXPIRY_ACCESS_DAYS", "3") or 3)
)
LOOP_SECONDS = max(300, int(os.environ.get("SUBSCRIPTION_LIFECYCLE_INTERVAL_SECONDS", "3600") or 3600))
TRIAL_THRESHOLDS = (7, 3, 1)
ACTIVE_THRESHOLDS = (30, 14, 7, 3, 1)
LIMITED_THRESHOLDS = (3, 2, 1)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None):
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _remaining_days(deadline: datetime | None, now: datetime):
    if not deadline:
        return None
    seconds = (deadline - now).total_seconds()
    if seconds <= 0:
        return 0
    return max(1, math.ceil(seconds / 86400))


def _post_expiry_access_days(tenant: dict) -> int:
    sub = (tenant or {}).get("subscription") or {}
    value = sub.get("post_expiry_access_days", DEFAULT_POST_EXPIRY_ACCESS_DAYS)
    try:
        return max(0, min(365, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_POST_EXPIRY_ACCESS_DAYS


def _reminder_threshold(days_remaining: int | None, thresholds):
    if days_remaining is None or days_remaining <= 0:
        return None
    eligible = [x for x in thresholds if days_remaining <= x]
    return min(eligible) if eligible else None


def _message_for(status: str, phase: str, days_remaining: int | None, deadline: datetime | None):
    date_text = deadline.astimezone(timezone.utc).strftime("%d-%m-%Y") if deadline else None
    if phase == "locked" and status == "suspended":
        return "Workspace ditangguhkan oleh administrator platform. Hubungi administrator untuk informasi lebih lanjut."
    if phase == "locked":
        return "Masa akses setelah jatuh tempo telah berakhir. Workspace terkunci sampai langganan diperpanjang."
    if phase == "limited_access":
        if days_remaining is not None:
            return (
                f"Masa aktif telah berakhir. Akses terbatas tersisa {days_remaining} hari "
                f"hingga {date_text}; transaksi baru dan perubahan data dinonaktifkan."
            )
        return "Masa aktif telah berakhir. Workspace berada dalam akses terbatas."
    if status == "trial":
        if days_remaining is not None:
            return f"Masa trial berakhir dalam {days_remaining} hari ({date_text})."
        return "Workspace masih dalam masa trial."
    if status == "active" and days_remaining is not None:
        return f"Langganan berakhir dalam {days_remaining} hari ({date_text})."
    return "Langganan aktif tanpa tanggal berakhir."


def _severity(status: str, phase: str, days_remaining: int | None):
    if phase == "locked":
        return "danger"
    if phase == "limited_access":
        return "warning"
    if days_remaining is not None and days_remaining <= 3:
        return "danger"
    if days_remaining is not None and days_remaining <= 7:
        return "warning"
    if days_remaining is not None and days_remaining <= 30:
        return "info"
    return "ok"


def _evaluate(tenant: dict, now: datetime):
    sub = tenant.get("subscription") or {}
    current_status = str(sub.get("status") or "active").lower()
    trial_end = _parse_dt(sub.get("trial_ends_at"))
    ends_at = _parse_dt(sub.get("ends_at"))
    access_end = _parse_dt(sub.get("grace_ends_at"))
    access_days = _post_expiry_access_days(tenant)

    # Tenant-level suspension and subscription-level suspension both lock immediately.
    if tenant.get("status") == "suspended" or current_status == "suspended":
        status = "suspended"
        phase = "locked"
        deadline = ends_at or trial_end
        access_end = None
    elif current_status == "trial":
        if trial_end and now >= trial_end:
            access_end = access_end or (trial_end + timedelta(days=access_days))
            if access_days > 0 and now < access_end:
                status, phase, deadline = "grace", "limited_access", access_end
            else:
                status, phase, deadline = "expired", "locked", access_end or trial_end
        else:
            access_end = None
            status, phase, deadline = "trial", "full", trial_end
    elif current_status == "active":
        if ends_at and now >= ends_at:
            access_end = access_end or (ends_at + timedelta(days=access_days))
            if access_days > 0 and now < access_end:
                status, phase, deadline = "grace", "limited_access", access_end
            else:
                status, phase, deadline = "expired", "locked", access_end or ends_at
        else:
            access_end = None
            status, phase, deadline = "active", "full", ends_at
    elif current_status == "grace":
        source_deadline = ends_at or trial_end
        access_end = access_end or (
            source_deadline + timedelta(days=access_days) if source_deadline else None
        )
        if not access_end or access_days == 0 or now >= access_end:
            status, phase, deadline = "expired", "locked", access_end or source_deadline
        else:
            status, phase, deadline = "grace", "limited_access", access_end
    elif current_status == "expired":
        status, phase, deadline = "expired", "locked", access_end or ends_at or trial_end
    else:
        status, phase, deadline = current_status, "full", ends_at or trial_end

    days_remaining = _remaining_days(deadline, now)
    show_banner = phase in {"limited_access", "locked"}
    if status == "trial" and days_remaining is not None and days_remaining <= 7:
        show_banner = True
    if status == "active" and days_remaining is not None and days_remaining <= 30:
        show_banner = True

    access_mode = "full"
    if phase == "limited_access":
        access_mode = "limited"
    elif phase == "locked":
        access_mode = "locked"

    return {
        "tenant_id": tenant.get("id"),
        "tenant_code": tenant.get("tenant_code"),
        "tenant_name": tenant.get("name"),
        "status": status,
        "phase": phase,
        "access_mode": access_mode,
        "trial_ends_at": _iso(trial_end),
        "ends_at": _iso(ends_at),
        # Keep the field name for backward compatibility; semantically this is the end of
        # the post-expiry limited-access window.
        "grace_ends_at": _iso(access_end),
        "post_expiry_access_ends_at": _iso(access_end),
        "deadline": _iso(deadline),
        "days_remaining": days_remaining,
        "show_banner": show_banner,
        "severity": _severity(status, phase, days_remaining),
        "message": _message_for(status, phase, days_remaining, deadline),
        "post_expiry_access_days": access_days,
        "grace_days": access_days,
        "last_reminder_at": sub.get("last_reminder_at"),
        "last_reminder_type": sub.get("last_reminder_type"),
    }


def _reminder_key(snapshot: dict):
    status = snapshot.get("status")
    phase = snapshot.get("phase")
    days = snapshot.get("days_remaining")
    if status == "trial":
        threshold = _reminder_threshold(days, TRIAL_THRESHOLDS)
    elif status == "active":
        threshold = _reminder_threshold(days, ACTIVE_THRESHOLDS)
    elif phase == "limited_access":
        threshold = _reminder_threshold(days, LIMITED_THRESHOLDS)
    else:
        threshold = None
    if threshold is None:
        return None
    deadline = _parse_dt(snapshot.get("deadline"))
    cycle = deadline.strftime("%Y%m%d") if deadline else "nodate"
    key_status = "limited" if phase == "limited_access" else status
    return f"{key_status}_{cycle}_h{threshold}"


async def _audit_transition(db, tenant: dict, before_status: str, after_status: str, snapshot: dict):
    await db.platform_audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "action": "subscription.status_changed",
        "tenant_id": tenant.get("id"),
        "user_id": None,
        "user_email": "system:subscription-lifecycle",
        "after": {
            "from": before_status,
            "to": after_status,
            "phase": snapshot.get("phase"),
            "access_mode": snapshot.get("access_mode"),
            "deadline": snapshot.get("deadline"),
            "days_remaining": snapshot.get("days_remaining"),
        },
        "at": _iso(_now()),
    })


async def _create_reminder(db, tenant: dict, snapshot: dict, key: str):
    sub = tenant.get("subscription") or {}
    sent = sub.get("reminders_sent") or {}
    if sent.get(key):
        return
    now = _now()
    title_map = {
        "trial": "Masa Trial Akan Berakhir",
        "active": "Langganan Akan Berakhir",
        "grace": "Akses Terbatas Setelah Jatuh Tempo",
    }
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant.get("id"),
        "title": title_map.get(snapshot.get("status"), "Informasi Langganan"),
        "message": snapshot.get("message"),
        "category": "subscription",
        "division": None,
        "read": False,
        "at": _iso(now),
    })
    await db.tenants.update_one(
        {"id": tenant.get("id")},
        {"$set": {
            f"subscription.reminders_sent.{key}": _iso(now),
            "subscription.last_reminder_at": _iso(now),
            "subscription.last_reminder_type": key,
            "updated_at": _iso(now),
        }},
    )


async def reconcile_tenant(server, tenant_id: str, create_reminder: bool = True):
    db = SaaS._global_db(server)
    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

    now = _now()
    before_status = str((tenant.get("subscription") or {}).get("status") or "active").lower()
    snapshot = _evaluate(tenant, now)
    desired = snapshot["status"]
    updates = {"subscription.lifecycle_checked_at": _iso(now)}
    unsets = {}

    if desired != before_status:
        updates["subscription.status"] = desired
        updates["subscription.status_changed_at"] = _iso(now)
        if desired == "expired":
            updates["subscription.expired_at"] = (tenant.get("subscription") or {}).get("expired_at") or _iso(now)

    if desired in {"trial", "active"}:
        unsets["subscription.expired_at"] = ""

    if snapshot.get("grace_ends_at"):
        updates["subscription.grace_ends_at"] = snapshot["grace_ends_at"]
    elif desired in {"trial", "active", "suspended"}:
        unsets["subscription.grace_ends_at"] = ""

    update_doc = {"$set": updates}
    if unsets:
        update_doc["$unset"] = unsets
    await db.tenants.update_one({"id": tenant_id}, update_doc)

    if desired != before_status:
        await _audit_transition(db, tenant, before_status, desired, snapshot)

    tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or tenant
    snapshot = _evaluate(tenant, now)
    if create_reminder:
        key = _reminder_key(snapshot)
        if key:
            await _create_reminder(db, tenant, snapshot, key)
            tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or tenant
            snapshot = _evaluate(tenant, now)
    return snapshot


async def reconcile_all(server, create_reminders: bool = True):
    db = SaaS._global_db(server)
    tenant_ids = [x.get("id") for x in await db.tenants.find({}, {"id": 1, "_id": 0}).to_list(100000)]
    snapshots = []
    for tenant_id in tenant_ids:
        if not tenant_id:
            continue
        try:
            snapshots.append(await reconcile_tenant(server, tenant_id, create_reminders))
        except Exception as exc:
            server.logger.warning("subscription lifecycle reconcile failed for %s: %s", tenant_id, exc)
    return snapshots


async def _loop(server):
    while True:
        await asyncio.sleep(LOOP_SECONDS)
        await reconcile_all(server, create_reminders=True)


def install(server):
    app = server.app

    @app.on_event("startup")
    async def subscription_lifecycle_startup():
        await reconcile_all(server, create_reminders=True)
        app.state.subscription_lifecycle_task = asyncio.create_task(_loop(server))
        server.logger.info(
            "Subscription lifecycle ready; default post-expiry access=%s days, interval=%ss",
            DEFAULT_POST_EXPIRY_ACCESS_DAYS,
            LOOP_SECONDS,
        )

    @app.on_event("shutdown")
    async def subscription_lifecycle_shutdown():
        task = getattr(app.state, "subscription_lifecycle_task", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @app.get("/api/subscription/status", tags=["subscription"])
    async def subscription_status(user=Depends(server.current_user)):
        tenant_id = T.tenant_id_of(user)
        return await reconcile_tenant(server, tenant_id, create_reminder=True)

    @app.get("/api/platform/subscriptions/overview", tags=["platform"])
    async def platform_subscription_overview(user=Depends(server.current_user)):
        SaaS._require_platform_admin(user)
        snapshots = await reconcile_all(server, create_reminders=True)
        attention = [x for x in snapshots if x.get("show_banner")]
        attention.sort(key=lambda x: (
            0 if x.get("access_mode") == "locked" else 1 if x.get("access_mode") == "limited" else 2,
            x.get("days_remaining") if x.get("days_remaining") is not None else 999999,
            x.get("tenant_code") or "",
        ))
        return {
            "counts": {
                "active": sum(1 for x in snapshots if x.get("status") == "active"),
                "trial": sum(1 for x in snapshots if x.get("status") == "trial"),
                "limited": sum(1 for x in snapshots if x.get("access_mode") == "limited"),
                "grace": sum(1 for x in snapshots if x.get("access_mode") == "limited"),
                "expired": sum(1 for x in snapshots if x.get("status") == "expired"),
                "locked": sum(1 for x in snapshots if x.get("access_mode") == "locked"),
                "attention": len(attention),
                "due_7_days": sum(
                    1 for x in snapshots
                    if x.get("days_remaining") is not None
                    and x.get("days_remaining") <= 7
                    and x.get("access_mode") == "full"
                ),
            },
            "items": snapshots,
            "attention": attention[:500],
        }
