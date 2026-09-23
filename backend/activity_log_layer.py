"""System activity log endpoint backed by immutable audit_logs."""
import re
from fastapi import Depends, Query


def _safe_regex(value):
    return {"$regex": re.escape(str(value or "").strip()), "$options": "i"}


def install(server):
    app = server.app

    @app.get("/api/activity-log", tags=["system"])
    async def activity_log(
        q: str = Query(""),
        entity: str = Query(""),
        action: str = Query(""),
        user_email: str = Query(""),
        date_from: str = Query(""),
        date_to: str = Query(""),
        page: int = Query(1, ge=1),
        size: int = Query(50, ge=10, le=200),
        user=Depends(server.current_user),
    ):
        server.require(user, "view")
        query = {}

        # Limited users may only inspect their own history; global roles can inspect all.
        if not server.is_global(user):
            query["user"] = user.get("email")
        elif user_email:
            query["user"] = _safe_regex(user_email)

        if entity:
            query["entity"] = _safe_regex(entity)
        if action:
            query["action"] = _safe_regex(action)

        if date_from or date_to:
            query["at"] = {}
            if date_from:
                query["at"]["$gte"] = f"{date_from[:10]}T00:00:00"
            if date_to:
                query["at"]["$lte"] = f"{date_to[:10]}T23:59:59.999999+00:00"

        if q:
            rx = _safe_regex(q)
            query["$or"] = [
                {"doc_no": rx},
                {"entity": rx},
                {"action": rx},
                {"user": rx},
                {"user_name": rx},
                {"reason": rx},
            ]

        total = await server.db.audit_logs.count_documents(query)
        skip = (page - 1) * size
        rows = await server.db.audit_logs.find(query, {"_id": 0}).sort("at", -1).skip(skip).limit(size).to_list(size)

        # Facets are intentionally compact and based on the audit collection itself.
        entities = await server.db.audit_logs.distinct("entity")
        actions = await server.db.audit_logs.distinct("action")

        return {
            "rows": rows,
            "page": page,
            "size": size,
            "total": total,
            "pages": max(1, (total + size - 1) // size),
            "entities": sorted([x for x in entities if x]),
            "actions": sorted([x for x in actions if x]),
            "scope": "global" if server.is_global(user) else "self",
        }
