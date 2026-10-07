"""Concurrency: (1) race login Satu Sesi Aktif (token_version) dan (2) race Approve Terpilih Approval 2 PO.

Throwaway tenants (saas/register + receipt_control_test.setup), localhost:8001. Tidak memakai data/user existing,
tidak reset/truncate DB. Request di-overlap memakai threading.Barrier (bukan sleep). Verifikasi akhir langsung ke DB:
approval_tasks, po_approvals, PO.status, audit_logs, attachments (referensi), spk_commitment_ledger, notifications.
"""
import base64
import json
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import requests

import receipt_control_test as T
from po_approval2_batch_test import PNG, mk_user, mk_po, line, task, set_ov

check, call, API = T.check, T.call, T.API
PW = "TestPass123!"
MSG = "Sesi Anda telah berakhir karena akun ini login di perangkat lain."
SESSION_ITER = int(os.environ.get("SESSION_ITER", "15"))
APPROVE_ITER = int(os.environ.get("APPROVE_ITER", "6"))
REPORT = {}


def dbc():
    env = {}
    for ln in open(os.path.join(os.path.dirname(__file__), "..", ".env")):
        if "=" in ln and not ln.startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v.strip().strip('"')
    u = urlparse(env.get("DATABASE_URL", ""))
    import pymysql
    return pymysql.connect(host=u.hostname or "127.0.0.1", port=u.port or 3306, user=unquote(u.username or ""),
                           password=unquote(u.password or ""), database=(u.path or "/").lstrip("/"), autocommit=True)


def q1(sql, args=()):
    con = dbc()
    try:
        with con.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    finally:
        con.close()


def jwt_ver(tok):
    p = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("ver")


def me(tok):
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def register(prefix):
    u = uuid.uuid4().hex[:8]
    email = f"{prefix}_{u}@example.com"
    r = requests.post(f"{API}/saas/register", json={"company_name": f"CC {u}", "pic_name": "QA", "email": email, "whatsapp": "+628123456789",
                                                  "workspace_slug": f"{prefix}-{u}", "plan_code": "starter", "password": PW,
                                                  "address": "x", "terms_accepted": True})
    return email, r.status_code


def race_logins(email, n):
    bar = threading.Barrier(n)

    def go(_):
        bar.wait()
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": PW})
        return r.status_code, (r.json().get("token") if r.status_code == 200 else None)
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(go, range(n)))


# ============================================================ 1. Single active session race
def session_race():
    email, sc = register("ccs")
    check("S0. Registrasi tenant uji (race sesi)", sc == 200, sc)
    other_email, sc = register("cco")
    check("S0. Registrasi tenant lain (kontrol)", sc == 200, sc)
    r = requests.post(f"{API}/auth/login", json={"email": other_email, "password": PW})
    other_tok = r.json().get("token")
    # user lain di tenant yang sama
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PW})
    owner_tok = r.json().get("token")
    peer_email = f"ccp_{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(f"{API}/users", json={"email": peer_email, "password": PW, "name": "QA Peer", "role": "manager"},
                      headers={"Authorization": f"Bearer {owner_tok}"})
    check("S0. User lain (tenant sama) dibuat", r.status_code == 200, (r.status_code, r.text[:200]))
    peer_tok = requests.post(f"{API}/auth/login", json={"email": peer_email, "password": PW}).json().get("token")
    peer_ver0 = q1("SELECT token_version FROM users WHERE email=%s", (peer_email,))[0][0]
    other_ver0 = q1("SELECT token_version FROM users WHERE email=%s", (other_email,))[0][0]

    fails, all_tokens = [], [owner_tok]
    for it in range(SESSION_ITER):
        n = 2 if it % 3 else 3  # sebagian iterasi 3 klien sekaligus
        res = race_logins(email, n)
        toks = [t for s, t in res if s == 200 and t]
        all_tokens += toks
        dbver = int(q1("SELECT token_version FROM users WHERE email=%s", (email,))[0][0])
        vers = [jwt_ver(t) for t in toks]
        valid = [t for t in toks if me(t)[0] == 200]
        stale = [t for t in toks if t not in valid]
        stale_ok = all(me(t) == (401, {"detail": MSG}) for t in stale)
        ok = (len(toks) == n and len(set(vers)) == n and max(vers) == dbver and len(valid) == 1
              and jwt_ver(valid[0]) == dbver and stale_ok)
        if not ok:
            fails.append({"iter": it, "status": [s for s, _ in res], "vers": vers, "db": dbver, "valid": len(valid)})
    check(f"S1. {SESSION_ITER} iterasi race login: semua login sukses, versi unik (inc atomik), hanya token versi terbaru valid",
          not fails, fails[:3])
    final_ver = int(q1("SELECT token_version FROM users WHERE email=%s", (email,))[0][0])
    valid_all = [t for t in all_tokens if me(t)[0] == 200]
    check("S2. Setelah seluruh race: tepat 1 generasi sesi aktif (token lama tidak kembali valid)",
          len(valid_all) == 1 and jwt_ver(valid_all[0]) == final_ver, (len(valid_all), final_ver))
    sc, body = me(owner_tok)
    check("S3. Token lama (sebelum race) -> 401 dengan pesan sesi digantikan", sc == 401 and body.get("detail") == MSG, (sc, body))
    check("S4. User lain di tenant sama tidak terpengaruh",
          me(peer_tok)[0] == 200 and q1("SELECT token_version FROM users WHERE email=%s", (peer_email,))[0][0] == peer_ver0)
    check("S5. User tenant lain tidak terpengaruh",
          me(other_tok)[0] == 200 and q1("SELECT token_version FROM users WHERE email=%s", (other_email,))[0][0] == other_ver0)
    REPORT["session"] = {"iterations": SESSION_ITER, "final_token_version": final_ver, "active_tokens": len(valid_all),
                         "logins_total": len(all_tokens) - 1}


