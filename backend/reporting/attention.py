"""PO / Invoice yang perlu ditindaklanjuti — hanya exception/action item, paling urgent dahulu."""
from __future__ import annotations

from . import finance as F
from . import procurement as P

# prioritas: 1 invoice lewat jatuh tempo, 2 jatuh tempo <=7 hari, 3 PO terlambat, 4 menunggu approval,
# 5 PO belum diterima, 6 invoice belum diterima (DO belum ditagih), 7 invoice belum dibayar
REASON = {1: "Lewat jatuh tempo", 2: "Jatuh tempo ≤ 7 hari", 3: "PO terlambat (lewat ETA)", 4: "Menunggu approval",
          5: "PO belum diterima", 6: "Invoice belum diterima", 7: "Invoice belum dibayar"}
LIMIT = 300


def _po(r, prio, tabs, price):
    return {"key": f"po:{r['id']}", "doc_type": "PO", "id": r["id"], "no": r.get("no"), "path": f"/po/{r['id']}",
            "date": r.get("date"), "supplier_name": r.get("supplier_name"), "project": r.get("trace_project") or "",
            "division": r.get("trace_division") or r.get("division_name") or "",
            "value": (float(r.get("grand_total") or 0) if price else None), "document_status": r.get("document_status"),
            "receipt_status": r.get("receipt_status"), "payment_status": None, "due_date": None, "due_state": None,
            "eta": r.get("eta"), "priority": prio, "reason": REASON[prio], "tabs": tabs, "sort": str(r.get("eta") or r.get("date") or "")}


def _inv(i, prio, tabs):
    return {"key": f"inv:{i['id']}", "doc_type": "Invoice", "id": i["id"], "no": i.get("invoice_no") or i.get("no"),
            "path": f"/invoice/{i['id']}", "date": i.get("invoice_date"), "supplier_name": i.get("supplier_name"),
            "project": i.get("trace_project") or "", "division": i.get("trace_division") or "", "value": round(F.outstanding(i), 2),
            "document_status": i.get("status"), "receipt_status": None, "payment_status": i.get("payment_status"),
            "due_date": i.get("due_date"), "due_state": i.get("due_state"), "eta": None, "priority": prio,
            "reason": REASON[prio], "tabs": tabs, "sort": str(i.get("due_date") or "9999")}


def _do(d):
    return {"key": f"do:{d['do_id']}", "doc_type": "DO", "id": d["do_id"], "no": d.get("do_no"), "path": f"/do/{d['do_id']}",
            "date": d.get("date"), "supplier_name": d.get("supplier_name"), "project": d.get("project") or "",
            "division": d.get("division") or "", "value": float(d.get("remaining") or 0), "document_status": d.get("billing_status"),
            "receipt_status": None, "payment_status": None, "due_date": None, "due_state": None, "eta": None,
            "priority": 6, "reason": REASON[6], "tabs": ["unbilled"], "sort": str(d.get("date") or "")}


def build(po_rows, invs, dos, f, perm):
    td, price, rows = f.today, perm["price"], []
    for r in po_rows:
        tabs = []
        if P.PO_KINDS["waiting_approval"](r, td):
            tabs.append("approval")
        if P.PO_KINDS["not_received"](r, td) or P.PO_KINDS["late"](r, td):
            tabs.append("not_received")
        if not tabs:
            continue
        prio = 3 if P.PO_KINDS["late"](r, td) else 4 if "approval" in tabs else 5
        rows.append(_po(r, prio, tabs, price))
    for i in invs or []:
        if not F.INV_KINDS["unpaid"](i):
            continue
        due = F.INV_KINDS["overdue"](i) or F.INV_KINDS["due_soon"](i)
        prio = 1 if F.INV_KINDS["overdue"](i) else 2 if due else 7
        rows.append(_inv(i, prio, ["unpaid"] + (["due"] if due else [])))
    for d in dos or []:
        if F.DO_KINDS["unbilled"](d):
            rows.append(_do(d))
    rows.sort(key=lambda x: (x["priority"], x["sort"], str(x["no"] or "")))
    counts = {"all": len(rows)}
    for t in ("approval", "not_received", "unbilled", "unpaid", "due"):
        counts[t] = sum(1 for x in rows if t in x["tabs"])
    for x in rows:
        x.pop("sort", None)
    return {"counts": counts, "rows": rows[:LIMIT], "truncated": len(rows) > LIMIT}
