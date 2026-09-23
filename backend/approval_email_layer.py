"""Email-based sequential approval configurable per transaction module.

Approval is based on ordered levels tied to concrete active user emails. The
configuration is module-specific so MRO, RO and PO may use different approvers,
or bypass approval entirely. Stock-posting documents are intentionally excluded
from this layer until they have a pre-posting draft workflow.
"""
from fastapi import Depends, HTTPException, Query


SUPPORTED_MODULES = {
    "mro": {"label": "MRO", "collection": "mro"},
    "ro": {"label": "RO", "collection": "ro"},
    "po": {"label": "PO", "collection": "po"},
}


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _module_config(server, module):
    cfg = await server.db.settings.find_one({"id": "approval_modules"}, {"_id": 0}) or {}
    modules = cfg.get("modules") or {}
    row = modules.get(module)
    if row is not None:
        return {"enabled": bool(row.get("enabled", False)), "levels": row.get("levels") or []}

    # Backward compatibility: previous version stored one PO-only level list.
    if module == "po":
        legacy = await server.db.settings.find_one({"id": "approval_levels"}, {"_id": 0}) or {}
        levels = legacy.get("levels") or []
        if levels:
            return {"enabled": True, "levels": levels}
    return {"enabled": False, "levels": []}


async def _levels(server, module):
    cfg = await _module_config(server, module)
    out = []
    for idx, row in enumerate(cfg.get("levels") or []):
        email = str(row.get("email") or "").strip().lower()
        if not email and row.get("user_id"):
            u = await server.db.users.find_one({"id": row.get("user_id")}, {"_id": 0, "password_hash": 0})
            email = str((u or {}).get("email") or "").strip().lower()
        if not email:
            continue
        user = await server.db.users.find_one(
            {"email": email, "is_active": {"$ne": False}},
            {"_id": 0, "password_hash": 0},
        )
        if not user:
            continue
        out.append({
            "level": int(row.get("level") or idx + 1),
            "user_id": user.get("id"),
            "email": email,
            "name": user.get("name") or email,
        })
    return sorted(out, key=lambda x: x["level"])


async def _get_doc(server, module, did):
    meta = SUPPORTED_MODULES[module]
    return await getattr(server.db, meta["collection"]).find_one({"id": did}, {"_id": 0})


async def _refresh(app, module, did, user):
    route = _find_route(app, f"/api/{module}/{{did}}", "GET")
    if not route:
        return {"id": did}
    result = await route.endpoint(did, user)
    if isinstance(result, dict) and result.get("approval_status") in ("Waiting Approval", "Rejected"):
        result["status"] = result.get("approval_status")
    return result


async def _clear_tasks(server, module, did):
    await server.db.approval_tasks.delete_many({"module": module, "document_id": did})
    if module == "po":
        await server.db.po_approvals.delete_many({"po_id": did})


async def _create_tasks(server, module, doc, levels):
    await _clear_tasks(server, module, doc["id"])
    for i, lv in enumerate(levels):
        task = {
            "id": server.gid(),
            "module": module,
            "document_type": SUPPORTED_MODULES[module]["label"],
            "document_id": doc["id"],
            "document_no": doc.get("no"),
            "seq": i + 1,
            "level": lv["level"],
            "approver_user_id": lv["user_id"],
            "approver_email": lv["email"],
            "approver_name": lv["name"],
            "status": "Pending" if i == 0 else "Waiting",
            "acted_by": None,
            "acted_by_email": None,
            "acted_at": None,
            "note": None,
        }
        await server.db.approval_tasks.insert_one(task.copy())
        if module == "po":
            po_task = {**task, "po_id": doc["id"], "role": None}
            po_task.pop("module", None)
            po_task.pop("document_type", None)
            po_task.pop("document_id", None)
            po_task.pop("document_no", None)
            await server.db.po_approvals.insert_one(po_task)


async def _set_waiting(server, module, did):
    if module in ("mro", "ro"):
        await getattr(server.db, module).update_one(
            {"id": did},
            {"$set": {"submitted": False, "approval_status": "Waiting Approval", "approval_mode": "email-level"}},
        )
    else:
        await server.db.po.update_one(
            {"id": did},
            {"$set": {"status": "Waiting Approval", "approval_status": "Waiting Approval", "approval_mode": "email-level"}},
        )


async def _set_approved(server, module, did):
    if module in ("mro", "ro"):
        await getattr(server.db, module).update_one(
            {"id": did},
            {"$set": {"submitted": True, "approval_status": "Approved", "approval_mode": "email-level"}},
        )
    else:
        await server.db.po.update_one(
            {"id": did},
            {"$set": {"status": "Approved", "approval_status": "Approved", "approval_mode": "email-level"}},
        )


