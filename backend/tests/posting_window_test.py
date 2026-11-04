"""Uji regresi guard "posting mundur" pada pool stok (tanpa DB sungguhan).

Membuktikan tiga perilaku yang diperbaiki:
1. Tanggal sama (WIB) tidak ditolak walau representasi UTC-nya berbeda.
2. Entri reversal tidak dianggap sebagai pergerakan stok terakhir.
3. Entri milik dokumen yang sedang diposting ulang tidak memblokir dirinya sendiri.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=-1):
        self.docs = sorted(self.docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    async def to_list(self, limit):
        return self.docs[:limit]


class FakeLedger:
    def __init__(self, docs):
        self.docs = docs

    def find(self, flt, projection=None):
        return FakeCursor([d for d in self.docs if self._match(d, flt)])

    @staticmethod
    def _match(doc, flt):
        for key, want in (flt or {}).items():
            got = doc.get(key)
            if isinstance(want, dict) and "$ne" in want:
                if got == want["$ne"]:
                    return False
            elif got != want:
                return False
        return True


class FakeDB:
    def __init__(self, ledger_docs):
        self.valuation_ledger = FakeLedger(ledger_docs)


def led(**over):
    row = {"item_id": "item-1", "warehouse_id": "wh-1"}
    row.update(over)
    return row


def run_case(ledger_docs, txn_at, doc_id=None):
    server.db = FakeDB(ledger_docs)
    try:
        asyncio.run(server.assert_posting_window("item-1", "wh-1", txn_at, doc_id=doc_id))
        return "ok"
    except server.StockError as exc:
        return str(exc.detail)


def main():
    # DO 02/11 WIB tersimpan 01/11T17:00Z; MI 02/11 WIB tersimpan timestamp nyata.
    assert run_case([led(doc_no="MI/1", txn_at="2026-11-02T02:30:03.696Z")],
                    "2026-11-01T17:00:00.000Z") == "ok"

    # Benar-benar mundur (01/11 WIB vs 02/11 WIB) -> ditolak dengan tanggal WIB.
    msg = run_case([led(doc_no="MI/1", txn_at="2026-11-02T02:30:03.696Z")],
                   "2026-10-31T17:00:00.000Z")
    assert msg.startswith("Transaksi tidak dapat diposting mundur"), msg
    assert "2026-11-02" in msg and "MI/1" in msg, msg

    # Entri reversal bertanggal "sekarang" tidak boleh memblokir posting ulang dokumen.
    assert run_case([led(doc_no="MI/1", txn_at="2026-11-04T03:00:00+00:00", is_reversal=True)],
                    "2026-11-01T17:00:00.000Z") == "ok"

    # Entri dokumen sendiri tidak memblokir dirinya saat edit/posting ulang.
    assert run_case([led(doc_no="DO/1", doc_id="do-1", txn_at="2026-11-04T03:00:00+00:00")],
                    "2026-11-01T17:00:00.000Z", doc_id="do-1") == "ok"

    # Dokumen lain yang lebih baru tetap memblokir.
    assert run_case([led(doc_no="MI/9", doc_id="mi-9", txn_at="2026-11-04T03:00:00+00:00")],
                    "2026-11-01T17:00:00.000Z", doc_id="do-1").startswith("Transaksi tidak dapat diposting mundur")

    print("posting_window_test: 5 kasus OK")


if __name__ == "__main__":
    main()
