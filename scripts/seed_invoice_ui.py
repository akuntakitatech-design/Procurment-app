"""Seed a throwaway tenant for Invoice Vendor UI QA. Prints login email (password TestPass123!)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "tests"))
import receipt_control_test as T  # noqa: E402

M = T.setup()
dos = []
for qty in (10000, 15000, 5000, 20000):
    po, _, _ = T.make_po(M, "supX", qty)
    dos.append(T.call("POST", "do", T.do_body(M, po, qty, "supX"), 200)[1])
sc, inv = T.call("POST", "vendor-invoices", {"supplier_id": M["supX"]["id"], "invoice_no": "INV-SEED-01", "invoice_date": "2026-06-01",
                                              "received_date": "2026-06-02", "due_date": "2026-06-20", "amount": 12_000_000, "tax_amount": 0,
                                              "allocations": [{"do_id": dos[3]["id"], "amount": 12_000_000}]}, 200)
T.call("POST", f"vendor-invoices/{inv['id']}/payments", {"date": "2026-06-05", "amount": 5_000_000, "reference": "TRF-SEED"}, 200)
email = T.S.get(f"{T.API}/auth/me").json().get("email")
print(f"EMAIL={email}\nPASSWORD=TestPass123!\nSUPPLIER=Supplier X\nDO={','.join(d['no'] for d in dos)}\nINVOICE=INV-SEED-01")
