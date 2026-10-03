import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";

export function TxnBulkDeleteDialog({ open, module, rows, onClose, onDone, stockModule }) {
  const [checks, setChecks] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) { setChecks(null); return; }
    Promise.all(rows.map((r) => api.get(`/transactions/${module}/${r.id}/capability`)
      .then((x) => ({ row: r, ok: !!x.data.can_delete, reason: x.data.reason || (!x.data.can_delete ? "Tidak memiliki hak hapus" : null) }))
      .catch((e) => ({ row: r, ok: false, reason: apiError(e.response?.data?.detail) }))))
      .then(setChecks);
  }, [open, module, rows]);

  const valid = (checks || []).filter((c) => c.ok), blocked = (checks || []).filter((c) => !c.ok);

  const run = async () => {
    setBusy(true);
    const failed = [];
    for (const c of valid) {
      try { await api.delete(`/transactions/${module}/${c.row.id}`); }
      catch (e) { failed.push(`${c.row.no}: ${apiError(e.response?.data?.detail)}`); }
    }
    setBusy(false);
    if (failed.length) toast.error(`Sebagian gagal dihapus — ${failed.join("; ")}`);
    else toast.success(`${valid.length} transaksi dihapus`);
    onDone?.();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent className="max-w-xl" data-testid="bulk-delete-dialog">
        <DialogHeader>
          <DialogTitle>Hapus Massal</DialogTitle>
          <DialogDescription>Setiap transaksi divalidasi sebelum dihapus.{stockModule ? " Transaksi stok akan direversal sesuai aturan reversal." : ""}</DialogDescription>
        </DialogHeader>
        {!checks ? <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Memvalidasi transaksi...</div> : (
          <div className="max-h-80 space-y-3 overflow-auto text-sm">
            <div><div className="mb-1 text-xs font-semibold uppercase tracking-wider text-emerald-700">Dapat dihapus ({valid.length})</div>
              {valid.length === 0 ? <div className="text-xs text-muted-foreground">Tidak ada</div> : valid.map((c) => <div key={c.row.id} className="flex items-center gap-2 py-0.5" data-testid={`bulk-ok-${c.row.no}`}><CheckCircle2 className="h-4 w-4 text-emerald-600" /><span className="font-mono text-xs">{c.row.no}</span></div>)}
            </div>
            <div><div className="mb-1 text-xs font-semibold uppercase tracking-wider text-destructive">Tidak dapat dihapus ({blocked.length})</div>
              {blocked.length === 0 ? <div className="text-xs text-muted-foreground">Tidak ada</div> : blocked.map((c) => <div key={c.row.id} className="flex items-start gap-2 py-0.5" data-testid={`bulk-blocked-${c.row.no}`}><XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" /><div><span className="font-mono text-xs">{c.row.no}</span><div className="text-xs text-muted-foreground">{c.reason}</div></div></div>)}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Batal</Button>
          <Button variant="destructive" onClick={run} disabled={busy || !checks || valid.length === 0} data-testid="bulk-delete-confirm">
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{blocked.length && valid.length ? `Hapus ${valid.length} yang valid saja` : `Hapus ${valid.length} transaksi`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
