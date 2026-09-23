"""Premium dashboard aggregates for executive procurement and inventory control."""
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import Depends


def _month(v):
    s = str(v or "")
    return s[:7] if len(s) >= 7 else ""


def _active_po(doc):
    status = str(doc.get("status") or "").strip().lower()
    return not doc.get("cancelled") and status not in ("cancelled", "canceled", "rejected")


def _line_dpp(line):
    if line.get("dpp") is not None:
        return float(line.get("dpp") or 0)
    qty = float(line.get("qty") or 0)
    price = float(line.get("price") or 0)
    discount = float(line.get("discount") or 0)
    return max(0.0, qty * price - discount)


def _scope_query(server, user):
    if server.is_global(user):
        return {}
    divisions = user.get("divisions") or []
    return {"division_id": {"$in": divisions}} if divisions else {"division_id": "__none__"}


def install(server):
    app = server.app

    @app.get("/api/dashboard-premium", tags=["dashboard"])
    async def dashboard_premium(user=Depends(server.current_user)):
        server.require(user, "view")
        year = datetime.now(timezone.utc).year
        year_prefix = f"{year}-"
        scope = _scope_query(server, user)
        financial_visible = server.has_perm(user, "view_purchase_price")

        po_docs = await server.db.po.find(scope, {"_id": 0}).to_list(10000)
        po_docs = [d for d in po_docs if _active_po(d) and str(d.get("date") or "").startswith(year_prefix)]
        po_ids = [d.get("id") for d in po_docs if d.get("id")]
        po_by_id = {d.get("id"): d for d in po_docs}

        po_lines = await server.db.po_lines.find({"po_id": {"$in": po_ids}}, {"_id": 0}).to_list(50000) if po_ids else []
        line_ids = [l.get("id") for l in po_lines if l.get("id")]

        do_docs = await server.db.do.find({"cancelled": {"$ne": True}, "deleted": {"$ne": True}}, {"_id": 0, "id": 1, "status": 1}).to_list(20000)
        active_do_ids = {d.get("id") for d in do_docs if str(d.get("status") or "").lower() not in ("cancelled", "canceled", "rejected")}
        allocs = await server.db.allocations.find({"source_line_id": {"$in": line_ids}, "target_type": "do"}, {"_id": 0}).to_list(100000) if line_ids else []
        received_by_line = defaultdict(float)
        for a in allocs:
            if a.get("target_doc_id") in active_do_ids:
                received_by_line[a.get("source_line_id")] += float(a.get("qty") or 0)

        items = await server.db.items.find({}, {"_id": 0, "id": 1, "category_id": 1}).to_list(20000)
        item_category = {x.get("id"): x.get("category_id") for x in items}
        categories = await server.db.item_categories.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5000)
        category_name = {x.get("id"): x.get("name") for x in categories}
        suppliers = await server.db.suppliers.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(10000)
        supplier_name = {x.get("id"): x.get("name") for x in suppliers}

        line_count = len(po_lines)
        closed_lines = partial_lines = not_received_lines = over_delivery_lines = 0
        po_value = received_value = 0.0
        monthly = defaultdict(lambda: {"po_value": 0.0, "received_value": 0.0, "categories": defaultdict(lambda: {"po_value": 0.0, "received_value": 0.0})})
        category_totals = defaultdict(float)
        supplier_totals = defaultdict(float)

        for line in po_lines:
            qty = float(line.get("qty") or 0)
            received = received_by_line.get(line.get("id"), 0.0)
            if qty > 0 and received >= qty - 1e-9:
                closed_lines += 1
            elif received > 1e-9:
                partial_lines += 1
            else:
                not_received_lines += 1
            if qty > 0 and received > qty + 1e-9:
                over_delivery_lines += 1

            dpp = _line_dpp(line)
            ratio = min(1.0, max(0.0, (received / qty) if qty > 0 else 0.0))
            recv_val = dpp * ratio
            po_value += dpp
            received_value += recv_val

            po = po_by_id.get(line.get("po_id"), {})
            m = _month(po.get("date"))
            cat_id = item_category.get(line.get("item_id"))
            cat = category_name.get(cat_id) or "Tanpa Kategori"
            if m:
                monthly[m]["po_value"] += dpp
                monthly[m]["received_value"] += recv_val
                monthly[m]["categories"][cat]["po_value"] += dpp
                monthly[m]["categories"][cat]["received_value"] += recv_val
            category_totals[cat] += dpp
            supplier_totals[supplier_name.get(po.get("supplier_id")) or "Tanpa Supplier"] += dpp

        monthly_rows = []
        for m in sorted(monthly):
            row = monthly[m]
            cats = []
            for cat, vals in sorted(row["categories"].items(), key=lambda x: x[1]["po_value"], reverse=True):
                cats.append({
                    "category": cat,
                    "po_value": vals["po_value"],
                    "received_value": vals["received_value"],
                    "outstanding": max(0.0, vals["po_value"] - vals["received_value"]),
                })
            monthly_rows.append({
                "month": m,
                "po_value": row["po_value"],
                "received_value": row["received_value"],
                "outstanding": max(0.0, row["po_value"] - row["received_value"]),
                "categories": cats,
            })

        today = datetime.now(timezone.utc).date().isoformat()
        overdue_po = 0
        for d in po_docs:
            eta = str(d.get("eta") or "")[:10]
            if not eta or eta >= today:
                continue
            lines = [x for x in po_lines if x.get("po_id") == d.get("id")]
            if any(received_by_line.get(x.get("id"), 0.0) < float(x.get("qty") or 0) - 1e-9 for x in lines):
                overdue_po += 1

        pending_approvals = await server.db.approval_tasks.count_documents({"status": "Pending"})
        overdue_loans = 0
        loan_docs = await server.db.loans.find({}, {"_id": 0}).to_list(10000)
        for loan in loan_docs:
            due = str(loan.get("due_date") or "")[:10]
            if not due or due >= today:
                continue
            lines = await server.db.loan_lines.find({"loan_id": loan.get("id")}, {"_id": 0, "qty": 1, "returned": 1}).to_list(2000)
            if any(float(x.get("qty") or 0) - float(x.get("returned") or 0) > 1e-9 for x in lines):
                overdue_loans += 1

        recent = await server.db.audit_logs.find({}, {"_id": 0}).sort("at", -1).to_list(8)
        top_categories = [{"name": k, "value": v} for k, v in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)[:5]]
        top_suppliers = [{"name": k, "value": v} for k, v in sorted(supplier_totals.items(), key=lambda x: x[1], reverse=True)[:5]]

        return {
            "year": year,
            "financial_visible": financial_visible,
            "po": {
                "total_docs": len(po_docs),
                "line_count": line_count,
                "closed_lines": closed_lines,
                "partial_lines": partial_lines,
                "not_received_lines": not_received_lines,
                "over_delivery_lines": over_delivery_lines,
                "po_value": po_value if financial_visible else None,
                "received_value": received_value if financial_visible else None,
                "outstanding_value": max(0.0, po_value - received_value) if financial_visible else None,
            },
            "monthly": monthly_rows if financial_visible else [],
            "top_categories": top_categories if financial_visible else [],
            "top_suppliers": top_suppliers if financial_visible else [],
            "attention": {
                "pending_approvals": pending_approvals,
                "overdue_po": overdue_po,
                "overdue_loans": overdue_loans,
                "over_delivery_lines": over_delivery_lines,
            },
            "recent": recent,
        }
