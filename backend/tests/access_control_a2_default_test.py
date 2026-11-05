"""Default izin Approval 2 per role (murni, tanpa DB/HTTP).

Purchasing mengajukan batch (view + submit + print) tetapi tidak menyetujui; director/manager yang
memegang legacy "approve" tetap mendapat keempat izin. Jalankan dari backend/:
    python tests/access_control_a2_default_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from access_control_layer import A2_KEYS, A2_SUBMIT_KEYS, legacy_to_granular, role_cfg_permissions  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


# Legacy default role (ALL_PERMISSIONS subset di server.ROLE_DEFAULTS) — sengaja tanpa "approve" untuk purchasing.
PURCHASING_LEGACY = ["view", "create", "edit", "submit", "cancel", "print", "export", "upload_attachment",
                     "view_all_division", "view_all_warehouse", "view_purchase_price", "edit_purchase_price"]
MANAGER_LEGACY = ["view", "create", "edit", "submit", "approve", "reject", "cancel", "close", "print", "export",
                  "view_all_division", "view_all_warehouse", "view_purchase_price"]
WAREHOUSE_LEGACY = ["view", "create", "edit", "submit", "print", "upload_attachment", "direct_mi"]

pur = legacy_to_granular(PURCHASING_LEGACY, "purchasing")
check("purchasing: dapat lihat Approval 2", "po_approval2.view" in pur)
check("purchasing: dapat mengajukan Approval 2 (submit)", "po_approval2.submit" in pur)
check("purchasing: dapat mencetak batch", "po_approval2.print" in pur)
check("purchasing: TIDAK dapat menyetujui", "po_approval2.approve" not in pur)
check("purchasing: tidak menambah izin lain di luar A2", (pur & A2_KEYS) == A2_SUBMIT_KEYS, sorted(pur & A2_KEYS))

mgr = legacy_to_granular(MANAGER_LEGACY, "manager")
check("manager (legacy approve): keempat izin A2", (mgr & A2_KEYS) == A2_KEYS, sorted(mgr & A2_KEYS))

wh = legacy_to_granular(WAREHOUSE_LEGACY, "warehouse")
check("warehouse: tidak otomatis mendapat izin Approval 2", not (wh & A2_KEYS), sorted(wh & A2_KEYS))

fin = legacy_to_granular(["view", "print", "export"], "finance")
check("finance: tidak otomatis mendapat izin Approval 2", not (fin & A2_KEYS), sorted(fin & A2_KEYS))

# Migrasi konfigurasi role lama (tersimpan sebelum izin po_approval2 ada / a2_configured belum diisi).
old_purchasing = role_cfg_permissions({"role": "purchasing", "permissions": ["po.view", "po.create", "do.view"]})
check("migrasi config lama purchasing: dapat ajukan", (old_purchasing & A2_KEYS) == A2_SUBMIT_KEYS,
      sorted(old_purchasing & A2_KEYS))
old_mgr = role_cfg_permissions({"role": "manager", "permissions": ["po.view", "po.approve"]})
check("migrasi config lama manager (punya po.approve): keempat izin", (old_mgr & A2_KEYS) == A2_KEYS,
      sorted(old_mgr & A2_KEYS))
configured = role_cfg_permissions({"role": "purchasing", "a2_configured": True,
                                   "permissions": ["po.view", "po_approval2.view"]})
check("config yang sudah disimpan apa adanya (a2_configured) tidak ditambah",
      (configured & A2_KEYS) == {"po_approval2.view"}, sorted(configured & A2_KEYS))

passed = sum(1 for r in RESULTS if r)
print(f"\n{passed}/{len(RESULTS)} passed")
sys.exit(0 if passed == len(RESULTS) else 1)
