import { Fragment, useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { num, rupiah, fmtDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Check, History, Info, TrendingDown } from "lucide-react";

const STATUS_STYLE = {
  "Kontrak Aktif + Supplier Utama": "border-primary/40 bg-primary/10 text-primary",
  "Kontrak Aktif": "border-primary/30 text-primary",
  "Supplier Utama": "border-amber-500/40 text-amber-700 dark:text-amber-400",
  "Riwayat Pembelian": "text-muted-foreground",
};

/** Harga per satuan dasar; bila transaksi/kontrak memakai satuan lain, harga aslinya ditampilkan kecil. */
const Price = ({ base, unit, alt, altUnit, showAlt, testid }) => {
  if (base == null) return <span className="text-muted-foreground">-</span>;
  return (
    <div data-testid={testid}>
      <div className="whitespace-nowrap font-semibold tabular-nums">{rupiah(base)}</div>
      <div className="text-[11px] text-muted-foreground">per {unit}</div>
      {showAlt && alt != null && altUnit && <div className="whitespace-nowrap text-[11px] text-muted-foreground tabular-nums">({rupiah(alt)} / {altUnit})</div>}
    </div>
  );
};
const otherUom = (uomId, baseId) => !!uomId && !!baseId && uomId !== baseId;

/** Riwayat (maks. 5) pembelian Barang + Supplier — dimuat hanya saat "Lihat Riwayat" dibuka. */
function HistoryPanel({ state, supplierName }) {
  if (!state || state.loading) return <div className="space-y-1.5 p-3" data-testid="po-price-history-loading">{[0, 1].map((i) => <Skeleton key={i} className="h-7 w-full" />)}</div>;
  if (state.error) return <div className="p-3 text-sm text-destructive" data-testid="po-price-history-error">{state.error}</div>;
  if (!state.rows.length) return <div className="p-3 text-sm text-muted-foreground" data-testid="po-price-history-empty">Belum Ada Riwayat pembelian dari {supplierName}.</div>;
  return (
    <div className="p-3">
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Riwayat Harga — {state.rows.length} pembelian terakhir{state.count > state.rows.length ? ` dari ${state.count}` : ""}</div>
      <table className="w-full text-sm" data-testid="po-price-history-table"><thead><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
        <th className="p-1.5">Tanggal</th><th className="p-1.5">No PO</th><th className="p-1.5">Supplier</th><th className="p-1.5 text-right">Qty</th><th className="p-1.5">Satuan</th><th className="p-1.5 text-right">Harga Satuan Net</th>
      </tr></thead><tbody>
        {state.rows.map((h, i) => (
          <tr key={`${h.po_id}-${i}`} className="border-t" data-testid={`po-price-history-row-${i}`}>
            <td className="p-1.5">{fmtDate(h.date)}</td><td className="p-1.5 font-mono text-xs font-semibold">{h.po_no}</td><td className="p-1.5">{h.supplier_name}</td>
            <td className="p-1.5 text-right tabular-nums">{num(h.qty)}</td><td className="p-1.5">{h.unit || "-"}</td><td className="p-1.5 text-right font-medium tabular-nums">{rupiah(h.unit_net_price)}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  );
}

/** Informasi Harga & Supplier untuk satu baris kebutuhan RO (read-only, on-demand). */
export function PoPriceInsightDialog({ row, poDate, currentSupplierId, onClose, onPick }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [openHist, setOpenHist] = useState(null);
  const [hist, setHist] = useState({});
  const load = () => {
    setLoading(true); setError(null);
    api.get("/pull/ro-for-po/price-insight", { params: { ro_line_id: row.line_id, date: poDate ? String(poDate).slice(0, 10) : "" } })
      .then((r) => setData(r.data)).catch((e) => setError(apiError(e.response?.data?.detail))).finally(() => setLoading(false));
  };
  useEffect(() => { setData(null); setHist({}); setOpenHist(null); load(); }, [row.line_id, poDate]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggleHistory = (sid) => {
    if (openHist === sid) { setOpenHist(null); return; }
    setOpenHist(sid);
    if (hist[sid] && !hist[sid].error) return;
    setHist((c) => ({ ...c, [sid]: { loading: true, rows: [] } }));
    api.get("/pull/ro-for-po/price-history", { params: { ro_line_id: row.line_id, supplier_id: sid, limit: 5 } })
      .then((r) => setHist((c) => ({ ...c, [sid]: { rows: r.data.rows || [], count: r.data.count || 0 } })))
      .catch((e) => setHist((c) => ({ ...c, [sid]: { rows: [], error: apiError(e.response?.data?.detail) } })));
  };
  const unit = data?.base_unit || row.base_unit || "";
  const sups = data?.suppliers || [];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-[min(96vw,1280px)] max-h-[90vh] overflow-y-auto" data-testid="po-price-insight">
        <DialogHeader>
          <DialogTitle className="font-head">Informasi Harga & Supplier</DialogTitle>
          <DialogDescription>Informasi pembanding untuk membantu Purchasing. Keputusan supplier tetap pada Anda.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-3 text-sm md:grid-cols-5" data-testid="po-price-insight-header">
          <div><div className="text-xs text-muted-foreground">Kode Barang</div><div className="font-mono font-semibold" data-testid="po-price-insight-item-code">{data?.item_code || row.item_code}</div></div>
          <div className="md:col-span-2"><div className="text-xs text-muted-foreground">Nama Barang</div><div className="font-medium" data-testid="po-price-insight-item-name">{data?.item_name || row.item_name}</div></div>
          <div><div className="text-xs text-muted-foreground">Qty Kebutuhan / Sisa PO</div><div className="tabular-nums" data-testid="po-price-insight-qty">{num(data?.qty_ro ?? row.qty_ro_base)} / <span className="font-semibold">{num(data?.sisa_po ?? row.outstanding_base)}</span> {unit}</div></div>
          <div><div className="text-xs text-muted-foreground">Divisi · RO</div><div data-testid="po-price-insight-division">{data?.division_name || row.division_name || "-"} · <span className="font-mono text-xs">{data?.ro_no || row.ro_no}</span></div></div>
        </div>
        {data && !data.price_visible && <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs" data-testid="po-price-insight-no-access"><Info className="h-4 w-4 shrink-0" />Harga tidak ditampilkan karena Anda tidak memiliki akses Lihat Harga Beli.</div>}
        {loading ? <div className="space-y-2" data-testid="po-price-insight-loading">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
          : error ? <div className="rounded-md border border-destructive/40 p-4 text-sm" data-testid="po-price-insight-error">{error} <Button size="sm" variant="outline" className="ml-2" onClick={load} data-testid="po-price-insight-retry">Coba lagi</Button></div>
          : !sups.length ? <div className="rounded-md border p-6 text-center text-sm text-muted-foreground" data-testid="po-price-insight-empty">Belum ada supplier kontrak aktif, Supplier Utama, maupun riwayat pembelian untuk barang ini. Pilih supplier secara manual pada form PO.</div>
          : (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full min-w-[1100px] text-sm" data-testid="po-price-insight-table"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="p-2">Supplier</th><th className="p-2">Status</th><th className="p-2 text-right">Harga Kontrak</th><th className="p-2">Berlaku Sampai</th><th className="p-2 text-right">Harga Beli Terakhir</th><th className="p-2">Tanggal PO Terakhir</th><th className="p-2">No PO</th><th className="p-2">Selisih</th><th className="p-2 text-right">Aksi</th>
              </tr></thead><tbody>
                {sups.map((s) => { const cur = currentSupplierId && currentSupplierId === s.supplier_id; return (
                  <Fragment key={s.supplier_id}>
                    <tr className={`border-t align-top ${cur ? "bg-primary/5" : ""}`} data-testid={`po-price-insight-row-${s.supplier_code || s.supplier_id}`}>
                      <td className="p-2"><div className="font-medium">{s.supplier_name}</div>{s.supplier_code && <div className="font-mono text-xs text-muted-foreground">{s.supplier_code}</div>}{cur && <Badge variant="outline" className="mt-1 text-[10px]">Supplier PO saat ini</Badge>}</td>
                      <td className="p-2"><Badge variant="outline" className={`whitespace-nowrap text-[11px] ${STATUS_STYLE[s.status] || ""}`} data-testid={`po-price-insight-status-${s.supplier_code || s.supplier_id}`}>{s.status}</Badge>{s.is_contract && <div className="mt-1 font-mono text-[11px] text-muted-foreground">{s.contract_number} · {s.contract_status}</div>}</td>
                      <td className="p-2 text-right">{s.is_contract ? <Price base={s.contract_price_base} unit={unit} alt={s.contract_price} altUnit={s.contract_uom} showAlt={otherUom(s.contract_uom_id, data.base_uom_id)} testid={`po-price-insight-contract-${s.supplier_code || s.supplier_id}`} /> : <span className="text-muted-foreground">-</span>}</td>
                      <td className="p-2 whitespace-nowrap">{s.is_contract ? (s.effective_end ? fmtDate(s.effective_end) : "Tanpa batas") : "-"}</td>
                      <td className="p-2 text-right"><Price base={s.last_price_base} unit={unit} alt={s.last_price} altUnit={s.last_unit} showAlt={otherUom(s.last_uom_id, data.base_uom_id)} testid={`po-price-insight-last-${s.supplier_code || s.supplier_id}`} />{s.last_qty != null && <div className="whitespace-nowrap text-[11px] text-muted-foreground">Qty PO {num(s.last_qty)} {s.last_unit}</div>}</td>
                      <td className="p-2 whitespace-nowrap">{s.last_po_date ? fmtDate(s.last_po_date) : "-"}</td>
                      <td className="p-2 font-mono text-xs font-semibold">{s.last_po_no || "-"}</td>
                      <td className="p-2 text-xs"><div data-testid={`po-price-insight-diff-${s.supplier_code || s.supplier_id}`}>{s.diff_label || "-"}</div>{s.is_lowest && <Badge variant="outline" className="mt-1 gap-1 border-primary/40 text-[10px] text-primary" data-testid={`po-price-insight-lowest-${s.supplier_code || s.supplier_id}`}><TrendingDown className="h-3 w-3" />Harga terendah</Badge>}</td>
                      <td className="p-2"><div className="flex justify-end gap-1.5">
                        {data.price_visible && <Button type="button" size="sm" variant="ghost" className="h-8 px-2" onClick={() => toggleHistory(s.supplier_id)} aria-expanded={openHist === s.supplier_id} data-testid={`po-price-insight-history-${s.supplier_code || s.supplier_id}`}><History className="mr-1 h-3.5 w-3.5" />{openHist === s.supplier_id ? "Tutup Riwayat" : "Lihat Riwayat"}</Button>}
                        <Button type="button" size="sm" variant={cur ? "secondary" : "default"} className="h-8 px-2" disabled={cur} onClick={() => onPick(s)} data-testid={`po-price-insight-pick-${s.supplier_code || s.supplier_id}`}><Check className="mr-1 h-3.5 w-3.5" />{cur ? "Terpilih" : "Pilih Supplier"}</Button>
                      </div></td>
                    </tr>
                    {openHist === s.supplier_id && <tr className="border-t bg-muted/20"><td colSpan={9}><HistoryPanel state={hist[s.supplier_id]} supplierName={s.supplier_name} /></td></tr>}
                  </Fragment>); })}
              </tbody></table>
            </div>
          )}
        <p className="text-xs text-muted-foreground">Harga dibandingkan per {unit || "satuan dasar"}, net setelah diskon item dan tanpa PPN. Harga Beli Terakhir diambil dari PO Approved/Final terakhir. Memilih supplier hanya mengubah supplier pada PO yang sedang dibuat, tidak mengubah Supplier Utama barang maupun Kontrak Harga Vendor.</p>
        <DialogFooter><Button variant="outline" onClick={onClose} data-testid="po-price-insight-close">Tutup</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
