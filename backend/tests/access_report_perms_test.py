"""Uji izin Pusat Laporan per-laporan (`report.<key>`).

Yang dijaga:
- Setiap laporan katalog punya kunci `report.<key>` yang dikenal (bisa muncul di UI & disimpan).
- Default role dan migrasi `perm_v3` menghasilkan set yang SAMA dengan aturan lama, sehingga tidak ada
  laporan yang tiba-tiba hilang saat rilis.
- Setelah role disimpan dari UI (`perm_v3`), pencabutan yang disengaja dipertahankan.
- Laporan yang tidak dicentang tidak muncul di katalog dan tidak bisa dibuka (403).
- Laporan non-katalog (export daftar transaksi/master) tetap memakai aturan lama.
- Laporan valuasi tetap mensyaratkan `view_purchase_price`.

Registry asli baru terisi saat bootstrap (`report_center.install`), jadi tes ini mendaftarkan laporan
contoh untuk menguji logika katalog/penegakan tanpa menyalakan server.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import access_control_layer as AC  # noqa: E402
import reporting.registry as R  # noqa: E402
from reporting.registry import ReportSpec, register  # noqa: E402
from reporting.report_center import report_allowed  # noqa: E402

fail = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info not in ("", None) else ""))
    if not ok:
        fail.append(name)


async def _builder(server, user, params):  # tidak dipanggil di tes
    return []


def spec(key, group="persediaan", perm="view", catalog=True):
    return register(ReportSpec(key=key, group=group, title=f"Laporan {key}", description="contoh",
                               columns=(), builder=_builder, permission=perm, catalog=catalog))


# --- fixture tiga laporan katalog + satu non-katalog (export daftar transaksi)
if "t-view" not in R.REGISTRY:
    spec("t-view")
    spec("t-ap", group="hutang", perm="invoice.view")
    spec("t-val", perm="view_purchase_price")
    spec("t-export", group="hutang", perm="export", catalog=False)

# --- 1. kunci izin
check("format kunci report.<key>", AC.report_perm("t-view") == "report.t-view", AC.report_perm("t-view"))
check("report_specs hanya laporan katalog", {s.key for s in AC.report_specs()} == {"t-view", "t-ap", "t-val"},
      sorted(s.key for s in AC.report_specs()))
check("known_keys memuat kunci per-laporan",
      {"report.t-view", "report.t-ap", "report.t-val"} <= AC.known_keys(), sorted(AC.known_keys())[-5:])
check("laporan non-katalog tidak dapat kunci per-laporan", "report.t-export" not in AC.known_keys())
check("known_keys tetap memuat izin modul lama", "po.view" in AC.known_keys() and "report_center.view" in AC.known_keys())

# --- 2. default per role = aturan lama
check("role hanya view -> 1 laporan default",
      AC.report_default_keys({"mro.view"}) == {"report.t-view"}, sorted(AC.report_default_keys({"mro.view"})))
check("role dengan invoice.view -> ikut laporan AP",
      AC.report_default_keys({"mro.view", "invoice.view"}) == {"report.t-view", "report.t-ap"})
check("role dengan view_purchase_price -> ikut laporan valuasi",
      AC.report_default_keys({"mro.view", "invoice.view", "view_purchase_price"}) ==
      {"report.t-view", "report.t-ap", "report.t-val"})
check("tanpa izin baca (.view) -> tidak ada laporan", AC.report_default_keys({"export"}) == set())

# --- 3. migrasi perm_v3 (konfigurasi tersimpan)
_cfg_lama = {"role": "warehouse", "permissions": ["mro.view"], "perm_v2": True}
_mig = AC.role_cfg_permissions(_cfg_lama)
check("migrasi role lama memberi laporan yang sebelumnya terlihat", "report.t-view" in _mig, sorted(k for k in _mig if k.startswith("report.")))
check("migrasi tidak memberi laporan AP tanpa invoice.view", "report.t-ap" not in _mig)
check("migrasi tidak memberi laporan valuasi tanpa izin harga", "report.t-val" not in _mig)

_cfg_baru = {"role": "warehouse", "permissions": ["mro.view"], "perm_v2": True, "perm_v3": True}
check("setelah disimpan dari UI (perm_v3) pencabutan dipertahankan", "report.t-view" not in AC.role_cfg_permissions(_cfg_baru))
_cfg_pilih = {"role": "warehouse", "permissions": ["mro.view", "report.t-ap"], "perm_v2": True, "perm_v3": True}
check("setelah perm_v3 pilihan admin yang berlaku", "report.t-ap" in AC.role_cfg_permissions(_cfg_pilih))

# --- 4. penegakan katalog & buka laporan
class Srv:
    def __init__(self, *perms):
        self.perms = set(perms)

    def has_perm(self, user, key):
        return key in self.perms


check("dicentang -> laporan boleh", report_allowed(Srv("report.t-view"), {}, R.REGISTRY["t-view"]) is True)
check("tidak dicentang -> laporan ditolak", report_allowed(Srv(), {}, R.REGISTRY["t-view"]) is False)
check("valuasi tanpa izin harga -> ditolak",
      report_allowed(Srv("report.t-val"), {}, R.REGISTRY["t-val"]) is False)
check("valuasi dengan izin harga -> boleh",
      report_allowed(Srv("report.t-val", "view_purchase_price"), {}, R.REGISTRY["t-val"]) is True)
check("non-katalog tetap pakai izin lama (export)",
      report_allowed(Srv("export"), {}, R.REGISTRY["t-export"]) is True and
      report_allowed(Srv("report.t-export"), {}, R.REGISTRY["t-export"]) is False)
check("laporan tidak dikenal -> ditolak", report_allowed(Srv("report.t-view"), {}, None) is False)

# --- 5. katalog UI: grup + label tersedia
_groups = AC.report_groups()
check("grup laporan lengkap (5)", len(_groups) == 5, [g["key"] for g in _groups])
check("semua laporan katalog punya grup valid",
      {s.group for s in AC.report_specs()} <= {g["key"] for g in _groups},
      sorted({s.group for s in AC.report_specs()}))
check("label grup terisi", all(g["label"] for g in _groups))

print()
if fail:
    print(f"GAGAL: {len(fail)} -> {fail}")
    sys.exit(1)
print("SEMUA PASS")