# ============================================================ 2. Approval 2 approve race
def approval_race():
    M = T.setup()
    a1, a2 = mk_user("cl1", [M["div"]["id"]]), mk_user("cl2", [M["div"]["id"]])
    call("PUT", "settings/approval_modules", {"modules": {
        "mro": {"enabled": False, "levels": []}, "ro": {"enabled": False, "levels": []},
        "po": {"enabled": True, "levels": [{"level": 1, "email": a1.email}, {"level": 2, "email": a2.email}]}}}, 200)
    n_po = APPROVE_ITER + 2  # +2 untuk race himpunan tumpang-tindih (urutan berbeda)
    pos = [mk_po(M, [line(M, "item", 1, 1000 * (i + 1))]) for i in range(n_po)]
    for p in pos:
        call("POST", f"po/{p['id']}/submit", {}, 200)
        t = task(a1, p["id"], 1)
        a1("POST", f"approvals/{t['id']}/approve", {"note": "L1 OK"})
    tids = [task(a2, p["id"], 2)["id"] for p in pos]
    check("A0. Level 2 Pending untuk semua PO uji", all(tids), len(tids))
    set_ov(a2, {"upload_attachment": "allow"})
    sc, B = a2("POST", "approval2/po/batches", {"title": "Race Approve", "submission_date": "2026-10-06", "approval_task_ids": tids})
    check("A0. Batch berisi beberapa PO dibuat", sc == 200 and B.get("po_count") == n_po, (sc, B.get("po_count") if isinstance(B, dict) else B))
    bid = B["id"]
    sc, d = a2("POST", f"approval2/po/batches/{bid}/submit", {})
    sc, ev = a2.upload("po_approval2_batch", bid, "wa-approval.png", PNG, "image/png")
    check("A0. Export + bukti diunggah", sc == 200 and ev.get("id"), (sc, ev))
    items = {i["po_id"]: i["id"] for i in d.get("items") or []}
    tenant_id = call("GET", "auth/me")[1].get("tenant_id")

    def race(item_sets, n):
        bar = threading.Barrier(n)

        def go(k):
            bar.wait()
            return a2("POST", f"approval2/po/batches/{bid}/approve", {"item_ids": item_sets[k % len(item_sets)]})
        with ThreadPoolExecutor(n) as ex:
            return list(ex.map(go, range(n)))

    fails = []
    for i in range(APPROVE_ITER):
        n = 2 if i % 2 == 0 else 4
        res = race([[items[pos[i]["id"]]]], n)
        codes = [r[0] for r in res]
        if codes.count(200) != 1 or any(c not in (200, 409) for c in codes):
            fails.append({"iter": i, "codes": codes})
    check(f"A1. {APPROVE_ITER} iterasi Approve Terpilih paralel (2-4 request/PO yang sama): tepat 1 menang, sisanya 409",
          not fails, fails)
    # himpunan tumpang-tindih urutan terbalik: lock terurut -> tidak deadlock, tetap 1 menang
    x, y = items[pos[-2]["id"]], items[pos[-1]["id"]]
    res = race([[x, y], [y, x]], 2)
    codes = [r[0] for r in res]
    check("A2. Race himpunan [x,y] vs [y,x]: tidak deadlock, tepat 1 menang (atomik, tanpa approve sebagian)",
          codes.count(200) == 1 and all(c in (200, 409) for c in codes), codes)

    # ---- verifikasi DB per PO
    bad, audit_n, ref_n, notif_total = [], 0, 0, 0
    for p in pos:
        pid = p["id"]
        tasks = q1("SELECT seq, status FROM approval_tasks WHERE document_id=%s AND module='po' ORDER BY seq", (pid,))
        pa = q1("SELECT seq, status FROM po_approvals WHERE po_id=%s ORDER BY seq", (pid,))
        st = q1("SELECT status FROM po WHERE id=%s", (pid,))[0][0]
        a_l2 = q1("SELECT COUNT(*) FROM audit_logs WHERE entity='po' AND entity_id=%s AND action='approval2_batch_approve'", (pid,))[0][0]
        a_ap = q1("SELECT COUNT(*) FROM audit_logs WHERE entity='po' AND entity_id=%s AND action='approve'", (pid,))[0][0]
        refs = q1("SELECT COUNT(*) FROM attachments WHERE entity='po' AND entity_id=%s AND category='Bukti Approval 2'", (pid,))[0][0]
        spk = q1("SELECT COUNT(*) FROM spk_commitment_ledger WHERE doc LIKE %s", (f"%{pid}%",))[0][0]
        nt = q1("SELECT COUNT(*) FROM notifications WHERE message=%s AND doc LIKE %s", (f"{p.get('no')} approved", f"%{tenant_id}%"))[0][0]
        notif_total += nt
        it_st = q1("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.status')) FROM po_approval2_batch_items WHERE id=%s", (items[pid],))[0][0]
        audit_n += a_l2
        ref_n += refs
        ok = ([s for _, s in tasks] == ["Approved", "Approved"] and len(pa) == 2 and [s for _, s in pa] == ["Approved", "Approved"]
              and st == "Approved" and a_l2 == 1 and a_ap == 2 and refs == 1 and spk <= 1 and it_st == "Approved" and nt == 1)
        if not ok:
            bad.append({"po": p.get("no"), "tasks": tasks, "po_approvals": pa, "status": st, "audit_l2": a_l2, "audit_approve": a_ap,
                        "refs": refs, "spk": spk, "item": it_st, "notif": nt})
    check("A3. approval_tasks: tepat 1 transisi Pending->Approved per Level (L1+L2 Approved, tanpa duplikat)", not bad, bad[:3])
    check("A4. po_approvals tidak duplikat; PO.status Approved sekali; audit approval2_batch_approve = 1 per PO", not bad)
    check("A5. Lampiran referensi bukti = 1 per PO; notifikasi 'approved' = 1 per PO; tidak ada side effect SPK ganda", not bad)
    bstat = q1("SELECT JSON_UNQUOTE(JSON_EXTRACT(doc,'$.status')) FROM po_approval2_batches WHERE id=%s", (bid,))[0][0]
    bulk = q1("SELECT COUNT(*) FROM audit_logs WHERE entity='po_approval2_batch' AND entity_id=%s AND action='bulk_approve'", (bid,))[0][0]
    check("A6. Status batch Selesai & jumlah audit bulk_approve = jumlah request yang menang", bstat == "Selesai" and bulk == APPROVE_ITER + 1, (bstat, bulk))
    REPORT["approval"] = {"iterations": APPROVE_ITER + 1, "po_count": n_po, "task_status_final": "Approved" if not bad else "MISMATCH",
                          "audit_approval2_batch_approve": audit_n, "attachment_refs": ref_n, "batch_status": bstat,
                          "bulk_approve_audit": bulk, "approved_notifications": notif_total}


def main():
    session_race()
    approval_race()
    passed = sum(1 for _, ok in T.RESULTS if ok)
    print("\nREPORT:", json.dumps(REPORT, indent=1))
    print(f"\n{passed}/{len(T.RESULTS)} passed")
    sys.exit(0 if passed == len(T.RESULTS) else 1)


if __name__ == "__main__":
    main()
