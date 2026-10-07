"""Dokumen Supplier via attachment engine existing (entity=supplier). Throwaway tenant."""
import sys
import uuid

import requests

import receipt_control_test as T
from po_approval2_batch_test import U, PNG, mk_user, set_ov

call, check, API = T.call, T.check, T.API
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def up(sess_headers, sid, name, data, ctype, category, note=""):
    r = requests.post(f"{API}/attachments", headers=sess_headers, files={"file": (name, data, ctype)},
                      data={"entity": "supplier", "entity_id": sid, "category": category, "note": note})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def main():
    M = T.setup()
    H = {"Authorization": T.S.headers["Authorization"]}
    sid = M["supX"]["id"]
    sc, npwp = up(H, sid, "npwp.pdf", PDF, "application/pdf", "NPWP", "NPWP badan")
    check("Upload NPWP berhasil", sc == 200 and npwp.get("category") == "NPWP" and npwp.get("note") == "NPWP badan", (sc, npwp))
    check("Respons tidak membuka storage_path / binary", "storage_path" not in npwp and "data" not in npwp, list(npwp))
    sc, ktp = up(H, sid, "ktp-direktur.png", PNG, "image/png", "KTP", "KTP Direktur")
    check("Upload KTP berhasil", sc == 200 and ktp.get("category") == "KTP", (sc, ktp))
    sc, kon = up(H, sid, "kontrak.pdf", PDF, "application/pdf", "Kontrak")
    check("Upload kategori lain (Kontrak) berhasil", sc == 200 and kon.get("category") == "Kontrak", (sc, kon))
    sc, r = up(H, sid, "x.pdf", PDF, "application/pdf", "Kategori Ngawur")
    check("Kategori tidak valid ditolak", sc == 400, (sc, r))
    sc, r = up(H, str(uuid.uuid4()), "x.pdf", PDF, "application/pdf", "NPWP")
    check("Supplier tidak ada -> 404", sc == 404, (sc, r))

    sc, rows = call("GET", f"attachments?entity=supplier&entity_id={sid}")
    names = {x["original_filename"]: x for x in rows or []}
    check("Setelah reload: 3 dokumen tampil", sc == 200 and {"npwp.pdf", "ktp-direktur.png", "kontrak.pdf"} <= set(names), (sc, list(names)))
    check("Kategori & catatan tersimpan", names.get("npwp.pdf", {}).get("note") == "NPWP badan" and names.get("ktp-direktur.png", {}).get("category") == "KTP")
    check("Tanggal upload & pengunggah tercatat", all(names[n].get("created_at") and names[n].get("uploaded_by") for n in names))
    r = T.S.get(f"{API}/attachments/{npwp['id']}/download")
    check("Download dokumen supplier", r.status_code == 200 and r.content == PDF, r.status_code)
    sc, _ = call("GET", f"attachments?entity=supplier&entity_id={M['supY']['id']}")
    check("Dokumen supplier lain terpisah (kosong)", sc == 200 and _ == [], _)

    # user tanpa hak akses Supplier
    noacc = mk_user("noacc", [M["div"]["id"]])
    set_ov(noacc, {"suppliers.view": "deny", "suppliers.edit": "deny"})
    sc, _ = noacc("GET", f"attachments?entity=supplier&entity_id={sid}")
    check("User tanpa akses Supplier tidak bisa membaca daftar (403)", sc == 403, sc)
    r = noacc.S.get(f"{API}/attachments/{npwp['id']}/download")
    check("User tanpa akses Supplier tidak bisa download via URL langsung (403)", r.status_code == 403, r.status_code)
    viewer = mk_user("supview", [M["div"]["id"]])
    set_ov(viewer, {"suppliers.view": "allow", "suppliers.edit": "deny", "upload_attachment": "allow"})
    sc, rows_v = viewer("GET", f"attachments?entity=supplier&entity_id={sid}")
    check("User dengan suppliers.view dapat membaca", sc == 200 and len(rows_v) == 3, sc)
    sc, r = up(dict(viewer.S.headers), sid, "v.pdf", PDF, "application/pdf", "NPWP")
    check("User tanpa suppliers.edit tidak bisa upload (403)", sc == 403, (sc, r))
    sc, _ = viewer("DELETE", f"attachments/{ktp['id']}")
    check("User tanpa suppliers.edit tidak bisa delete (403)", sc == 403, sc)
    set_ov(viewer, {"suppliers.view": "allow", "suppliers.edit": "allow", "upload_attachment": "deny"})
    sc, r = up(dict(viewer.S.headers), sid, "v.pdf", PDF, "application/pdf", "NPWP")
    check("User tanpa upload_attachment tidak bisa upload (403)", sc == 403, (sc, r))

    # tenant lain
    ten = requests.Session(); u = uuid.uuid4().hex[:8]
    r = ten.post(f"{API}/saas/register", json={"company_name": f"SD {u}", "pic_name": "QA", "email": f"sd_{u}@example.com",
                                             "whatsapp": "+628123456789", "workspace_slug": f"sd-{u}", "plan_code": "starter",
                                             "password": "TestPass123!", "address": "x", "terms_accepted": True})
    tok = r.json().get("token") or ten.post(f"{API}/auth/login", json={"email": f"sd_{u}@example.com", "password": "TestPass123!"}).json().get("token")
    ten.headers.update({"Authorization": f"Bearer {tok}"})
    check("Tenant lain login valid", ten.get(f"{API}/auth/me").status_code == 200)
    r = ten.get(f"{API}/attachments", params={"entity": "supplier", "entity_id": sid})
    check("Tenant lain tidak bisa membaca daftar dokumen", r.status_code == 404, r.status_code)
    r = ten.get(f"{API}/attachments/{npwp['id']}/download")
    check("Tenant lain tidak bisa download dokumen", r.status_code == 404, r.status_code)
    r = ten.delete(f"{API}/attachments/{npwp['id']}")
    sc_after, rows2 = call("GET", f"attachments?entity=supplier&entity_id={sid}")
    check("Tenant lain tidak bisa menghapus dokumen", npwp["id"] in {x["id"] for x in rows2}, r.status_code)
    sc, r = up(dict(ten.headers), sid, "t.pdf", PDF, "application/pdf", "NPWP")
    check("Tenant lain tidak bisa upload ke supplier tenant ini", sc in (403, 404), (sc, r))

    # soft delete
    sc, _ = call("DELETE", f"attachments/{ktp['id']}")
    check("Soft delete dokumen KTP", sc == 200, sc)
    sc, rows3 = call("GET", f"attachments?entity=supplier&entity_id={sid}")
    ids3 = {x["id"] for x in rows3}
    check("KTP hilang dari daftar, dokumen lain tetap", ktp["id"] not in ids3 and {npwp["id"], kon["id"]} <= ids3, ids3)
    r = T.S.get(f"{API}/attachments/{ktp['id']}/download")
    check("Dokumen terhapus tidak bisa diunduh", r.status_code == 404, r.status_code)
    r = T.S.get(f"{API}/attachments/{npwp['id']}/download")
    check("File attachment lain tetap utuh setelah soft delete", r.status_code == 200 and r.content == PDF, r.status_code)
    sc, logs = call("GET", f"audit?entity=supplier&entity_id={sid}")
    acts = {x.get("action") for x in (logs if isinstance(logs, list) else [])}
    check("Audit upload & delete dokumen supplier", {"upload_supplier_document", "delete_supplier_document"} <= acts, acts)

    passed = sum(1 for _, ok in T.RESULTS if ok)
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
