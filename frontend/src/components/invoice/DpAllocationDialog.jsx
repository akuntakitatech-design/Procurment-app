import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { rupiah } from "@/lib/format";
import { round2 } from "@/lib/invoice";
import { dpLimit, sumDp } from "@/lib/supplierDp";

const HEAD = ["", "PO", "Nilai Bagian Invoice", "DP Sudah Dibayar", "DP Digunakan Invoice Lain", "DP Tersedia", "Alokasi DP"];

/**
 * Dialog "Alokasi DP Supplier". Checklist mengisi otomatis MIN(DP Tersedia, Nilai Bagian Invoice PO);
 * Finance boleh menurunkan, tidak boleh menaikkan di atas batas. Backend memvalidasi ulang saat simpan.
 */
export function DpAllocationDialog({ open, onClose, cands, value, onApply, invoiceAmount, paidTotal = 0 }) {
  const [local, setLocal] = useState({});
  useEffect(() => { if (open) setLocal({ ...(value || {}) }); }, [open, value]);
  const toggle = (c, on) => setLocal((m) => {
    const n = { ...m };
    if (on) n[c.po_id] = String(c.suggested); else delete n[c.po_id];
    return n;
  });
  const errOf = (c) => {
    if (local[c.po_id] === undefined) return "";
    const v = Number(local[c.po_id]);
    if (Number.isNaN(v) || v < 0) return "Nilai tidak valid";
    if (v > dpLimit(c) + 0.005) return `Maksimal ${rupiah(dpLimit(c))}`;
    return "";
  };
  const total = sumDp(local);
  const remaining = round2(Number(invoiceAmount || 0) - total - Number(paidTotal || 0));
  const invalid = cands.some((c) => errOf(c)) || remaining < -0.005;
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl" data-testid="dp-allocation-dialog">
        <DialogHeader>
          <DialogTitle>Alokasi DP Supplier</DialogTitle>
          <DialogDescription>DP yang sudah dibayar dari PO sumber DO pada invoice ini. Nilai otomatis = MIN(DP Tersedia, Nilai Bagian Invoice PO); nominal boleh diturunkan.</DialogDescription>
        </DialogHeader>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[820px] text-sm" data-testid="dp-allocation-table">
            <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {HEAD.map((h, i) => <th key={i} className={`p-2.5 ${i >= 2 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
            <tbody>
              {cands.length === 0 && <tr><td colSpan={HEAD.length} className="p-6 text-center text-muted-foreground" data-testid="dp-allocation-empty">Tidak ada DP tersedia dari PO sumber DO yang dipilih.</td></tr>}
              {cands.map((c) => {
                const on = local[c.po_id] !== undefined;
                const err = errOf(c);
                return (
                  <tr key={c.po_id} className={`border-t ${on ? "bg-primary/5" : ""}`} data-testid={`dp-allocation-row-${c.po_no}`}>
                    <td className="p-2.5"><Checkbox checked={on} onCheckedChange={(v) => toggle(c, !!v)} aria-label={`Pilih DP ${c.po_no}`} data-testid={`dp-allocation-check-${c.po_no}`} /></td>
                    <td className="p-2.5"><div className="font-mono text-xs font-semibold">{c.po_no}</div><div className="text-[11px] text-muted-foreground">{c.dp_no}</div></td>
                    <td className="p-2.5 text-right tabular-nums">{rupiah(c.invoice_portion)}</td>
                    <td className="p-2.5 text-right tabular-nums">{rupiah(c.dp_paid)}</td>
                    <td className="p-2.5 text-right tabular-nums">{rupiah(c.dp_used)}</td>
                    <td className="p-2.5 text-right tabular-nums">{rupiah(c.dp_available)}</td>
                    <td className="p-2.5 text-right">
                      <Input type="number" step="0.01" min="0" max={dpLimit(c)} className={`ml-auto w-40 text-right ${err ? "border-destructive focus-visible:ring-destructive" : ""}`} disabled={!on}
                        value={on ? local[c.po_id] : ""} onChange={(e) => setLocal((m) => ({ ...m, [c.po_id]: e.target.value }))} aria-invalid={!!err} data-testid={`dp-allocation-amount-${c.po_no}`} />
                      {err && <div className="mt-1 text-[11px] text-destructive" data-testid={`dp-allocation-error-${c.po_no}`}>{err}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">Nilai Invoice</div><div className="font-head text-lg font-bold tabular-nums">{rupiah(invoiceAmount)}</div></div>
          <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">Total DP Dialokasikan</div><div className="font-head text-lg font-bold tabular-nums" data-testid="dp-allocation-total">{rupiah(total)}</div></div>
          <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">Sisa Hutang setelah DP</div><div className={`font-head text-lg font-bold tabular-nums ${remaining < -0.005 ? "text-destructive" : ""}`} data-testid="dp-allocation-remaining">{rupiah(remaining)}</div></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="dp-allocation-cancel">Batal</Button>
          <Button onClick={() => { onApply(Object.fromEntries(Object.entries(local).map(([k, v]) => [k, round2(v)]).filter(([, v]) => v > 0))); onClose(); }} disabled={invalid} data-testid="dp-allocation-apply">Terapkan Alokasi DP</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
