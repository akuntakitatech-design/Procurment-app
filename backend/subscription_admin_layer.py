"""Platform controls for tenant trial, paid subscription dates, and post-expiry access.

Trial expiry and paid subscription expiry stay separate. Platform Admin can also set
how many days a tenant remains in limited/read-only access after either deadline.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import saas_platform_layer as SaaS


def _normalize_iso(value: str | None):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal tidak valid")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _as_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class SubscriptionDatesPatch(BaseModel):
    trial_ends_at: str | None = None
    ends_at: str | None = None
    post_expiry_access_days: int | None = Field(default=None, ge=0, le=365)


def install(server):
    app = server.app

    @app.patch("/api/platform/tenants/{tenant_id}/subscription-dates", tags=["platform"])
    async def update_subscription_dates(
        tenant_id: str,
        body: SubscriptionDatesPatch,
        user=Depends(server.current_user),
    ):
        SaaS._require_platform_admin(user)
        db = SaaS._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")

        trial_ends_at = _normalize_iso(body.trial_ends_at)
        ends_at = _normalize_iso(body.ends_at)
        update = {
            "updated_at": SaaS.now_iso(),
            "subscription.trial_ends_at": trial_ends_at,
            "subscription.ends_at": ends_at,
        }
        if body.post_expiry_access_days is not None:
            update["subscription.post_expiry_access_days"] = int(body.post_expiry_access_days)

        # If Platform Admin moves an expired/grace deadline back into the future, revive the
        # lifecycle automatically. This makes manual date extension work without requiring a
        # second status change in the UI. A suspended tenant is never reactivated implicitly.
        current_status = str((tenant.get("subscription") or {}).get("status") or "active").lower()
        tenant_status = str(tenant.get("status") or "active").lower()
        now = datetime.now(timezone.utc)
        auto_status = None
        if tenant_status != "suspended" and current_status in {"grace", "expired"}:
            paid_end = _as_dt(ends_at)
            trial_end = _as_dt(trial_ends_at)
            if paid_end and paid_end > now:
                auto_status = "active"
            elif trial_end and trial_end > now:
                auto_status = "trial"
            if auto_status:
                update["subscription.status"] = auto_status

        # Changing dates or the post-expiry access window starts a fresh lifecycle evaluation.
        # Old transition/reminder metadata must not carry into the new period.
        unset = {
            "subscription.grace_ends_at": "",
            "subscription.expired_at": "",
            "subscription.reminders_sent": "",
            "subscription.last_reminder_at": "",
            "subscription.last_reminder_type": "",
            "subscription.status_changed_at": "",
        }

        await db.tenants.update_one(
            {"id": tenant_id},
            {"$set": update, "$unset": unset},
        )
        after = {
            "trial_ends_at": trial_ends_at,
            "ends_at": ends_at,
        }
        if body.post_expiry_access_days is not None:
            after["post_expiry_access_days"] = int(body.post_expiry_access_days)
        if auto_status:
            after["subscription_status"] = auto_status
            after["auto_reactivated"] = True
        await SaaS._platform_audit(
            server,
            user,
            "subscription.dates_updated",
            tenant_id,
            after,
        )
        return {
            "ok": True,
            "tenant_id": tenant_id,
            **after,
        }
