"""Guard item-warehouse configuration so physical stock remains ledger-controlled.

The legacy POST /api/item-warehouse endpoint is intended for min/max configuration, but
it also accepted current_stock from the caller. That allows stock to bypass transaction
and ledger controls. This wrapper strips current_stock before delegating to the legacy
handler, so callers may still update min/max while stock can only move through ledger
posting transactions.
"""
from fastapi import Depends


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


def install(server):
    app = server.app
    route = _find_route(app, "/api/item-warehouse", "POST")
    if not route:
        return

    original_set = route.endpoint
    app.router.routes.remove(route)

    async def safe_item_warehouse_set(body: dict, user=Depends(server.current_user)):
        safe_body = dict(body or {})
        # Stock is derived from the stock ledger. Never accept a caller-supplied balance.
        safe_body.pop("current_stock", None)
        return await original_set(safe_body, user)

    app.add_api_route(
        "/api/item-warehouse",
        safe_item_warehouse_set,
        methods=["POST"],
        tags=["stock-safety"],
    )
