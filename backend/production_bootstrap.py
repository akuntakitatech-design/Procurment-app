"""Production bootstrap for self-hosted deployment.

The original Emergent-generated app seeds demo warehouses/items/opening stock and writes
admin test credentials to disk on startup. Production disables both behaviours by default.
"""
import os

os.environ.setdefault("PROCUREFLOW_ENTRY", "bootstrap")

import uvicorn

import server
import master_auto
import contact_master_layer
import master_code_settings_layer
import master_delete_guard_layer
import uom_layer
import tax_layer
import supplier_po_layer
import document_defaults_layer
import document_message_layer
import print_layout_layer
import email_outbound_layer
import po_email_signature_layer
import source_inheritance_layer
import approval_email_layer
import transaction_integrity_layer
import pull_source_eligibility_layer
import transaction_mutation_layer
import transaction_mutation_safety_layer
import po_buyer_contact_layer
import loan_return_mutation_layer
import premium_dashboard_layer
import activity_log_layer
import report_trace_detail
import report_financial_fix
import lifecycle_tracker
import company_branding
import excel_import_layer
import opening_inventory_layer


async def production_seed_defaults():
    """Seed only safe system defaults required by transactions."""
    if await server.db.settings.find_one({"id": "numbering"}) is None:
        await server.db.settings.insert_one({
            "id": "numbering",
            "formats": {
                "MRO": "MRO/{year}/{month}/{seq}",
                "RO": "RO/{year}/{month}/{seq}",
                "PO": "PO/{year}/{month}/{seq}",
                "DO": "DO/{year}/{month}/{seq}",
                "MI": "MI/{year}/{month}/{seq}",
                "TRF": "TRF/{year}/{month}/{seq}",
                "LOAN": "LOAN/{year}/{month}/{seq}",
                "RET": "RET/{year}/{month}/{seq}",
                "ADJ": "ADJ/{year}/{month}/{seq}",
                "OPN": "OPN/{year}/{month}/{seq}",
            },
        })

    if await server.db.settings.find_one({"id": "approval_rules"}) is None:
        await server.db.settings.insert_one({"id": "approval_rules", "rules": []})

    if await server.db.settings.find_one({"id": "approval_levels"}) is None:
        await server.db.settings.insert_one({"id": "approval_levels", "levels": []})

    if await server.db.settings.find_one({"id": "approval_modules"}) is None:
        legacy = await server.db.settings.find_one({"id": "approval_levels"}, {"_id": 0}) or {}
        legacy_levels = legacy.get("levels") or []
        await server.db.settings.insert_one({
            "id": "approval_modules",
            "modules": {
                "mro": {"enabled": False, "levels": []},
                "ro": {"enabled": False, "levels": []},
                "po": {"enabled": bool(legacy_levels), "levels": legacy_levels},
            },
        })

    if await server.db.settings.find_one({"id": "company"}) is None:
        await server.db.settings.insert_one({
            "id": "company",
            "name": "PT. Perusahaan Anda",
            "address": "Alamat perusahaan",
            "app_subtitle": "Procurement & Inventory",
            "damaged_method": "method1",
        })


async def no_test_credentials_file():
    return None


if os.environ.get("ALLOW_DEMO_SEED", "false").lower() not in ("1", "true", "yes"):
    server.seed_defaults = production_seed_defaults

if os.environ.get("WRITE_TEST_CREDENTIALS", "false").lower() not in ("1", "true", "yes"):
    server.write_test_credentials = no_test_credentials_file

master_auto.install(server)
contact_master_layer.install(server)
master_code_settings_layer.install(server)
master_delete_guard_layer.install(server)
uom_layer.install(server)
tax_layer.install(server)
supplier_po_layer.install(server)
document_defaults_layer.install(server)
document_message_layer.install(server)
print_layout_layer.install(server)
email_outbound_layer.install(server)
po_email_signature_layer.install(server)
source_inheritance_layer.install(server)
approval_email_layer.install(server)
transaction_integrity_layer.install(server)
pull_source_eligibility_layer.install(server)
transaction_mutation_layer.install(server)
transaction_mutation_safety_layer.install(server)
po_buyer_contact_layer.install(server)
loan_return_mutation_layer.install(server)
premium_dashboard_layer.install(server)
activity_log_layer.install(server)
report_trace_detail.install(server)
report_financial_fix.install(server)
lifecycle_tracker.install(server)
company_branding.install(server)
# Register opening inventory before the generic Excel routes are installed.
opening_inventory_layer.install(server, excel_import_layer)
# Install last so transaction imports call the final wrapped transaction endpoints.
excel_import_layer.install(server)


if __name__ == "__main__":
    uvicorn.run(
        server.app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
