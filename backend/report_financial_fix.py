"""Correct traceability PO/DO financials using stored DPP/tax snapshots.

The base report builds lifecycle references. This wrapper recalculates PO money
and received quantities so tax-inclusive POs and consolidated PO lines remain
correct. DO value = allocated PO DPP per base unit x received quantity.
"""
import report_trace_detail


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def install(server):
    original = report_trace_detail._build_rows

    # report_trace_detail's route calls the module-level _build_rows with
    # (server, date_from, date_to, user). Keep exactly that signature when we
    # replace the function; otherwise the report endpoint fails and the MRO
    # list (which also loads traceability) can appear empty.
    async def build_rows(server_arg, date_from=None, date_to=None, user=None):
        rows = await original(server_arg, date_from, date_to, user)
        if not user or not server.has_perm(user, "view_purchase_price"):
            return rows

        for row in rows:
            row.update({
                "qty_received": 0.0,
                "po_gross": 0.0,
                "po_discount": 0.0,
                "po_dpp": 0.0,
                "po_tax": 0.0,
                "po_total": 0.0,
                "do_total": 0.0,
            })
            mro_lines = await server.db.mro_lines.find(
                {"mro_id": row.get("mro_id"), "item_id": row.get("item_id")}, {"_id": 0}
            ).to_list(2000)
            for ml in mro_lines:
                ro_allocs = await server.db.allocations.find(
                    {"source_line_id": ml["id"], "target_type": "ro"}, {"_id": 0}
                ).to_list(1000)
                for ra in ro_allocs:
                    po_allocs = await server.db.allocations.find(
                        {"source_line_id": ra.get("target_line_id"), "target_type": "po"}, {"_id": 0}
                    ).to_list(1000)
                    for pa in po_allocs:
                        pl = await server.db.po_lines.find_one(
                            {"id": pa.get("target_line_id")}, {"_id": 0}
                        ) or {}
                        qty = _f(pl.get("qty"))
                        allocated = _f(pa.get("qty"))
                        share = allocated / qty if qty > 0 else 0.0

                        gross = _f(pl.get("gross")) if pl.get("gross") is not None else qty * _f(pl.get("price"))
                        discount = _f(pl.get("discount"))
                        if pl.get("dpp") is not None:
                            dpp = _f(pl.get("dpp"))
                        else:
                            net = max(0.0, gross - discount)
                            rate = _f(pl.get("tax"))
                            dpp = net / (1 + rate / 100.0) if pl.get("tax_inclusive") and rate else net
                        tax_amount = _f(pl.get("tax_amount")) if pl.get("tax_amount") is not None else dpp * _f(pl.get("tax")) / 100.0
                        total = _f(pl.get("total")) if pl.get("total") is not None else dpp + tax_amount

                        row["po_gross"] += gross * share
                        row["po_discount"] += discount * share
                        row["po_dpp"] += dpp * share
                        row["po_tax"] += tax_amount * share
                        row["po_total"] += total * share

                        unit_dpp = dpp / qty if qty > 0 else 0.0
                        do_allocs = await server.db.allocations.find(
                            {"source_line_id": pa.get("target_line_id"), "target_type": "do"}, {"_id": 0}
                        ).to_list(1000)
                        for da in do_allocs:
                            received_for_source = _f(da.get("qty")) * share
                            row["qty_received"] += received_for_source
                            row["do_total"] += unit_dpp * received_for_source
        return rows

    report_trace_detail._build_rows = build_rows
