import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, Loader2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

// rows: [{id, label}]. Preflight via /master-delete-check/{checkName}; all-or-nothing via /master-bulk-delete/{checkName}.
export function MasterDeleteDialog({ open, rows, checkName, entityLabel, onClose, onDone, onDeselect }) {
  const [checks, setChecks] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) { setChecks(null); return; }
    api.post(`/master-delete-check/${checkName}`, { ids: rows.map((r) => r.id) })
      .then((r) => setChecks(r.data.map((c) => ({ ...c, label: rows.find((x) => x.id === c.id)?.label || c.label }))))
      .catch((e) => { toast.error(apiError(e.response?.data?.detail)); onClose(); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rows, checkName]);

  const valid = (checks || []).filter((c) => c.ok), blocked = (checks || []).filter((c) => !c.ok);
  const single = (checks ? checks.length : rows.length) === 1;

  const dropBlocked = () => {
    onDeselect?.(blocked.map((c) => c.id));
    setChecks(valid);
  };

  const run = async () => {
    setBusy(true);
    try {
      await api.post(`/master-bulk-delete/${checkName}`, { ids: valid.map((c) => c.id) });
      toast.success(single ? `${entityLabel} ${valid[0]?.label} berhasil dihapus` : `${valid.length} data ${entityLabel} berhasil dihapus`);
      onDone?.();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent className="max-w-xl" data-testid="master-delete-dialog">
        <DialogHeader>
          <DialogTitle>{single ? `Hapus ${entityLabel}?` : `Hapus Massal ${entityLabel}`}</DialogTitle>
          <DialogDescription>{single ? <>Anda akan menghapus <b>{(checks?.[0] || rows[0])?.label}</b>. Data yang telah digunakan pada transaksi tidak dapat dihapus.</> : `${checks ? checks.length : rows.length} data dipilih. Seluruh data diperiksa sebelum dihapus.`}</DialogDescription>
        </DialogHeader>
        {!checks ? <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Memeriksa keterkaitan data...</div> : (
          <div className="max-h-80 space-y-3 overflow-auto text-sm">
            {!single && <div className="text-xs font-semibold" data-testid="master-delete-summary">{valid.length} dapat dihapus · {blocked.length} tidak dapat dihapus</div>}
            {valid.map((c) => <div key={c.id} className="flex items-center gap-2" data-testid={`master-delete-ok-${c.id}`}><CheckCircle2 className="h-4 w-4 text-emerald-600" /><span>{c.label}</span></div>)}
            {blocked.map((c) => <div key={c.id} className="flex items-start gap-2" data-testid={`master-delete-blocked-${c.id}`}><XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" /><div><div>{c.label}</div><div className="text-xs text-muted-foreground">Tidak dapat dihapus karena {c.reason}.{" "}Silakan nonaktifkan data apabila sudah tidak digunakan.</div></div></div>)}
            {blocked.length > 0 && <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900" data-testid="master-delete-blocked-notice">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>Penghapusan tidak dapat dilanjutkan selama masih ada data yang diblok. Tidak ada data yang dihapus. {valid.length > 0 ? "Batalkan pilihan data yang diblok untuk melanjutkan." : ""}</span>
            </div>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy} data-testid="master-delete-cancel">{blocked.length && !valid.length ? "Tutup" : "Batal"}</Button>
          {blocked.length > 0 && valid.length > 0 && <Button variant="outline" onClick={dropBlocked} disabled={busy} data-testid="master-delete-drop-blocked">Batalkan Pilihan yang Diblok</Button>}
          <Button variant="destructive" onClick={run} disabled={busy || !checks || valid.length === 0 || blocked.length > 0} data-testid="master-delete-confirm">
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{single || !checks ? "Hapus" : `Hapus ${valid.length} data`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