async def _set_rejected(server, module, did):
    if module in ("mro", "ro"):
        await getattr(server.db, module).update_one(
            {"id": did},
            {"$set": {"submitted": False, "approval_status": "Rejected", "approval_mode": "email-level"}},
        )
    else:
        await server.db.po.update_one(
            {"id": did},
            {"$set": {"status": "Rejected", "approval_status": "Rejected", "approval_mode": "email-level"}},
        )


async def _sync_po_task(server, task_id, patch):
    await server.db.po_approvals.update_one({"id": task_id}, {"$set": patch})


def install(server):
    app = server.app

    async def ensure_assignee(step, user):
        assigned = str(step.get("approver_email") or "").lower()
        actual = str(user.get("email") or "").lower()
        if assigned != actual:
            raise HTTPException(403, f"Approval ini ditugaskan ke {assigned or 'user lain'}")

    async def approve_current(module, did, note, user):
        if module not in SUPPORTED_MODULES:
            raise HTTPException(400, "Modul approval tidak didukung")
        doc = await _get_doc(server, module, did)
        if not doc:
            raise HTTPException(404, f"{SUPPORTED_MODULES[module]['label']} tidak ditemukan")
        step = await server.db.approval_tasks.find_one(
            {"module": module, "document_id": did, "status": "Pending"},
            {"_id": 0}, sort=[("seq", 1)],
        )
        if not step:
            raise HTTPException(400, "Tidak ada tahap approval yang menunggu")
        await ensure_assignee(step, user)
        patch = {
            "status": "Approved",
            "acted_by": user.get("name") or user.get("email"),
            "acted_by_email": user.get("email"),
            "acted_at": server.now_iso(),
            "note": note,
        }
        await server.db.approval_tasks.update_one({"id": step["id"]}, {"$set": patch})
        if module == "po":
            await _sync_po_task(server, step["id"], patch)

        nxt = await server.db.approval_tasks.find_one(
            {"module": module, "document_id": did, "status": "Waiting"},
            {"_id": 0}, sort=[("seq", 1)],
        )
        if nxt:
            await server.db.approval_tasks.update_one({"id": nxt["id"]}, {"$set": {"status": "Pending"}})
            if module == "po":
                await _sync_po_task(server, nxt["id"], {"status": "Pending"})
            await _set_waiting(server, module, did)
            await server.notify(
                f"Approval {SUPPORTED_MODULES[module]['label']} berikutnya",
                f"{doc.get('no')} menunggu {nxt.get('approver_name') or nxt.get('approver_email')}",
                "approval", doc.get("division_id"),
            )
        else:
            await _set_approved(server, module, did)
            await server.notify(
                f"{SUPPORTED_MODULES[module]['label']} disetujui",
                f"{doc.get('no')} approved",
                "approval", doc.get("division_id"),
            )
        await server.audit(user, "approve", module, did, doc.get("no"))
        return await _refresh(app, module, did, user)

    async def reject_current(module, did, reason, user):
        if module not in SUPPORTED_MODULES:
            raise HTTPException(400, "Modul approval tidak didukung")
        doc = await _get_doc(server, module, did)
        if not doc:
            raise HTTPException(404, f"{SUPPORTED_MODULES[module]['label']} tidak ditemukan")
        step = await server.db.approval_tasks.find_one(
            {"module": module, "document_id": did, "status": "Pending"},
            {"_id": 0}, sort=[("seq", 1)],
        )
        if not step:
            raise HTTPException(400, "Tidak ada tahap approval yang menunggu")
        await ensure_assignee(step, user)
        patch = {
            "status": "Rejected",
            "acted_by": user.get("name") or user.get("email"),
            "acted_by_email": user.get("email"),
            "acted_at": server.now_iso(),
            "note": reason,
        }
        await server.db.approval_tasks.update_one({"id": step["id"]}, {"$set": patch})
        if module == "po":
            await _sync_po_task(server, step["id"], patch)
        await _set_rejected(server, module, did)
        await server.audit(user, "reject", module, did, doc.get("no"), reason=reason)
        await server.notify(
            f"{SUPPORTED_MODULES[module]['label']} ditolak",
            f"{doc.get('no')} rejected",
            "approval", doc.get("division_id"),
        )
        return await _refresh(app, module, did, user)

    # Replace submit workflow for each approval-capable module.
    for module in SUPPORTED_MODULES:
        path = f"/api/{module}/{{did}}/submit"
        route = _find_route(app, path, "POST")
        if not route:
            continue
        original = route.endpoint
        app.router.routes.remove(route)

        def make_submit(kind, original_endpoint):
            async def submit_module(did: str, user=Depends(server.current_user)):
                server.require(user, "submit")
                doc = await _get_doc(server, kind, did)
                if not doc:
                    raise HTTPException(404, f"{SUPPORTED_MODULES[kind]['label']} tidak ditemukan")
                cfg = await _module_config(server, kind)
                if not cfg.get("enabled"):
                    await _clear_tasks(server, kind, did)
                    if kind == "po":
                        await server.db.po.update_one(
                            {"id": did},
                            {"$set": {"status": "Approved", "approval_status": "Not Required", "approval_mode": "none"}},
                        )
                        await server.audit(user, "submit", "po", did, doc.get("no"))
                        return await _refresh(app, kind, did, user)
                    result = await original_endpoint(did, user)
                    await getattr(server.db, kind).update_one(
                        {"id": did},
                        {"$set": {"approval_status": "Not Required", "approval_mode": "none"}},
                    )
                    return result

                levels = await _levels(server, kind)
                if not levels:
                    raise HTTPException(400, f"Approval {SUPPORTED_MODULES[kind]['label']} aktif tetapi belum memiliki approver")
                await _create_tasks(server, kind, doc, levels)
                await _set_waiting(server, kind, did)
                await server.audit(user, "submit", kind, did, doc.get("no"))
                await server.notify(
                    f"{SUPPORTED_MODULES[kind]['label']} menunggu approval",
                    f"{doc.get('no')} menunggu {levels[0]['name']}",
                    "approval", doc.get("division_id"),
                )
                return await _refresh(app, kind, did, user)
            return submit_module

        app.add_api_route(path, make_submit(module, original), methods=["POST"], tags=["approval"])

    # Keep detail/list status readable for request documents waiting approval.
    for module in ("mro", "ro"):
        for path in (f"/api/{module}", f"/api/{module}/{{did}}"):
            route = _find_route(app, path, "GET")
            if not route:
                continue
            original = route.endpoint
            app.router.routes.remove(route)

            if "{did}" in path:
                def make_detail(kind, original_endpoint):
                    async def detail(did: str, user=Depends(server.current_user)):
                        result = await original_endpoint(did, user)
                        if isinstance(result, dict) and result.get("approval_status") in ("Waiting Approval", "Rejected"):
                            result["status"] = result["approval_status"]
                        return result
                    return detail
                app.add_api_route(path, make_detail(module, original), methods=["GET"], tags=["approval"])
            else:
                def make_list(kind, original_endpoint):
                    async def listing(user=Depends(server.current_user)):
                        rows = await original_endpoint(user)
                        for row in rows or []:
                            if row.get("approval_status") in ("Waiting Approval", "Rejected"):
                                row["status"] = row["approval_status"]
                        return rows
                    return listing
                app.add_api_route(path, make_list(module, original), methods=["GET"], tags=["approval"])

    @app.get("/api/approvals/inbox", tags=["approval"])
    async def approval_inbox(scope: str = Query("mine"), user=Depends(server.current_user)):
        query = {}
        if user.get("role") != "admin" or scope != "all":
            query["approver_email"] = str(user.get("email") or "").lower()
        steps = await server.db.approval_tasks.find(query, {"_id": 0}).sort([("status", 1), ("seq", 1)]).to_list(5000)
        suppliers = {s["id"]: s for s in await server.db.suppliers.find({}, {"_id": 0}).to_list(3000)}
        out = []
        for step in steps:
            module = step.get("module")
            if module not in SUPPORTED_MODULES:
                continue
            doc = await _get_doc(server, module, step.get("document_id"))
            if not doc:
                continue
            context_name = None
            grand_total = None
            if module == "po":
                context_name = suppliers.get(doc.get("supplier_id"), {}).get("name")
                grand_total = doc.get("grand_total")
            else:
                context_name = doc.get("requester") or doc.get("department")
            out.append({
                **step,
                "document_type": SUPPORTED_MODULES[module]["label"],
                "document_id": doc.get("id"),
                "document_no": doc.get("no"),
                "date": doc.get("date"),
                "context_name": context_name,
                "supplier_name": context_name if module == "po" else None,
                "grand_total": grand_total,
                "document_status": doc.get("approval_status") or doc.get("status"),
            })
        return out

    @app.post("/api/approvals/{approval_id}/approve", tags=["approval"])
    async def approval_inbox_approve(approval_id: str, body: dict = None, user=Depends(server.current_user)):
        step = await server.db.approval_tasks.find_one({"id": approval_id}, {"_id": 0})
        if not step:
            raise HTTPException(404, "Approval tidak ditemukan")
        if step.get("status") != "Pending":
            raise HTTPException(400, "Approval ini tidak lagi menunggu tindakan")
        return await approve_current(step["module"], step["document_id"], (body or {}).get("note"), user)

    @app.post("/api/approvals/{approval_id}/reject", tags=["approval"])
    async def approval_inbox_reject(approval_id: str, body: dict = None, user=Depends(server.current_user)):
        step = await server.db.approval_tasks.find_one({"id": approval_id}, {"_id": 0})
        if not step:
            raise HTTPException(404, "Approval tidak ditemukan")
        if step.get("status") != "Pending":
            raise HTTPException(400, "Approval ini tidak lagi menunggu tindakan")
        return await reject_current(step["module"], step["document_id"], (body or {}).get("reason") or "Ditolak", user)
