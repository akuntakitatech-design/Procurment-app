"""Production bootstrap for self-hosted deployment.

The original Emergent-generated app seeds demo warehouses/items/opening stock and writes
admin test credentials to disk on startup. Production disables both behaviours by default.
"""
import os

os.environ.setdefault("PROCUREFLOW_ENTRY", "bootstrap")

import uvicorn

import server
import tenant_foundation_layer
import tenant_isolation_layer
import tenant_security_hardening_layer
import attachment_query_token_compat_layer
import attachment_integrity_guard_layer
import saas_platform_layer
import tenant_invite_layer
import tenant_invite_platform_layer
import subscription_lifecycle_layer
import subscription_admin_layer
import subscription_access_gate_layer
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
import item_warehouse_guard_layer
import stock_opname_guard_layer
import po_buyer_contact_layer
import loan_return_mutation_layer
import loan_return_integrity_guard_layer
import premium_dashboard_layer
import activity_log_layer
import report_trace_detail
import report_financial_fix
import report_control_scope_layer
import lifecycle_tracker
import company_branding
import platform_branding
import division_visibility_layer
import procurement_action_guard_layer
import approval_state_guard_layer
import do_receipt_guard_layer
import do_receipt_condition_layer
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

# Install tenant foundation before feature layers. Its startup migration is additive only:
# the existing installation becomes the first tenant while business data remains intact.
tenant_foundation_layer.install(server)
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
# Transaction attachments must point to an existing tenant-owned document and obey size/type limits.
attachment_integrity_guard_layer.install(server)
source_inheritance_layer.install(server)
approval_email_layer.install(server)
transaction_integrity_layer.install(server)
pull_source_eligibility_layer.install(server)
transaction_mutation_layer.install(server)
transaction_mutation_safety_layer.install(server)
# Item/warehouse settings may tune min/max only; physical stock stays ledger-controlled.
item_warehouse_guard_layer.install(server)
# Stock Opname needs line ownership, complete-count, non-negative, and posted-correction guards.
stock_opname_guard_layer.install(server)
po_buyer_contact_layer.install(server)
loan_return_mutation_layer.install(server)
# Validate return ownership/quantity/borrower stock before legacy return handlers write anything.
loan_return_integrity_guard_layer.install(server)
premium_dashboard_layer.install(server)
activity_log_layer.install(server)
report_trace_detail.install(server)
report_financial_fix.install(server)
lifecycle_tracker.install(server)
company_branding.install(server)
platform_branding.install(server)
# Enforce division visibility after procurement routes have received all approval, integrity,
# source-pull, mutation, and PO-contact wrappers. Excel import is installed afterwards so its
# transaction calls also hit the final division-aware routes.
division_visibility_layer.install(server)
# Reports/control surfaces must follow the same division and warehouse visibility as transactions.
report_control_scope_layer.install(server)
# Direct submit/cancel/approve/reject actions need the same division boundary, and source
# documents may not be cancelled/re-submitted while active downstream transactions exist.
procurement_action_guard_layer.install(server)
# Approval lifecycle state is the final procurement action guard: stale approval tasks cannot
# process cancelled documents, rejected docs must be revised, and resubmission cannot reset an
# approval that is already waiting or completed.
approval_state_guard_layer.install(server)
# DO is a stock-posting transaction, so validate its complete PO source/supplier/division/
# warehouse/quantity context before any receipt is written, and keep edit/delete equally scoped.
do_receipt_guard_layer.install(server)
# Receipt quality/discrepancy sits outside the PO quantity guard. Damaged quantities are removed
# from usable stock via an offset ledger while shortage/excess remain documented exceptions.
do_receipt_condition_layer.install(server)
# Register opening inventory before the generic Excel routes are installed.
opening_inventory_layer.install(server, excel_import_layer)
# Install last so transaction imports call the final wrapped transaction endpoints.
excel_import_layer.install(server)

# SaaS registration/platform routes are registered before isolation activation. Their startup
# bootstrap runs after the default PT REAL tenant backfill and creates only platform metadata.
saas_platform_layer.install(server)
# Tenant invitation routes are also registered before isolation activation. Authenticated
# creation/list/cancel remain tenant-scoped, while public acceptance resolves its tenant through
# a deliberately narrow raw-database path before the invited user has a session.
tenant_invite_layer.install(server)
# Platform Super Admin gets read-only invitation visibility through a separate endpoint.
tenant_invite_platform_layer.install(server)
# Subscription lifecycle reconciles trial/active/limited/locked dates, creates tenant-scoped
# reminder notifications, and exposes lifecycle status to tenant owners and Platform Admin.
subscription_lifecycle_layer.install(server)
# Platform Admin can adjust trial, paid subscription dates, and limited-access duration.
subscription_admin_layer.install(server)

# Harden proxy ownership, cross-source references and attachment storage/download rules before
# isolation middleware/startup activation. Isolation is still installed after all business
# routes so it can patch any cached raw database references.
tenant_security_hardening_layer.install(server)

# Tenant isolation is installed after all business/feature modules are registered. Its startup
# handler runs after the original server startup and additive foundation backfill, then replaces
# raw database references with tenant-aware proxies.
tenant_isolation_layer.install(server)

# The subscription gate runs after isolation so it can enforce lifecycle access on every tenant
# API request. Attachment auth compatibility remains outermost so legacy ?auth= links are first
# normalized into Bearer auth before this gate evaluates the tenant.
subscription_access_gate_layer.install(server)

# Compatibility normalization is middleware-only and intentionally installed after isolation and
# the subscription gate so it runs outermost: legacy ?auth= attachment links are converted into
# normal Bearer auth before tenant isolation/security/access middleware resolve identity.
attachment_query_token_compat_layer.install(server)


if __name__ == "__main__":
    uvicorn.run(
        server.app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
