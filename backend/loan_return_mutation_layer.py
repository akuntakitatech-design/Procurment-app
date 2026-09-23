"""Mutation support for loan-return transactions.

Legacy code stored return headers and stock ledgers but no return-line table. This
layer records return lines for new returns and safely reconstructs legacy lines
when the loan contains a unique line per item.
"""
from fastapi import Depends, HTTPException


def _find_route(app, path, method):
    for route in list(app.router.routes):
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route
    return None


async def _reverse_blockers(server, rid):
    rows = await server.db.stock_ledger.find({"doc_id": rid, "is_reversal": {"$ne": True}, "reversed": {"$ne": True}}, {"_id": 0}).to_list(5000)
    impact = {}
    for row in rows:
        key=(row.get("item_id"),row.get("warehouse_id"))
        impact[key]=impact.get(key,0.0)+float(row.get("qty_out") or 0)-float(row.get("qty_in") or 0)
    blockers=[]
    for (item_id,wh),delta in impact.items():
        if delta>=-1e-9: continue
        current=float(await server.stock_balance(item_id,wh) or 0)
        if current+delta < -1e-9:
            item=await server.db.items.find_one({"id":item_id},{"_id":0}) or {}
            warehouse=await server.db.warehouses.find_one({"id":wh},{"_id":0}) or {}
            blockers.append(f"{item.get('code') or item_id} di {warehouse.get('name') or wh}")
    return blockers


async def _reverse(server, rid, user, reason):
    rows=await server.db.stock_ledger.find({"doc_id":rid,"is_reversal":{"$ne":True},"reversed":{"$ne":True}},{"_id":0}).sort("at",1).to_list(5000)
    for row in rows:
        qty_in=float(row.get("qty_out") or 0)
        qty_out=float(row.get("qty_in") or 0)
        item_id=row.get("item_id"); wh=row.get("warehouse_id")
        bal=float(await server.stock_balance(item_id,wh) or 0)
        running=bal+qty_in-qty_out
        await server.db.stock_ledger.insert_one({
            "id":server.gid(),
            "doc_type":f"Reversal {row.get('doc_type') or 'Loan Return'}",
            "doc_no":row.get("doc_no"),
            "doc_id":rid,
            "item_id":item_id,
            "warehouse_id":wh,
            "qty_in":qty_in,
            "qty_out":qty_out,
            "running_balance":running,
            "project_id":row.get("project_id"),
            "unit_id":row.get("unit_id"),
            "division_id":row.get("division_id"),
            "user":user.get("email"),
            "at":server.now_iso(),
            "is_reversal":True,
            "reversal_of_ledger_id":row.get("id"),
            "reversal_reason":reason,
        })
        await server.db.item_warehouse.update_one(
            {"item_id":item_id,"warehouse_id":wh},
            {"$set":{"item_id":item_id,"warehouse_id":wh,"current_stock":running}},
            upsert=True,
        )
        await server.db.stock_ledger.update_one({"id":row.get("id")},{"$set":{"reversed":True,"reversed_at":server.now_iso(),"reversal_reason":reason}})


async def _legacy_lines(server, ret):
    loan_id=ret.get("loan_id")
    loan_lines=await server.db.loan_lines.find({"loan_id":loan_id},{"_id":0}).to_list(1000)
    by_item={}
    for ll in loan_lines: by_item.setdefault(ll.get("item_id"),[]).append(ll)
    ledgers=await server.db.stock_ledger.find({"doc_id":ret.get("id"),"doc_type":"Loan Return Out","is_reversal":{"$ne":True}},{"_id":0}).to_list(1000)
    out=[]
    for lg in ledgers:
        choices=by_item.get(lg.get("item_id"),[])
        if len(choices)!=1:
            return None
        ll=choices[0]
        out.append({"id":server.gid(),"return_id":ret.get("id"),"loan_id":loan_id,"loan_line_id":ll.get("id"),"item_id":ll.get("item_id"),"qty":float(lg.get("qty_out") or 0)})
    return out


