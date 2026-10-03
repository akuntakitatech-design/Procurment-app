import { useEffect, useState } from "react";
import api from "@/lib/api";
import { num } from "@/lib/format";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Warehouse } from "lucide-react";

// Informasi stok read-only (sumber: /stock/by-warehouse = item_warehouse existing, scope diperiksa backend).
const cache = new Map();
const TTL = 20000;
export function loadStock(itemId, force = false) {
  const hit = cache.get(itemId);
  if (!force && hit && Date.now() - hit.at < TTL) return hit.p;
  const p = api.get(`/stock/by-warehouse/${itemId}`).then((r) => r.data).catch((e) => ({ error: e.response?.status || true, warehouses: [] }));
  cache.set(itemId, { at: Date.now(), p });
  return p;
}

export function StockPopup({ itemId, itemName, warehouseId, open, onClose }) {
  const [d, setD] = useState(null);
  useEffect(() => { if (open && itemId) loadStock(itemId, true).then(setD); }, [open, itemId]);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="stock-popup">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Warehouse className="h-4 w-4" />Stok per Gudang{itemName ? ` — ${itemName}` : ""}</DialogTitle></DialogHeader>
        {!d ? <div className="py-6 text-center text-sm text-muted-foreground">Memuat...</div> : d.error ? <div className="py-6 text-center text-sm text-muted-foreground" data-testid="stock-popup-denied">Stok barang ini tidak dapat ditampilkan (di luar cakupan Anda).</div> :
          <table className="w-full text-sm">
            <thead><tr className="border-b text-left text-[11px] uppercase tracking-wider text-muted-foreground"><th className="p-2">Gudang</th><th className="p-2 text-right">Stok Tersedia</th><th className="p-2">Satuan</th></tr></thead>
            <tbody>{d.warehouses.length === 0 && <tr><td colSpan={3} className="p-4 text-center text-muted-foreground">Tidak ada gudang dalam cakupan Anda</td></tr>}
              {d.warehouses.map((w) => <tr key={w.warehouse_id} className={`border-b last:border-0 ${w.warehouse_id === warehouseId ? "bg-primary/5 font-semibold" : ""}`} data-testid={`stock-popup-row-${w.warehouse_name}`}>
                <td className="p-2">{w.warehouse_name}{w.warehouse_id === warehouseId && <span className="ml-2 text-[10px] font-medium text-primary">(gudang transaksi)</span>}</td>
                <td className="p-2 text-right tabular-nums">{num(w.stock)}</td><td className="p-2">{w.unit || d.unit || ""}</td></tr>)}</tbody>
          </table>}
        <p className="text-[11px] text-muted-foreground">Hanya informasi. Untuk memakai stok gudang lain, pilih gudang yang sesuai atau lakukan Transfer Antar Gudang.</p>
      </DialogContent>
    </Dialog>
  );
}

export function StockInfo({ itemId, warehouseId, itemName, label = "Stok tersedia", value, testid }) {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { setD(null); if (itemId) loadStock(itemId).then(setD); }, [itemId]);
  if (!itemId) return null;
  const row = d && !d.error ? d.warehouses.find((w) => w.warehouse_id === warehouseId) : null;
  const shown = value !== undefined ? value : row ? row.stock : d && !d.error && warehouseId ? 0 : null;
  const text = !warehouseId ? "pilih gudang" : d?.error ? "di luar cakupan" : shown === null ? "…" : `${num(shown)} ${d?.unit || ""}`.trim();
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="mb-0.5 block w-full truncate text-left text-[10px] font-medium text-muted-foreground transition-colors hover:text-primary hover:underline" data-testid={testid || "stock-info"} title="Klik untuk melihat Stok per Gudang">
        {label}: <span className="tabular-nums text-foreground" data-testid={`${testid || "stock-info"}-value`}>{text}</span>
      </button>
      {open && <StockPopup itemId={itemId} itemName={itemName} warehouseId={warehouseId} open onClose={() => setOpen(false)} />}
    </>
  );
}
