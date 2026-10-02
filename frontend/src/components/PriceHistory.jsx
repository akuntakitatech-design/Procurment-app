import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { History, X } from "lucide-react";
import { rupiah, fmtDate } from "@/lib/format";

// CP5A-1 — read-only purchase price history (decision support, NOT price override).
export function PriceHistory({ itemId, uomId, supplierId, itemName }) {
  const [summary, setSummary] = useState(null);
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState(supplierId ? "vendor" : "all");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  // lightweight last-price for the row (single call, not full history)
  useEffect(() => {
    let active = true;
    if (!itemId) { setSummary(null); return; }
    const p = new URLSearchParams({ item_id: itemId, summary: "1" });
    if (uomId) p.set("uom_id", uomId);
    api.get(`/purchase-price-history?${p.toString()}`).then(r => { if (active) setSummary(r.data.last || null); }).catch(() => {});
    return () => { active = false; };
  }, [itemId, uomId]);

  const loadFull = useCallback((sc) => {
    if (!itemId) return;
    setLoading(true);
    const p = new URLSearchParams({ item_id: itemId, scope: sc, limit: "20" });
    if (uomId) p.set("uom_id", uomId);
    if (supplierId) p.set("supplier_id", supplierId);
    api.get(`/purchase-price-history?${p.toString()}`).then(r => setData(r.data)).catch(() => setData({ rows: [], last: null })).finally(() => setLoading(false));
  }, [itemId, uomId, supplierId]);

  const openModal = () => { setOpen(true); const sc = supplierId ? "vendor" : "all"; setScope(sc); loadFull(sc); };
  const switchScope = (sc) => { setScope(sc); loadFull(sc); };

  if (!itemId) return null;
  const variance = (price) => {
    const base = summary ? Number(summary.unit_price) : 0;
    if (!base) return null;
    const pct = ((Number(price) - base) / base) * 100;
    return pct;
  };

  return (
    <div className="inline-flex">
      <button type="button" onClick={openModal} data-testid="price-history-btn" title={summary ? `Riwayat Harga — Terakhir ${rupiah(summary.unit_price)} · ${fmtDate(summary.date)}` : "Riwayat Harga"} className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-primary">
        <History className="h-4 w-4" />
      </button>

      {open && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center p-4" role="dialog" aria-modal="true" data-testid="price-history-modal">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative z-10 w-full max-w-2xl overflow-hidden rounded-xl border bg-card shadow-2xl">
            <div className="flex items-start justify-between gap-3 border-b px-5 py-3">
              <div>
                <h3 className="font-head text-base font-semibold">Riwayat Harga Beli — {itemName || "Barang"}</h3>
                <p className="text-xs text-muted-foreground">Informasi referensi (read-only). Tidak otomatis mengubah Harga PO.</p>
              </div>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setOpen(false)}><X className="h-4 w-4" /></Button>
            </div>

            {data?.last && (
              <div className="border-b bg-muted/40 px-5 py-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Pembelian terakhir</div>
                <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-lg font-bold">{rupiah(data.last.unit_price)} <span className="text-sm font-normal text-muted-foreground">/ {data.last.uom}</span></span>
                  <span className="text-sm text-muted-foreground">{fmtDate(data.last.date)}</span>
                  <span className="text-sm text-muted-foreground">{data.last.supplier_name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{data.last.po_no}</span>
                </div>
              </div>
            )}

            <div className="flex items-center gap-2 border-b px-5 py-2">
              <button type="button" onClick={() => switchScope("vendor")} disabled={!supplierId} className={`rounded-md px-3 py-1 text-xs font-medium ${scope === "vendor" ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"} ${!supplierId ? "opacity-40 cursor-not-allowed" : ""}`} data-testid="ph-scope-vendor">Vendor ini</button>
              <button type="button" onClick={() => switchScope("all")} className={`rounded-md px-3 py-1 text-xs font-medium ${scope === "all" ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`} data-testid="ph-scope-all">Semua Vendor</button>
            </div>

            <div className="max-h-[45vh] overflow-y-auto px-2 py-2">
              {loading && <p className="p-4 text-center text-sm text-muted-foreground">Memuat…</p>}
              {!loading && (!data || (data.rows || []).length === 0) && (
                <p className="p-6 text-center text-sm text-muted-foreground" data-testid="ph-empty">Belum ada historis pembelian untuk barang ini.</p>
              )}
              {!loading && data && (data.rows || []).length > 0 && (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Tanggal</th><th className="p-2">No. PO</th><th className="p-2">Vendor</th><th className="p-2 text-right">Qty</th><th className="p-2 text-right">Harga/Sat</th></tr></thead>
                  <tbody>
                    {data.rows.map((r, i) => (
                      <tr key={i} className="border-t">
                        <td className="p-2 whitespace-nowrap">{fmtDate(r.date)}</td>
                        <td className="p-2 font-mono text-xs">{r.po_no}</td>
                        <td className="p-2">{r.supplier_name}</td>
                        <td className="p-2 text-right">{r.qty} {r.uom}</td>
                        <td className="p-2 text-right tabular-nums">{rupiah(r.unit_price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
