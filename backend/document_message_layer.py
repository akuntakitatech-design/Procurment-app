"""Configurable default messages / terms for operational documents.

Each document stores its own snapshot in the transaction header. Changing the
setting only affects newly-created transactions; historical documents retain the
text that was saved with them.
"""
from fastapi import Depends, HTTPException


MODULES = {
    "mro": {"label": "MRO — Permintaan Material", "collection": "mro"},
    "ro": {"label": "RO — Permintaan Pembelian", "collection": "ro"},
    "po": {"label": "PO — Pesanan Pembelian", "collection": "po"},
    "do": {"label": "DO — Penerimaan Barang", "collection": "do"},
    "mi": {"label": "MI — Pengeluaran Barang", "collection": "mi"},
    "transfer": {"label": "Transfer Antar Gudang", "collection": "transfers"},
    "loan": {"label": "Pinjam Antar Gudang", "collection": "loans"},
    "adjustment": {"label": "Penyesuaian Stok", "collection": "adjustments"},
    "opname": {"label": "Stock Opname", "collection": "opname"},
}

PO_DEFAULT = """Term and Condition

1. Apabila dalam waktu 7 hari setelah PO diterima material / barang tidak dikirim, maka PO otomatis dianggap batal
2. Untuk Pengikat Unit dan Pipa

Catatan :

1. Pesanan Pembelian ini harus memenuhi syarat dan ketentuan yang berlaku setelah pesanan pembelian diterima.
2. Jika ada informasi yang salah, yang tertulis di pesanan pembelian, maka penjual akan memberitahukan kepada pembeli saat pesanan pembelian ini diterima. Jika tidak, semua informasi ini dianggap benar.
3. Penjual dianggap telah menyetujui setelah menerima pesanan pembelian ini, kecuali penjual menolak dan memberikan pernyataan tertulis dalam 24 jam.
4. Semua invoice harus diajukan/dikirimkan ke alamat “Bill To” yang telah disebutkan di atas oleh pembeli.
5. Invoice hanya dapat diproses apabila melampirkan dokumen sebagai berikut:

- Invoice - Kwitansi (Harus Bermaterai)
- Faktur Pajak (Jika PKP) - Purchase Order
- Delivery Order (Jika Supply Barang atau Material)
- BAST & Time Sheet (Berita Acara Serah Terima & Time Sheet jika Sewa Menyewa Alat)
- Progress Physical (Laporan Summary Progress Pekerjaan jika melakukan Jasa Pekerjaan atau Borongan) - Kontrak Kerja (Jika dilakukan Kontrak, jika ada)"""

DEFAULT_MESSAGES = {k: "" for k in MODULES}
DEFAULT_MESSAGES["po"] = PO_DEFAULT


def _normalize_modules(raw):
    src = (raw or {}).get("modules") if isinstance(raw, dict) else None
    src = src if isinstance(src, dict) else {}
    out = {}
    for key in MODULES:
        val = src.get(key, DEFAULT_MESSAGES.get(key, ""))
        out[key] = str(val or "")
    return out


def install(server):
    app = server.app

    @app.get("/api/settings/document_messages", tags=["settings"])
    async def get_document_message_settings(user=Depends(server.current_user)):
        server.require(user, "view")
        row = await server.db.settings.find_one({"id": "document_messages"}, {"_id": 0})
        return {"id": "document_messages", "modules": _normalize_modules(row), "labels": {k: v["label"] for k, v in MODULES.items()}}

    @app.put("/api/settings/document_messages", tags=["settings"])
    async def put_document_message_settings(body: dict, user=Depends(server.current_user)):
        server.require(user, "edit")
        modules = _normalize_modules(body)
        for key, text in modules.items():
            if len(text) > 20000:
                raise HTTPException(400, f"Pesan default {MODULES[key]['label']} terlalu panjang (maksimal 20.000 karakter)")
        await server.db.settings.update_one(
            {"id": "document_messages"},
            {"$set": {"id": "document_messages", "modules": modules, "updated_by": user.get("email"), "updated_at": server.now_iso()}},
            upsert=True,
        )
        await server.audit(user, "edit", "settings", "document_messages", "Pesan Default Dokumen")
        return {"id": "document_messages", "modules": modules, "labels": {k: v["label"] for k, v in MODULES.items()}}

    @app.get("/api/document-message/{module}/{did}", tags=["documents"])
    async def get_document_message(module: str, did: str, user=Depends(server.current_user)):
        server.require(user, "view")
        meta = MODULES.get(module)
        if not meta:
            raise HTTPException(404, "Modul transaksi tidak dikenal")
        doc = await getattr(server.db, meta["collection"]).find_one({"id": did}, {"_id": 0, "document_message": 1})
        if not doc:
            raise HTTPException(404, "Transaksi tidak ditemukan")
        return {"module": module, "id": did, "document_message": doc.get("document_message") or ""}

    @app.put("/api/document-message/{module}/{did}", tags=["documents"])
    async def put_document_message(module: str, did: str, body: dict, user=Depends(server.current_user)):
        meta = MODULES.get(module)
        if not meta:
            raise HTTPException(404, "Modul transaksi tidak dikenal")
        if not (server.has_perm(user, "create") or server.has_perm(user, "edit")):
            server.require(user, "edit")
        text = str((body or {}).get("document_message") or "")
        if len(text) > 20000:
            raise HTTPException(400, "Pesan dokumen terlalu panjang (maksimal 20.000 karakter)")
        coll = getattr(server.db, meta["collection"])
        doc = await coll.find_one({"id": did}, {"_id": 0, "no": 1, "document_message": 1})
        if not doc:
            raise HTTPException(404, "Transaksi tidak ditemukan")
        await coll.update_one({"id": did}, {"$set": {"document_message": text, "document_message_updated_by": user.get("email"), "document_message_updated_at": server.now_iso()}})
        if (doc.get("document_message") or "") != text:
            await server.audit(user, "edit", module, did, doc.get("no"), before={"document_message": doc.get("document_message") or ""}, after={"document_message": text})
        return {"ok": True, "module": module, "id": did, "document_message": text}
