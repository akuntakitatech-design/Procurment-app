"""Uji regresi guard POSTING MUNDUR (backdate) pada pool stok — tanpa DB sungguhan.

Aturan yang diuji: backdate DIIZINKAN selama stok pada rentang tanggal itu mencukupi.
Yang dibandingkan bukan saldo di tanggal backdate saja, melainkan saldo TERENDAH sejak
tanggal tersebut sampai sekarang (transaksi mundur mengurangi saldo di seluruh rentang
sesudahnya). Transaksi masuk tidak pernah membuat saldo historis negatif, jadi selalu lolos.

Perilaku lama yang tetap dipertahankan:
1. Tanggal sama (WIB) tidak dianggap mundur walau representasi UTC-nya berbeda.
2. Entri reversal tidak dianggap pergerakan stok terakhir.
3. Entri milik dokumen yang sedang diposting ulang tidak memblokir dirinya sendiri.
4. Entri yang SUDAH dibalik tidak lagi berlaku.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs
        self._skip = 0
        self._limit = None

    def sort(self, key, direction=-1):
        self.docs = sorted(self.docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    def skip(self, n):
        self._skip = int(n or 0)
        return self

    def limit(self, n):
        self._limit = int(n or 0)
        return self

    async def to_list(self, limit):
        rows = self.docs[self._skip:]
        caps = [x for x in (self._limit, limit) if x]
        return rows[:min(caps)] if caps else rows


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
            elif isinstance(want, dict) and "$in" in want:
                if got not in want["$in"]:
                    return False
            elif got != want:
                return False
        return True


class FakePools:
    """item_warehouse: saldo pool = Σ (qty_in - qty_out) SELURUH entri (termasuk reversal),
    sama seperti state nyata setelah engine mem-posting semua mutasi."""

    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, flt, projection=None):
        item_id, wh = flt.get("item_id"), flt.get("warehouse_id")
        balance = 0.0
        for d in self.docs:
            if d.get("item_id") == item_id and d.get("warehouse_id") == wh:
                balance += float(d.get("qty_in") or 0) - float(d.get("qty_out") or 0)
        return {"item_id": item_id, "warehouse_id": wh, "current_stock": balance}


class FakeDB:
    def __init__(self, ledger_docs):
        self.valuation_ledger = FakeLedger(ledger_docs)
        self.stock_ledger = FakeLedger(ledger_docs)
        self.item_warehouse = FakePools(ledger_docs)


def led(**over):
    row = {"item_id": "item-1", "warehouse_id": "wh-1"}
    row.update(over)
    return row


def mv(day, qty_in=0.0, qty_out=0.0, hour="02:00:00", **over):
    """Satu pergerakan stok ber-tanggal bisnis `day` (WIB) pada jam 09:00 WIB."""
    row = led(qty_in=qty_in, qty_out=qty_out, txn_at=f"{day}T{hour}+00:00")
    row["at"] = row["txn_at"]
    row.update(over)
    return row


def run_case(ledger_docs, txn_at, doc_id=None, qty_out=0.0):
    server.db = FakeDB(ledger_docs)
    try:
        asyncio.run(server.assert_posting_window("item-1", "wh-1", txn_at, doc_id=doc_id, qty_out=qty_out))
        return "ok"
    except server.StockError as exc:
        return str(exc.detail)


def main():
    # 01/11 WIB = input DatePicker "2026-11-01" oleh frontend.
    D1 = "2026-11-01T17:00:00.000Z"

    # 1. Tanggal sama (WIB) tidak dianggap mundur walau timestamp UTC-nya beda.
    assert run_case([mv("2026-11-02", qty_out=5)], D1, qty_out=5) == "ok"

    # 2. Backdate DENGAN stok cukup -> lolos (inti perubahan: dulu selalu ditolak).
    ledger = [mv("2026-11-01", qty_in=100), mv("2026-11-05", qty_out=60), mv("2026-11-10", qty_out=30)]
    assert run_case(ledger, "2026-11-02T01:00:00.000Z", qty_out=5) == "ok"

    # 2b. Batas persis (= saldo terendah sejak tanggal itu) masih boleh.
    assert run_case(ledger, "2026-11-02T01:00:00.000Z", qty_out=10) == "ok"

    # 3. Backdate melebihi stok -> ditolak dengan pesan yang menyebut tanggal & angka.
    msg = run_case(ledger, "2026-11-02T01:00:00.000Z", qty_out=40)
    assert msg.startswith("Stok per 2026-11-02 tidak cukup"), msg
    assert "tersedia 10" in msg and "diminta 40" in msg, msg

    # 4. Stok DI TANGGAL itu cukup, tetapi transaksi sesudahnya jadi minus -> tetap ditolak.
    #    01/11 +100, 05/11 -100, 10/11 +50 -> pada 02/11 saldo 100, tetapi backdate 10 membuat 05/11 = -10.
    ledger_gap = [mv("2026-11-01", qty_in=100), mv("2026-11-05", qty_out=100), mv("2026-11-10", qty_in=50)]
    msg = run_case(ledger_gap, "2026-11-02T01:00:00.000Z", qty_out=10)
    assert msg.startswith("Stok per 2026-11-02 tidak cukup"), msg
    assert "tersedia 0" in msg, msg

    # 5. Transaksi MASUK bertanggal mundur selalu lolos (tidak mungkin membuat saldo negatif).
    assert run_case(ledger, "2026-10-31T17:00:00.000Z", qty_out=0) == "ok"

    # 6. Hanya ada entri reversal -> tidak ada pergerakan aktif, tidak menghalangi.
    assert run_case([mv("2026-11-04", qty_in=5, is_reversal=True)], D1, qty_out=5) == "ok"

    # 7. Entri dokumen sendiri tidak memblokir dirinya saat edit/posting ulang.
    assert run_case([mv("2026-11-04", qty_out=5, doc_id="do-1")], D1, doc_id="do-1", qty_out=5) == "ok"

    # 8. Entri yang SUDAH dibalik tidak lagi berlaku (dokumennya dihapus/diedit).
    assert run_case([
        mv("2026-11-01", qty_in=100, id="old"),
        mv("2026-11-11", qty_in=50, id="new", doc_no="DO/2"),
        mv("2026-11-11", qty_out=50, id="rev", doc_no="Reversal DO/2", is_reversal=True, reversal_of="new"),
    ], "2026-11-08T17:00:00.000Z", qty_out=40) == "ok"

    # 9. Backdate lintas bulan dengan riwayat panjang: saldo minimum dihitung dari seluruh rentang.
    long_ledger = [
        mv("2026-09-01", qty_in=500),
        mv("2026-09-15", qty_out=480),
        mv("2026-10-01", qty_in=400),
        mv("2026-10-20", qty_out=300),
    ]
    assert run_case(long_ledger, "2026-09-10T01:00:00.000Z", qty_out=20) == "ok"
    assert run_case(long_ledger, "2026-09-10T01:00:00.000Z", qty_out=21).startswith("Stok per 2026-09-10 tidak cukup")

    # 10. Pool tanpa riwayat sama sekali -> tidak ada yang menghalangi.
    assert run_case([], D1, qty_out=10) == "ok"

    print("posting_window_test: 13 kasus OK")


if __name__ == "__main__":
    main()
