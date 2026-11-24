"""Uji izin halaman yang sebelumnya tidak punya baris di Hak Akses.

Yang dijaga:
- Kunci baru terdaftar di katalog (SPECIALS) dan ALL_KEYS sehingga muncul di UI + bisa disimpan.
- Default per role sesuai kebijakan yang disetujui.
- Konfigurasi role lama (tanpa `perm_v2`) otomatis mendapat default -> perilaku tidak berubah
  sebelum admin menyimpan ulang dari UI. Setelah disimpan (`perm_v2`), nilai tersimpan yang berlaku.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import access_control_layer as AC  # noqa: E402

fail = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info not in ("", None) else ""))
    if not ok:
        fail.append(name)


NEW_KEYS = {"inventory.view", "report_center.view", "activity_log.view", "print_layout.manage",
            "excel_import.view", "excel_import.create", "settings.edit"}

# --- katalog
check("semua kunci baru ada di ALL_KEYS", NEW_KEYS <= AC.ALL_KEYS, sorted(NEW_KEYS - AC.ALL_KEYS))
_labels = dict(AC.SPECIALS)
check("semua kunci baru punya label di katalog", NEW_KEYS <= set(_labels), sorted(NEW_KEYS - set(_labels)))
check("modul transaksi tidak berubah (tetap 9 modul transaksi)",
      len(AC.TXN) == 9 and "po_approval2" not in AC.TXN, AC.TXN)

# --- default sesuai kebijakan
def defaults(role):
    return set(AC.NEW_DEFAULTS.get(role) or ())


check("warehouse: inventory + import excel", defaults("warehouse") == {"inventory.view", "excel_import.view", "excel_import.create"},
      sorted(defaults("warehouse")))
check("manager: inventory + pusat laporan", defaults("manager") == {"inventory.view", "report_center.view"},
      sorted(defaults("manager")))
check("director: inventory + pusat laporan", defaults("director") == {"inventory.view", "report_center.view"},
      sorted(defaults("director")))
check("purchasing: inventory + laporan + import", defaults("purchasing") ==
      {"inventory.view", "report_center.view", "excel_import.view", "excel_import.create"},
      sorted(defaults("purchasing")))
check("finance: inventory + pusat laporan", defaults("finance") == {"inventory.view", "report_center.view"},
      sorted(defaults("finance")))
check("log aktivitas: admin saja (tidak ada default role lain)",
      all("activity_log.view" not in defaults(r) for r in ("director", "manager", "purchasing", "warehouse", "finance")))
check("layout dokumen & ubah pengaturan: admin saja",
      all("print_layout.manage" not in defaults(r) and "settings.edit" not in defaults(r)
          for r in ("director", "manager", "purchasing", "warehouse", "finance")))

# --- migrasi konfigurasi role lama
legacy_wh = {"role": "warehouse", "permissions": ["mro.view", "do.view", "do.create", "do.post"]}
perms = AC.role_cfg_permissions(legacy_wh)
check("role lama warehouse otomatis dapat default baru",
      {"inventory.view", "excel_import.view", "excel_import.create"} <= perms, sorted(perms)[:8])
check("role lama warehouse tidak mendapat log aktivitas / layout / pengaturan",
      not ({"activity_log.view", "print_layout.manage", "settings.edit"} & perms))
check("izin lama tetap utuh setelah migrasi", {"mro.view", "do.view", "do.create", "do.post"} <= perms)

saved = {"role": "warehouse", "permissions": ["mro.view"], "perm_v2": True}
check("konfigurasi yang sudah disimpan (perm_v2) memakai nilai tersimpan apa adanya",
      AC.role_cfg_permissions(saved) == {"mro.view"}, sorted(AC.role_cfg_permissions(saved)))

# Role yang sengaja mencabut semuanya setelah simpan tidak diisi ulang.
saved_empty = {"role": "manager", "permissions": [], "perm_v2": True, "a2_configured": True}
check("pencabutan sengaja tidak dibatalkan migrasi", AC.role_cfg_permissions(saved_empty) == set())

print(("\nSEMUA PASS" if not fail else f"\n{len(fail)} GAGAL -> {fail}"))
sys.exit(1 if fail else 0)
