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
  const ttl = force === "fresh" ? 3000 : TTL;
  if (force !== true && hit && Date.now() - hit.at < ttl) return hit.p;
  const p = api.get(`/stock/by-warehouse/${itemId}`).then((r) => r.data).catch((e) => ({ error: e.response?.status || true, warehouses: [] }));
  cache.set(itemId, { at: Date.now(), p });
  return p;
}

export function StockPopup({ itemId, itemName, warehouseId, open, onClose }) {
  const [d, setD] = useState(null);
  useEffect(() => { if (open && itemId) loadStock(itemId, "fresh").then(setD); }, [open, itemId]);
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

// Badge stok tunggal di pojok kanan atas field Quantity (klik -> Stok per Gudang).
export function StockBadge({ itemId, warehouseId, itemName, value, testid, className = "" }) {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    setD(null);
    if (itemId && warehouseId) loadStock(itemId, "fresh").then((r) => live && setD(r));
    return () => { live = false; };
  }, [itemId, warehouseId]);
  if (!itemId || !warehouseId) return null;
  const row = d && !d.error ? d.warehouses.find((w) => w.warehouse_id === warehouseId) : null;
  const stock = value !== undefined && value !== null ? Number(value) : d && !d.error ? Number(row?.stock) || 0 : null;
  const tone = d?.error && value == null ? "border-slate-200 bg-slate-100 text-slate-500" : stock === null ? "border-slate-200 bg-slate-100 text-slate-500" : stock > 0 ? "border-emerald-200 bg-emerald-100 text-emerald-700" : "border-red-200 bg-red-50 text-red-600";
  const text = d?.error && value == null ? "—" : stock === null ? "..." : num(stock);
  const title = d?.error && value == null ? "Stok di luar cakupan Anda" : `Stok tersedia${d?.unit ? ` (${d.unit})` : ""} — klik untuk Stok per Gudang`;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title={title} data-testid={testid || "stock-badge"}
        className={`absolute -top-2 right-1 z-10 h-4 min-w-[18px] rounded-full border px-1 text-[10px] font-semibold leading-[14px] tabular-nums shadow-sm transition-transform hover:scale-110 ${tone} ${className}`}>{text}</button>
      {open && <StockPopup itemId={itemId} itemName={itemName} warehouseId={warehouseId} open onClose={() => setOpen(false)} />}
    </>
  );
}

export function QtyStock({ children, badgeClass, ...badge }) {
  return <div className="relative">{children}<StockBadge {...badge} className={badgeClass} /></div>;
}
