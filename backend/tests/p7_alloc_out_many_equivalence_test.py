"""P7 — ekuivalensi `alloc_out_many` (batch, endpoint Pull) vs `alloc_out` per baris (referensi, tidak diubah).

Uji in-process murni (tanpa DB/HTTP): `transaction_integrity_layer.install()` dipasang ke server palsu ber-DB memori,
lalu untuk ribuan skenario acak dibandingkan hasil batch vs per baris, termasuk:
  - dokumen hilir aktif / cancelled / canceled / rejected (status & approval_status, huruf besar/kecil + spasi) /
    deleted / yatim (dokumen tidak ada) / Draft & Waiting Approval (tetap mengunci qty);
  - allocation tanpa target_doc_id, qty None/string/float, baris tanpa allocation, id duplikat/kosong di input;
  - pengecualian dokumen yang sedang diedit (source_reservation_layer._EXCLUDE) per target_type;
  - target_type tanpa koleksi (cabang tanpa cek status);
  - batas 5000 allocation per baris (dihitung sebelum pengecualian, sama seperti referensi).
Kriteria: dict batch == {id: alloc_out(id)} persis (termasuk urutan penjumlahan float -> nilai bit-identik).
"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info and not cond else ""))


def _match(doc, flt):
    for k, v in flt.items():
        dv = doc.get(k)
        if isinstance(v, dict) and "$in" in v:
            if dv not in v["$in"]:
                return False
        elif dv != v:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n):
        return [dict(r) for r in (self.rows if n is None else self.rows[:n])]


class _Col:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = 0

    def find(self, flt=None, proj=None):
        self.calls += 1
        return _Cursor([r for r in self.rows if _match(r, flt or {})])  # urutan dasar = urutan sisip (created_at, pk)

    async def find_one(self, flt=None, proj=None):
        r = [x for x in self.rows if _match(x, flt or {})]
        return dict(r[0]) if r else None


class _DB:
    def __init__(self):
        self.cols = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self.cols.setdefault(name, _Col())


class _App:
    class router:  # noqa: N801
        routes = []

    def on_event(self, _):
        return lambda f: f


class _Server:
    def __init__(self):
        self.db = _DB()
        self.app = _App()
        self.current_user = lambda: None


STATUSES = [("Draft", None), ("Waiting Approval", "Waiting Approval"), ("Approved", "Approved"), ("cancelled", None),
            ("Canceled", None), (" Rejected ", None), ("Approved", "rejected"), ("Approved", " REJECTED"), ("Open", None),
            (None, None)]


def build(rnd, srv, n_lines, targets):
    db = srv.db
    db.cols.clear()
    lines = [f"ln-{i}" for i in range(n_lines)]
    docs = {t: [] for t in targets}
    for t in targets:
        for j in range(rnd.randint(0, 12)):
            st, ap = rnd.choice(STATUSES)
            d = {"id": f"{t}-doc-{j}", "status": st}
            if ap is not None:
                d["approval_status"] = ap
            if rnd.random() < 0.1:
                d["cancelled"] = True
            if rnd.random() < 0.08:
                d["deleted"] = True
            if rnd.random() < 0.05:
                d["cancelled"] = "true"  # bukan bool True -> tidak dianggap batal (sama dengan referensi)
            docs[t].append(d)
        db.cols[t] = _Col(docs[t])
    allocs = []
    for k in range(rnd.randint(0, 400)):
        t = rnd.choice(targets + ["xx"])  # "xx": target_type tanpa koleksi
        tid = rnd.choice([d["id"] for d in docs.get(t, [])] + [f"{t}-orphan", None, ""]) if docs.get(t) else \
            rnd.choice([f"{t}-orphan", None, f"{t}-doc-0"])
        q = rnd.choice([1, 2.5, 0.1, 0.2, 0.3, None, "3", 1e-9, 7.0000001, 0])
        allocs.append({"id": f"al-{k}", "source_line_id": rnd.choice(lines + ["ln-other"]), "target_type": t,
                       "target_doc_id": tid, "qty": q})
    db.cols["allocations"] = _Col(allocs)
    return lines, docs


async def run():
    import server  # noqa: F401  — muat modul aplikasi lebih dulu (hindari import melingkar); tanpa koneksi DB
    import transaction_integrity_layer as TIL
    import source_reservation_layer as SR
    srv = _Server()
    TIL.install(srv)
    ref, many = srv.alloc_out, srv.alloc_out_many
    check("T0 install memasang alloc_out & alloc_out_many", callable(ref) and callable(many))

    rnd = random.Random(7)
    targets = ["ro", "po", "do", "mi"]
    bad = 0
    cases = 0
    for it in range(400):
        lines, docs = build(rnd, srv, rnd.randint(1, 25), targets)
        for t in targets + ["xx"]:
            excl_opts = [None] + [d["id"] for d in docs.get(t, [])][:3] + ["tidak-ada"]
            ex = rnd.choice(excl_opts)
            tok = SR._EXCLUDE.set((t, ex) if ex else None) if rnd.random() < 0.7 else \
                SR._EXCLUDE.set((rnd.choice(targets), "ro-doc-0"))  # pengecualian target_type lain -> tidak berlaku
            try:
                inp = rnd.sample(lines, rnd.randint(1, len(lines))) + rnd.choice([[], [None, ""], [lines[0]]])
                try:
                    got = await many(inp, t)
                except Exception as e:  # noqa: BLE001
                    got = e
                exp = {}
                exp_err = None
                for i in dict.fromkeys(inp):
                    if not i:
                        continue
                    try:
                        exp[i] = await ref(i, t)
                    except Exception as e:  # noqa: BLE001
                        exp_err = e
                cases += 1
                if exp_err is not None:
                    ok = isinstance(got, Exception) and type(got) is type(exp_err)
                else:
                    ok = (not isinstance(got, Exception)) and got == exp and \
                        all(repr(got[k]) == repr(exp[k]) and type(got[k]) is type(exp[k]) for k in exp)
                if not ok:
                    bad += 1
                    if bad <= 3:
                        print("  beda:", t, ex, str(got)[:200], "vs", str(exp)[:200], repr(exp_err))
            finally:
                SR._EXCLUDE.reset(tok)
    check(f"T1 {cases} skenario acak: batch == per baris (nilai, tipe, bit float, error)", bad == 0, f"{bad} beda")

    # T2 batas 5000 allocation per baris (sebelum pengecualian) — identik
    srv.db.cols["po"] = _Col([{"id": "po-a", "status": "Approved"}, {"id": "po-b", "status": "Approved"}])
    al = [{"id": f"x{i}", "source_line_id": "L", "target_type": "po", "target_doc_id": "po-a" if i % 2 else "po-b",
           "qty": 1} for i in range(6200)]
    al += [{"id": f"y{i}", "source_line_id": "M", "target_type": "po", "target_doc_id": "po-a", "qty": 0.1} for i in range(300)]
    srv.db.cols["allocations"] = _Col(al)
    for ex in (None, "po-a", "po-b"):
        tok = SR._EXCLUDE.set(("po", ex) if ex else None)
        try:
            g = await many(["L", "M", "N"], "po")
            e = {k: await ref(k, "po") for k in ("L", "M", "N")}
        finally:
            SR._EXCLUDE.reset(tok)
        check(f"T2 batas 5000/baris, exclude={ex}: {g} == {e}", g == e and all(repr(g[k]) == repr(e[k]) for k in e))

    # T3 input kosong / hanya id kosong -> {} tanpa query
    c0 = srv.db.cols["allocations"].calls
    check("T3 input kosong -> {} tanpa query", await many([], "po") == {} and await many([None, ""], "po") == {}
          and srv.db.cols["allocations"].calls == c0)

    # T4 jumlah query batch konstan (<= 2) vs per baris (2 per baris)
    lines, _ = build(random.Random(3), srv, 40, targets)
    a0, p0 = srv.db.cols["allocations"].calls, srv.db.cols["po"].calls
    await many(lines, "po")
    qa, qp = srv.db.cols["allocations"].calls - a0, srv.db.cols["po"].calls - p0
    check(f"T4 batch 40 baris = {qa}+{qp} query (<= 1+1)", qa == 1 and qp <= 1)

    # T5 fungsi referensi tidak diubah (alloc_out per baris tetap dipakai modul procurement/reports)
    import doc_procurement
    import doc_reports
    check("T5 doc_procurement/doc_reports tetap memakai alloc_out per baris (referensi)",
          doc_procurement.alloc_out is ref and doc_reports.alloc_out is ref)


def main():
    asyncio.run(run())
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
