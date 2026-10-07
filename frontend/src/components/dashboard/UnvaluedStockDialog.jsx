import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { OpeningStatusBadge } from "@/components/OpeningCorrection";
import { num, rupiah } from "@/lib/format";
import { needsAction } from "@/lib/openingValuation";
import { ArrowRight } from "lucide-react";

// Detail "xxx barang punya stok tetapi belum bernilai" (+ saldo awal yang perlu revaluasi) — sumber: /valuation/opening-status.
export function UnvaluedStockDialog({ open, onOpenChange, divisionId }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!open) return;
    setData(null); setErr(null);
    api.get("/valuation/opening-status", { params: divisionId ? { division_id: divisionId } : {} })
      .then((r) => setData(r.data)).catch((e) => setErr(apiError(e)));
  }, [open, divisionId]);
  const s = data?.summary || {};
  const rows = needsAction(data?.rows);
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-w-5xl" data-testid="unvalued-dialog">
      <DialogHeader><DialogTitle>Stok belum bernilai & saldo awal perlu koreksi</DialogTitle>
        <DialogDescription>Nilai diambil dari Import Saldo Awal Persediaan. Status: Siap Ditetapkan / Perlu Revaluasi / Tidak Ada Nilai Sumber (Sudah Dinilai hanya dihitung).</DialogDescription></DialogHeader>
      {err && <div className="flex items-center justify-between rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" data-testid="unvalued-error">{err}</div>}
      {data && <div className="flex flex-wrap gap-4 text-sm" data-testid="unvalued-summary">
        <span>Siap Ditetapkan: <b>{num(s.ready || 0)}</b></span><span>Perlu Revaluasi: <b>{num(s.needs_replay || 0)}</b></span>
        <span>Tidak Ada Nilai Sumber: <b>{num(s.no_source || 0)}</b></span><span>Sudah Dinilai: <b>{num(s.valued || 0)}</b></span><span>Pool belum bernilai: <b>{num(s.unvalued_pools || 0)}</b></span></div>}
      <div className="max-h-[55vh] overflow-auto rounded-md border">
        {!data && !err ? <div className="space-y-2 p-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-7 w-full" />)}</div>
          : <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 text-left text-xs text-muted-foreground dark:bg-slate-900"><tr>
              <th className="px-3 py-2">Kode</th><th className="px-3 py-2">Barang</th><th className="px-3 py-2">Gudang</th><th className="px-3 py-2 text-right">Qty</th>
              <th className="px-3 py-2 text-right">Avg Cost</th><th className="px-3 py-2 text-right">Nilai Saat Ini</th><th className="px-3 py-2 text-right">Kandidat Opening</th><th className="px-3 py-2">Status</th></tr></thead>
            <tbody>
              {rows.map((r) => <tr key={`${r.item_id}-${r.warehouse_id}`} className="border-t" data-testid={`unvalued-row-${r.item_id}-${r.warehouse_id}`}>
                <td className="px-3 py-2 font-mono text-xs">{r.item_code}</td><td className="px-3 py-2">{r.item_name}</td><td className="px-3 py-2">{r.warehouse_name}</td>
                <td className="px-3 py-2 text-right tabular-nums">{num(r.qty)}</td><td className="px-3 py-2 text-right tabular-nums">{rupiah(r.avg_cost)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{rupiah(r.total_value)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.opening_cost != null ? <span title={`Nilai awal ${rupiah(r.opening_value)} / qty ${num(r.opening_qty)}`}>{rupiah(r.opening_cost)}</span> : "—"}</td>
                <td className="px-3 py-2"><OpeningStatusBadge status={r.status} label={r.status_label} testid={`unvalued-status-${r.item_id}-${r.warehouse_id}`} /></td></tr>)}
              {data && !rows.length && <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground" data-testid="unvalued-empty">Semua stok sudah bernilai.</td></tr>}
            </tbody>
          </table>}
      </div>
      <div className="flex justify-end"><Button asChild variant="outline" data-testid="unvalued-open-settings"><Link to="/settings?tab=opening">Buka Nilai Awal Persediaan<ArrowRight className="ml-1.5 h-4 w-4" /></Link></Button></div>
    </DialogContent>
  </Dialog>;
}
