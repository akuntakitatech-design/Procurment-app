"""Unit test cascade pembatalan PO -> RO -> MRO (fake DB, tanpa jaringan/DB sungguhan).

Menguji `backend/po_cancel_cascade_layer.py`:
- PO batal: alokasi RO->PO dilepas, RO dibatalkan bila tidak ada PO aktif lain,
  MRO dibatalkan bila seluruh RO-nya batal dan tidak ada MI.
- RO yang masih dipakai PO aktif lain TIDAK dibatalkan (begitu juga MRO-nya).
- MRO dengan MI aktif TIDAK dibatalkan.
- Reject approver = PO batal final (status Cancelled) + cascade + pelepasan komitmen SPK.
- Idempoten (dijalankan dua kali tidak menggandakan audit/notifikasi).

Jalankan: backend/.venv/Scripts/python.exe tests/po_cancel_cascade_unit_test.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import po_cancel_cascade_layer as C  # noqa: E402
from po_revision_unit_test import Coll, Server, check, FAILS  # noqa: E402

USER = {"id": "u1", "name": "Sari", "email": "sari@test", "role": "purchasing",
        "divisions": ["div1"], "permissions": ["cancel", "reject"]}
RUN = lambda coro: asyncio.get_event_loop().run_until_complete(coro)  # noqa: E731


def build(po_status="Cancelled", extra_po=None, mi_status=None):
    s = Server()
    s.db.ro = Coll()
    s.db.ro_lines = Coll()
    s.db.mro = Coll()
    s.db.mi = Coll()
    s.db.po.rows.append({"id": "po1", "no": "PO/1", "status": po_status, "approval_status": po_status,
                         "division_id": "div1", "cancelled": po_status in ("Cancelled",), "grand_total": 1000})
    s.db.ro.rows.append({"id": "ro1", "no": "RO/1", "cancelled": False, "submitted": True,
                         "division_id": "div1"})
    s.db.ro_lines.rows.append({"id": "rl1", "ro_id": "ro1", "qty": 10})
    s.db.mro.rows.append({"id": "m1", "no": "MRO/1", "cancelled": False, "submitted": True,
                          "division_id": "div1"})
    s.db.allocations.rows.append({"source_type": "ro", "source_line_id": "rl1", "source_doc_id": "ro1",
                                  "target_type": "po", "target_line_id": "pl1", "target_doc_id": "po1", "qty": 10})
    s.db.allocations.rows.append({"source_type": "mro", "source_line_id": "ml1", "source_doc_id": "m1",
                                  "target_type": "ro", "target_line_id": "rl1", "target_doc_id": "ro1", "qty": 10})
    if extra_po:
        s.db.allocations.rows.append({"source_type": "ro", "source_line_id": "rl1", "source_doc_id": "ro1",
                                      "target_type": "po", "target_line_id": "pl2", "target_doc_id": "po2", "qty": 5})
    if mi_status:
        s.db.mi.rows.append({"id": "mi1", "no": "MI/1", "status": mi_status, "cancelled": False})
        s.db.allocations.rows.append({"source_type": "mro", "source_line_id": "ml1", "source_doc_id": "m1",
                                      "target_type": "mi", "target_line_id": "mil1", "target_doc_id": "mi1", "qty": 2})
    return s


def po(s): return s.db.po.rows[0]
def ro(s): return s.db.ro.rows[0]
def mro(s): return s.db.mro.rows[0]
def po_alloc(s): return [a for a in s.db.allocations.rows if a.get("target_doc_id") == "po1"]


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())

    # 1) satu PO, satu RO, satu MRO -> semuanya batal
    s = build()
    info = RUN(C.cascade(s, "po1", USER, "PO PO/1 dibatalkan"))
    check("cascade: alokasi PO dilepas", po_alloc(s) == [] and info["allocations_released"] == 1, info)
    check("cascade: RO dibatalkan", ro(s)["cancelled"] is True and info["ro_cancelled"] == ["RO/1"], info)
    check("cascade: MRO dibatalkan", mro(s)["cancelled"] is True and info["mro_cancelled"] == ["MRO/1"], info)
    check("cascade: alasan tersimpan", "dibatalkan" in (ro(s).get("auto_cancel_reason") or ""), ro(s))
    check("cascade: audit RO+MRO", sorted(a["args"][1] for a in s.audits) == ["auto_cancel_source", "auto_cancel_source"],
          [a["args"][1] for a in s.audits])
    check("cascade: 2 notifikasi", len(s.notifs) == 2, len(s.notifs))

    # 2) RO masih dipakai PO aktif lain -> RO & MRO TIDAK dibatalkan
    s2 = build(extra_po=True)
    s2.db.po.rows.append({"id": "po2", "no": "PO/2", "status": "Waiting Approval",
                          "approval_status": "Waiting Approval", "cancelled": False})
    info2 = RUN(C.cascade(s2, "po1", USER, "PO PO/1 dibatalkan"))
    check("cascade: alokasi PO batal dilepas saja", po_alloc(s2) == [] and info2["allocations_released"] == 1, info2)
    check("cascade: RO dengan PO aktif lain tetap", ro(s2)["cancelled"] is False and info2["ro_cancelled"] == [], info2)
    check("cascade: MRO ikut tetap", mro(s2)["cancelled"] is False and info2["mro_cancelled"] == [], info2)
    check("cascade: alokasi PO aktif tetap ada",
          any(a.get("target_doc_id") == "po2" for a in s2.db.allocations.rows))

    # 3) MRO sudah punya MI aktif -> RO batal, MRO tetap
    s3 = build(mi_status="Posted")
    info3 = RUN(C.cascade(s3, "po1", USER, "PO PO/1 dibatalkan"))
    check("cascade: RO tetap dibatalkan walau ada MI", ro(s3)["cancelled"] is True, info3)
    check("cascade: MRO with MI tetap aktif", mro(s3)["cancelled"] is False and info3["mro_cancelled"] == [], info3)

    # 4) PO masih aktif -> cascade tidak melakukan apa pun
    s4 = build(po_status="Waiting Approval")
    s4.db.po.rows[0]["cancelled"] = False
    info4 = RUN(C.cascade(s4, "po1", USER, "x"))
    check("cascade: PO aktif dilewati", ro(s4)["cancelled"] is False and len(po_alloc(s4)) == 1, info4)

    # 5) idempoten
    s5 = build()
    RUN(C.cascade(s5, "po1", USER, "PO PO/1 dibatalkan"))
    audits1, notifs1 = len(s5.audits), len(s5.notifs)
    info5 = RUN(C.cascade(s5, "po1", USER, "PO PO/1 dibatalkan"))
    check("cascade: idempoten (tanpa audit ganda)", len(s5.audits) == audits1 and len(s5.notifs) == notifs1, info5)
    check("cascade: idempoten (tanpa aksi baru)", info5["ro_cancelled"] == [] and info5["mro_cancelled"] == [], info5)

    # 6) RO yang sudah batal sebelumnya tetap menutup MRO saat PO terakhir batal
    s6 = build(extra_po=True)
    s6.db.po.rows.append({"id": "po2", "no": "PO/2", "status": "Cancelled", "approval_status": "Cancelled",
                          "cancelled": True})
    s6.db.ro.rows[0]["cancelled"] = True
    info6 = RUN(C.cascade(s6, "po1", USER, "PO PO/1 dibatalkan"))
    check("cascade: MRO batal walau RO sudah batal lebih dulu",
          mro(s6)["cancelled"] is True and info6["mro_cancelled"] == ["MRO/1"], info6)

    # 7) reject approver -> PO batal final + cascade + release SPK
    s7 = build(po_status="Rejected")
    s7.db.po.rows[0].update({"cancelled": False})
    released = []

    async def fake_release(po_id, user, reason=None):
        released.append((po_id, reason))

    s7.spk_release_po = fake_release
    result = {"id": "po1", "no": "PO/1", "status": "Rejected", "approval_status": "Rejected"}
    out = RUN(C._finalize_reject(s7, "po1", {"reason": "harga terlalu tinggi"}, USER, result))
    check("reject: PO menjadi Cancelled", po(s7)["status"] == "Cancelled" and po(s7)["cancelled"] is True
          and po(s7)["approval_status"] == "Cancelled", po(s7))
    check("reject: respons ikut Cancelled", out.get("status") == "Cancelled"
          and out.get("document_status") == "Cancelled", out)
    check("reject: alasan audit", "harga terlalu tinggi" in [a["kw"].get("reason") for a in s7.audits], s7.audits)
    check("reject: komitmen SPK dilepas", released and released[0][0] == "po1", released)
    check("reject: RO+MRO ikut batal", ro(s7)["cancelled"] is True and mro(s7)["cancelled"] is True)
    check("reject: cascade dilaporkan", out.get("cascade", {}).get("ro_cancelled") == ["RO/1"], out)

    # 8) PO sudah batal -> reject tidak menggandakan audit
    s8 = build(po_status="Cancelled")
    before = len(s8.audits)
    RUN(C._finalize_reject(s8, "po1", {"reason": "dobel"}, USER, {}))
    check("reject: PO yang sudah batal tidak diproses ulang", len(s8.audits) == before, len(s8.audits))

    print()
    if FAILS:
        print(f"GAGAL: {len(FAILS)} -> {FAILS}")
        return 1
    print("SEMUA UNIT TEST CASCADE LULUS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