async def _get_lines(server, ret):
    rows=await server.db.loan_return_lines.find({"return_id":ret.get("id")},{"_id":0}).to_list(1000)
    if rows: return rows
    legacy=await _legacy_lines(server,ret)
    if legacy is None: return None
    if legacy:
        await server.db.loan_return_lines.insert_many([dict(x) for x in legacy])
    return legacy or []


async def _decrement_old(server, lines):
    for l in lines:
        await server.db.loan_lines.update_one({"id":l.get("loan_line_id")},{"$inc":{"returned":-float(l.get("qty") or 0)}})
        row=await server.db.loan_lines.find_one({"id":l.get("loan_line_id")})
        if row and float(row.get("returned") or 0)<0:
            await server.db.loan_lines.update_one({"id":l.get("loan_line_id")},{"$set":{"returned":0}})


def install(server):
    app=server.app

    route=_find_route(app,"/api/loans/{did}/return","POST")
    if route:
        original=route.endpoint
        app.router.routes.remove(route)
        async def return_with_lines(did:str,body:dict,user=Depends(server.current_user)):
            before={r["id"] for r in await server.db.loan_returns.find({"loan_id":did},{"id":1,"_id":0}).to_list(5000)}
            requested=[]
            for raw in (body or {}).get("lines",[]):
                ll=await server.db.loan_lines.find_one({"id":raw.get("loan_line_id")},{"_id":0}) or {}
                factor=float(ll.get("conversion_factor") or 1)
                requested.append({"loan_line_id":raw.get("loan_line_id"),"item_id":ll.get("item_id"),"qty":float(raw.get("qty") or 0)*factor})
            result=await original(did,body,user)
            ret=await server.db.loan_returns.find_one({"loan_id":did,"id":{"$nin":list(before)}},{"_id":0},sort=[("created_at",-1)])
            if ret:
                docs=[]
                for x in requested:
                    if x["qty"]>0: docs.append({"id":server.gid(),"return_id":ret["id"],"loan_id":did,**x})
                if docs: await server.db.loan_return_lines.insert_many(docs)
            return result
        app.add_api_route("/api/loans/{did}/return",return_with_lines,methods=["POST"],tags=["loan-return"])

    @app.get("/api/loans/{did}/returns",tags=["loan-return"])
    async def list_returns(did:str,user=Depends(server.current_user)):
        server.require(user,"view")
        docs=await server.db.loan_returns.find({"loan_id":did},{"_id":0}).sort("created_at",-1).to_list(1000)
        items={i["id"]:i for i in await server.db.items.find({}, {"_id":0}).to_list(5000)}
        out=[]
        for ret in docs:
            lines=await _get_lines(server,ret)
            ret["legacy_ambiguous"]=lines is None
            ret["lines"]=[] if lines is None else [{**l,"item_code":items.get(l.get("item_id"),{}).get("code"),"item_name":items.get(l.get("item_id"),{}).get("name")} for l in lines]
            out.append(ret)
        return out

    @app.get("/api/loan-returns/{rid}/capability",tags=["loan-return"])
    async def return_capability(rid:str,user=Depends(server.current_user)):
        ret=await server.db.loan_returns.find_one({"id":rid},{"_id":0})
        if not ret: raise HTTPException(404,"Return tidak ditemukan")
        lines=await _get_lines(server,ret)
        blockers=[]
        if lines is None: blockers.append("Return lama tidak memiliki jejak baris yang unik")
        blockers += await _reverse_blockers(server,rid)
        return {"id":rid,"no":ret.get("no"),"can_edit":server.has_perm(user,"edit") and not blockers,"can_delete":server.has_perm(user,"delete") and not blockers,"blockers":blockers,"reason":("; ".join(blockers) if blockers else None)}

    @app.put("/api/loan-returns/{rid}",tags=["loan-return"])
    async def edit_return(rid:str,body:dict,user=Depends(server.current_user)):
        server.require(user,"edit")
        ret=await server.db.loan_returns.find_one({"id":rid},{"_id":0})
        if not ret: raise HTTPException(404,"Return tidak ditemukan")
        old=await _get_lines(server,ret)
        if old is None: raise HTTPException(409,"Return lama ini tidak bisa diedit aman karena jejak baris tidak unik")
        blockers=await _reverse_blockers(server,rid)
        if blockers: raise HTTPException(409,"Stok hasil return sudah terpakai. Koreksi transaksi pemakaian stok terlebih dahulu.")
        loan=await server.db.loans.find_one({"id":ret.get("loan_id")},{"_id":0})
        await _reverse(server,rid,user,"edit return")
        await _decrement_old(server,old)
        new=[]
        for raw in (body or {}).get("lines",[]):
            ll=await server.db.loan_lines.find_one({"id":raw.get("loan_line_id")},{"_id":0})
            if not ll: raise HTTPException(400,"Baris pinjaman tidak ditemukan")
            qty=float(raw.get("qty") or 0)
            rem=float(ll.get("qty") or 0)-float(ll.get("returned") or 0)
            if qty>rem+1e-6 and not server.has_perm(user,"override_qty"): raise HTTPException(400,"Qty return melebihi outstanding pinjaman")
            if qty<=0: continue
            await server.db.loan_lines.update_one({"id":ll["id"]},{"$inc":{"returned":qty}})
            await server.post_ledger("Loan Return Out",ret.get("no"),rid,ll.get("item_id"),loan.get("to_warehouse_id"),0,qty,user=user)
            await server.post_ledger("Loan Return In",ret.get("no"),rid,ll.get("item_id"),loan.get("from_warehouse_id"),qty,0,user=user)
            new.append({"id":server.gid(),"return_id":rid,"loan_id":ret.get("loan_id"),"loan_line_id":ll["id"],"item_id":ll.get("item_id"),"qty":qty})
        await server.db.loan_return_lines.delete_many({"return_id":rid})
        if new: await server.db.loan_return_lines.insert_many(new)
        await server.db.loan_returns.update_one({"id":rid},{"$set":{"date":(body or {}).get("date",ret.get("date")),"notes":(body or {}).get("notes",ret.get("notes")),"updated_at":server.now_iso(),"updated_by":user.get("email")}})
        await server.audit(user,"edit","loan_return",rid,ret.get("no"),before={"header":ret,"lines":old},after={"line_count":len(new)})
        return {"ok":True,"id":rid,"no":ret.get("no")}

    @app.delete("/api/loan-returns/{rid}",tags=["loan-return"])
    async def delete_return(rid:str,user=Depends(server.current_user)):
        server.require(user,"delete")
        ret=await server.db.loan_returns.find_one({"id":rid},{"_id":0})
        if not ret: raise HTTPException(404,"Return tidak ditemukan")
        lines=await _get_lines(server,ret)
        if lines is None: raise HTTPException(409,"Return lama ini tidak bisa dihapus aman karena jejak baris tidak unik")
        blockers=await _reverse_blockers(server,rid)
        if blockers: raise HTTPException(409,"Stok hasil return sudah terpakai. Koreksi transaksi pemakaian stok terlebih dahulu.")
        await _reverse(server,rid,user,"delete return")
        await _decrement_old(server,lines)
        await server.db.loan_return_lines.delete_many({"return_id":rid})
        await server.db.loan_returns.delete_one({"id":rid})
        await server.db.attachments.update_many({"entity":"loan_return","entity_id":rid},{"$set":{"is_deleted":True}})
        await server.audit(user,"delete","loan_return",rid,ret.get("no"),before={"header":ret,"lines":lines})
        return {"ok":True,"id":rid,"no":ret.get("no")}
