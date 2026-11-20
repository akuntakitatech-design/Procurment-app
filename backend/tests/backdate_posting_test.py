"""Uji posting engine untuk transaksi BER-TANGGAL MUNDUR (backdate), tanpa DB sungguhan.

Membuktikan aturan baru di `server.post_movement`:
1. Posting mundur DITERIMA bila stok pada rentang tanggal itu mencukupi.
2. Posting mundur DITOLAK bila membuat saldo historis negatif (pesan menyebut tanggal & angka).
3. Transaksi masuk bertanggal mundur diterima.
4. Entri hasil backdate ditandai `backdated: true` pada stock_ledger & valuation_ledger (jejak audit).
5. Proteksi stok minus untuk transaksi bertanggal hari ini tidak berubah.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


def _match(doc, flt):
    for key, want in (flt or {}).items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in want):
                return False
            continue
        got = doc.get(key)
        if isinstance(want, dict):
            if "$ne" in want and got == want["$ne"]:
                return False
            if "$in" in want and got not in want["$in"]:
                return False
            if "$exists" in want and (key in doc) != bool(want["$exists"]):
                return False
            continue
        if got != want:
            return False
    return True


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


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find(self, flt=None, projection=None):
        return FakeCursor([d for d in self.docs if _match(d, flt)])

    async def find_one(self, flt=None, projection=None):
        for d in self.docs:
            if _match(d, flt):
                return d
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def find_one_and_update(self, flt, update, upsert=False, return_document=True, **kwargs):
        for idx, existing in enumerate(self.docs):
            if _match(existing, flt):
                merged = dict(existing)
                merged.update(update.get("$set") or {})
                self.docs[idx] = merged
                return merged
        if upsert:
            created = dict(update.get("$setOnInsert") or {})
            self.docs.append(created)
            return created
        return None


class FakeDB:
    def __init__(self):
        self.item_warehouse = FakeCollection()
        self.stock_ledger = FakeCollection()
        self.valuation_ledger = FakeCollection()


async def post(**over):
    payload = {"doc_type": "MI", "doc_no": "MI/X", "doc_id": "mi-x", "item_id": "item-1",
               "warehouse_id": "wh-1", "qty_in": 0, "qty_out": 0, "user": {"email": "t@example.test"}}
    payload.update(over)
    return await server.post_movement(**payload)


def pool_qty():
    iw = server.db.item_warehouse.docs
    return float(iw[0].get("current_stock") if iw else 0)


def main():
    server.db = FakeDB()

    async def scenario():
        # Saldo awal + pemakaian normal.
        await post(doc_type="DO", doc_no="DO/1", doc_id="do-1", qty_in=100, unit_cost_in=1000,
                   require_cost=True, txn_at="2026-11-01T02:00:00+00:00")
        await post(doc_no="MI/1", doc_id="mi-1", qty_out=60, txn_at="2026-11-05T02:00:00+00:00")
        assert pool_qty() == 40.0, pool_qty()

        # 1) Backdate 02/11 OUT 5 -> stok pada rentang itu cukup (100 - 60 = 40 minimum).
        await post(doc_no="MI/2", doc_id="mi-2", qty_out=5, txn_at="2026-11-02T02:00:00+00:00")
        assert pool_qty() == 35.0, pool_qty()

        # 4) Jejak audit: entri backdate ditandai.
        assert server.db.stock_ledger.docs[-1]["backdated"] is True
        assert server.db.valuation_ledger.docs[-1]["backdated"] is True
        assert server.db.valuation_ledger.docs[-1]["txn_at"] == "2026-11-02T02:00:00+00:00"

        # 2) Backdate 02/11 OUT 40 -> saldo terendah sejak 02/11 hanya 35 -> ditolak dengan angka.
        try:
            await post(doc_no="MI/3", doc_id="mi-3", qty_out=40, txn_at="2026-11-02T02:00:00+00:00")
            raise AssertionError("backdate melebihi stok seharusnya ditolak")
        except server.StockError as exc:
            msg = str(exc.detail)
        assert msg.startswith("Stok per 2026-11-02 tidak cukup"), msg
        assert "tersedia 35" in msg and "diminta 40" in msg, msg
        assert pool_qty() == 35.0, pool_qty()  # tidak ada perubahan saat ditolak

        # 3) Transaksi MASUK bertanggal mundur diterima & tetap bertanda backdate.
        await post(doc_type="DO", doc_no="DO/2", doc_id="do-2", qty_in=20, unit_cost_in=1000,
                   require_cost=True, txn_at="2026-11-02T03:00:00+00:00")
        assert pool_qty() == 55.0, pool_qty()
        assert server.db.valuation_ledger.docs[-1]["backdated"] is True

        # 5) Transaksi hari ini tetap dicek terhadap saldo sekarang (proteksi stok minus).
        try:
            await post(doc_no="MI/4", doc_id="mi-4", qty_out=1000, txn_at=server.now_iso())
            raise AssertionError("stok minus seharusnya ditolak")
        except server.StockError as exc:
            assert "Stok tidak cukup" in str(exc.detail), str(exc.detail)

        # Pool tanpa riwayat: backdate tetap boleh (tidak ada yang bisa membuat saldo negatif).
        await post(doc_no="MI/5", doc_id="mi-5", item_id="item-2", qty_in=7,
                   unit_cost_in=500, require_cost=True, txn_at="2026-10-01T02:00:00+00:00")
        assert float(server.db.item_warehouse.docs[-1]["current_stock"]) == 7.0

    asyncio.run(scenario())
    print("backdate_posting_test: 5 skenario OK")


if __name__ == "__main__":
    main()
