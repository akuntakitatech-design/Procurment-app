"""Master Barang & Inventory — daftar barang + posisi stok per gudang (server-side pagination).

Seluruh perhitungan (scope, agregat, status, ringkasan) ada di `stock_summary` (canonical, dipakai juga
oleh Dashboard). Layer ini hanya menegakkan izin dan memanggil helper tersebut.

Endpoint (read-only):
    GET /api/inventory/item-stock  — parameter sama, khusus barang AKTIF, izin Inventory (`view`).
    GET /api/master-items/stock-list
        ?page=1&page_size=25|50|100&q=&category_id=&warehouse_id=&division_id=
        &active=Aktif|Nonaktif&stock_status=Normal|Low Stock|Out of Stock|Overstock|No Stock
        &sort=code|name|category_label|unit_label|division_label|total_stock|stock_status|created_at&dir=asc|desc

Urutan penegakan: tenant (sesi + proxy isolasi) -> izin modul `items.view` -> cakupan divisi barang
-> cakupan gudang (divisi gudang + penugasan gudang) -> business rule status stok existing.

Sumber kebenaran stok = koleksi `item_warehouse` (current_stock, min_stock, max_stock) yang hanya
digerakkan oleh ledger transaksi. Tidak ada perhitungan stok baru, tidak ada nilai HPP/rata-rata.

Pola query per request (tanpa N+1):
    1. lookup ringan paralel: warehouses, divisions, item_categories, uoms (4 query, tabel kecil)
    2. 1 query daftar barang (filter kategori/divisi di-pushdown ke SQL)
    3. 1 query agregat stok per barang (GROUP BY item_id di MariaDB) -> ringkasan, filter & sort status
    4. 1 query batch stok per sel (item_id IN <barang di halaman aktif> AND warehouse_id IN <gudang scope>)
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

import stock_summary as SS
# Re-export agar import lama tetap berlaku (fungsi aslinya kini di stock_summary).
from stock_summary import (SIZES, STATUSES, SORTS, STATUS_RANK, ITEM_PROJECTION, _f, cell_status, item_status,  # noqa: F401
                           _size, _page, _skey, _item_divisions)


def install(server):
    app = server.app

    def can_view_items(user) -> bool:
        return user.get("role") == "admin" or "items.view" in set(user.get("effective_permissions") or [])

    @app.get("/api/master-items/stock-list", tags=["master-item-stock"])
    async def master_item_stock_list(request: Request, user=Depends(server.current_user)):
        if not can_view_items(user):
            raise HTTPException(403, "Anda tidak memiliki izin untuk melihat data Barang.")
        return await SS.list_response(server, user, dict(request.query_params))

    @app.get("/api/inventory/item-stock", tags=["master-item-stock"])
    async def inventory_item_stock(request: Request, user=Depends(server.current_user)):
        """Posisi Stok Inventory per BARANG: hanya barang aktif; barang tanpa item_warehouse tetap tampil (Stok Habis)."""
        server.require(user, "view")
        return await SS.list_response(server, user, dict(request.query_params), force_active="Aktif")
