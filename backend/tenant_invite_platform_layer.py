"""Platform Super Admin read-only visibility for tenant user invitations."""
from fastapi import Depends, HTTPException

import saas_platform_layer as P
import tenant_invite_layer as V


def install(server):
    @server.app.get("/api/platform/tenants/{tenant_id}/invitations", tags=["platform"])
    async def platform_tenant_invitations(tenant_id: str, user=Depends(server.current_user)):
        P._require_platform_admin(user)
        db = P._global_db(server)
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0})
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant tidak ditemukan")
        rows = await db.user_invitations.find(
            {"tenant_id": tenant_id}, {"_id": 0}
        ).sort("created_at", -1).to_list(1000)
        return [V._clean_invite(row) for row in rows]
