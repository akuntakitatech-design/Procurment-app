"""Inline Tambah Project & Unit/Aset dari form transaksi — backend tetap lewat Master existing.

Throwaway tenant. Memverifikasi: izin projects.create / units.create (403 tanpa izin, view tetap bisa memilih),
validasi duplikat & wajib Master existing, scope Divisi Unit/Aset, transaksi menyimpan referensi id
(tetap resolve setelah nama master diubah), dan isolasi tenant.
"""
import sys
import uuid

import requests

import receipt_control_test as T
from po_approval2_batch_test import mk_user, set_ov

call, check, API = T.call, T.check, T.API


def detail(r):
    return str((r or {}).get("detail") if isinstance(r, dict) else r)


def main():
    M = T.setup()
    sc, div2 = call("POST", "master/divisions", {"code": f"D2{uuid.uuid4().hex[:5]}", "name": "Divisi Lain"}, 200)
    d1 = [M["div"]["id"]]
    maker, viewer = mk_user("imk", d1), mk_user("ivw", d1)
    set_ov(maker, {"projects.view": "allow", "projects.create": "allow", "units.view": "allow", "units.create": "allow",
                   "mro.view": "allow", "mro.create": "allow", "mro.edit": "allow"})
    set_ov(viewer, {"projects.view": "allow", "projects.create": "deny", "units.view": "allow", "units.create": "deny"})

    # --- Project ---
    sc, p = maker("POST", "master/projects", {"name": "Project Inline UAT", "pic": "Budi"})
    check("1. projects.create: Tambah Project -> 200, kode otomatis PRJ", sc == 200 and str(p.get("code", "")).startswith("PRJ") and p.get("id"), (sc, p))
    sc, lk = maker("GET", "lookup/projects")
    check("1. Project baru langsung tersedia di lookup (dropdown refresh)", sc == 200 and any(x["id"] == p.get("id") for x in lk), sc)
    sc, r = viewer("POST", "master/projects", {"name": "Tidak Boleh"})
    check("2. tanpa projects.create: direct API -> 403", sc == 403, (sc, r))
    sc, lk = viewer("GET", "lookup/projects")
    check("2. tanpa projects.create: Project existing tetap bisa dipilih (lookup 200)", sc == 200 and any(x["id"] == p.get("id") for x in lk), sc)
    sc, r = maker("POST", "master/projects", {"code": p.get("code"), "name": "Duplikat"})
    check("3. Duplicate kode Project -> 400 (validasi master existing)", sc == 400 and "sudah dipakai" in detail(r), (sc, r))
    sc, r = maker("POST", "master/projects", {"name": ""})
    check("3. Project tanpa Nama -> 400 'Wajib diisi: Nama Proyek'", sc == 400 and "Nama Proyek" in detail(r), (sc, r))
    sc, r = call("PUT", f"master/projects/{p['id']}", {"pic": "Andi"})
    check("3. Edit parsial Project (tanpa kirim Nama) tetap 200 — nama lama dipakai", sc == 200 and r.get("name") == "Project Inline UAT", (sc, r))
    sc, r = call("PUT", f"master/projects/{p['id']}", {"name": "  "})
    check("3. Edit Project mengosongkan Nama -> 400", sc == 400 and "Nama Proyek" in detail(r), (sc, r))

    # --- Unit / Aset ---
    sc, u = maker("POST", "master/units", {"name": "Excavator Inline", "plate_no": "BM 1234 XY", "division_id": d1[0]})
    check("4. units.create: Tambah Unit -> 200 (divisi dalam scope)", sc == 200 and u.get("id") and u.get("division_id") == d1[0], (sc, u))
    sc, lk = maker("GET", "lookup/units")
    check("4. Unit baru langsung tersedia di lookup", sc == 200 and any(x["id"] == u.get("id") for x in lk), sc)
    sc, r = viewer("POST", "master/units", {"name": "Tidak Boleh"})
    check("5. tanpa units.create: direct API -> 403", sc == 403, (sc, r))
    sc, lk = viewer("GET", "lookup/units")
    check("5. tanpa units.create: Unit existing tetap bisa dipilih", sc == 200 and any(x["id"] == u.get("id") for x in lk), sc)
    sc, r = maker("POST", "master/units", {"name": "Di Luar Scope", "division_id": div2["id"]})
    check("6. Unit dengan Divisi di luar scope user -> 403", sc == 403 and "cakupan divisi" in detail(r), (sc, r))
    sc, r = maker("POST", "master/units", {"code": u.get("code"), "name": "Duplikat"})
    check("6. Duplicate kode Unit -> 400", sc == 400 and "sudah dipakai" in detail(r), (sc, r))
    sc, r = maker("POST", "master/units", {"name": ""})
    check("6. Unit tanpa Nama -> 400 'Wajib diisi: Nama Unit'", sc == 400 and "Nama Unit" in detail(r), (sc, r))

    # --- Transaksi menyimpan referensi master ---
    it = M["item"]["id"]
    body = {"no": f"MRO-INL-{uuid.uuid4().hex[:5]}", "division_id": d1[0], "requester": "QA", "default_project_id": p["id"], "default_unit_id": u["id"],
            "lines": [{"item_id": it, "qty": 1, "warehouse_id": M["wh"]["id"], "project_id": p["id"], "unit_id": u["id"]},
                      {"item_id": it, "qty": 2, "warehouse_id": M["wh"]["id"], "project_id": M["pa"]["id"]}]}
    sc, mro = maker("POST", "mro", body)
    check("7. MRO dengan Project/Unit baru tersimpan", sc == 200 and mro.get("id"), (sc, mro))
    sc, g = maker("GET", f"mro/{mro.get('id')}")
    ls = g.get("lines") or []
    check("7. Reload: header menyimpan project_id/unit_id master", g.get("default_project_id") == p["id"] and g.get("default_unit_id") == u["id"], g.get("default_project_id"))
    check("7. Reload: baris 1 = Project/Unit baru, baris 2 tetap Project lain (tidak tertimpa)", len(ls) == 2 and ls[0].get("project_id") == p["id"] and ls[0].get("unit_id") == u["id"] and ls[1].get("project_id") == M["pa"]["id"], [(x.get("project_id"), x.get("unit_id")) for x in ls])
    sc, _ = call("PUT", f"master/projects/{p['id']}", {**p, "name": "Project Inline UAT (Rename)"}, 200)
    sc, g2 = maker("GET", f"mro/{mro.get('id')}")
    sc, lk = maker("GET", "lookup/projects")
    nm = {x["id"]: x.get("name") for x in lk}
    check("8. Setelah rename master, transaksi tetap mereferensikan id yang sama & resolve nama baru", (g2.get("lines") or [{}])[0].get("project_id") == p["id"] and nm.get(p["id"]) == "Project Inline UAT (Rename)", nm.get(p["id"]))
    check("8. Tidak ada string bebas: project_id baris = id master (bukan nama)", all(x.get("project_id") in nm for x in g2.get("lines") or []))

    # --- Isolasi tenant ---
    ub = uuid.uuid4().hex[:8]
    s = requests.Session()
    r = s.post(f"{API}/saas/register", json={"company_name": f"ISO {ub}", "pic_name": "QA", "email": f"iso_{ub}@example.com", "whatsapp": "+628123456789",
                                            "workspace_slug": f"iso-{ub}", "plan_code": "starter", "password": f"Iso-{ub}!9", "address": "x", "terms_accepted": True})
    tok = r.json().get("token") or s.post(f"{API}/auth/login", json={"email": f"iso_{ub}@example.com", "password": f"Iso-{ub}!9"}).json().get("token")
    s.headers["Authorization"] = f"Bearer {tok}"
    lkB = s.get(f"{API}/lookup/projects").json()
    check("9. Tenant lain tidak melihat Project tenant A", r.status_code == 200 and not any(x.get("id") == p["id"] for x in lkB), r.status_code)
    lkB = s.get(f"{API}/lookup/units").json()
    check("9. Tenant lain tidak melihat Unit tenant A", not any(x.get("id") == u["id"] for x in lkB))
    rB = s.post(f"{API}/master/projects", json={"code": p["code"], "name": "Kode sama tenant B"})
    check("9. Kode Project sama di tenant lain tidak bentrok (uniqueness per tenant)", rB.status_code == 200, (rB.status_code, rB.text[:120]))
    rB = s.put(f"{API}/master/projects/{p['id']}", json={"name": "Hijack"})
    check("9. Tenant lain tidak dapat mengubah Project tenant A", rB.status_code in (403, 404), rB.status_code)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    return 0 if passed == len(T.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
