import { useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/DatePicker";
import { StatusBadge } from "@/components/StatusBadge";
import { rupiah, fmtDateTime } from "@/lib/format";
import { fmtD, todayDate, round2 } from "@/lib/invoice";
import { AttachmentPanel, uploadPendingAttachments } from "@/components/DocMeta";
import { Plus, Ban, Paperclip } from "lucide-react";
import { toast } from "sonner";

function PayDialog({ inv, open, onClose, onDone }) {
  const [p, setP] = useState({ date: todayDate(), amount: String(round2(inv.remaining)), reference: "", notes: "" });
  const [pending, setPending] = useState([]);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setP((c) => ({ ...c, [k]: e.target.value }));
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/vendor-invoices/${inv.id}/payments`, { ...p, amount: round2(p.amount) });
      const before = new Set((inv.payments || []).map((x) => x.id));
      const created = (r.data.payments || []).find((x) => !before.has(x.id));
      if (pending.length && created) {
        const { failed } = await uploadPendingAttachments("invoice_payment", created.id, pending);
        if (failed.length) toast.error(`Pembayaran tercatat, tetapi lampiran "${failed.map((f) => f.name).join(", ")}" gagal diunggah.`);
      }
      toast.success("Pembayaran dicatat"); onDone(); onClose();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="payment-dialog">
        <DialogHeader><DialogTitle>Catat Pembayaran — Sisa {rupiah(inv.remaining)}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tanggal Pembayaran"><Input type="date" value={p.date} onChange={set("date")} data-testid="payment-date-input" /></Field>
          <Field label="Nilai Dibayar"><Input type="number" step="0.01" value={p.amount} onChange={set("amount")} data-testid="payment-amount-input" /></Field>
          <Field label="Referensi Pembayaran"><Input value={p.reference} onChange={set("reference")} placeholder="No. transfer / giro" data-testid="payment-reference-input" /></Field>
          <Field label="Catatan Pembayaran"><Input value={p.notes} onChange={set("notes")} data-testid="payment-notes-input" /></Field>
          <div className="col-span-2" data-testid="payment-pending-attachments"><div className="mb-1 text-xs font-medium text-muted-foreground">Lampiran Pembayaran (Bukti Transfer, Advice Bank, Bukti Potong, dll.)</div>
            <AttachmentPanel entity="invoice_payment" pending={pending} onPendingChange={setPending} multiple /></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Batal</Button><Button onClick={submit} disabled={busy} data-testid="payment-submit-btn">{busy ? "Menyimpan..." : "Simpan Pembayaran"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CancelDialog({ inv, pay, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const submit = async () => {
    try { await api.post(`/vendor-invoices/${inv.id}/payments/${pay.id}/cancel`, { reason }); toast.success("Pembayaran dibatalkan"); onDone(); onClose(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="payment-cancel-dialog">
        <DialogHeader><DialogTitle>Batalkan Pembayaran {rupiah(pay.amount)} ({fmtD(pay.date)})</DialogTitle></DialogHeader>
        <Field label="Alasan Pembatalan (wajib)"><Input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="payment-cancel-reason" /></Field>
        <p className="text-xs text-muted-foreground">Pembayaran tidak dihapus; riwayat tetap tersimpan dengan status Dibatalkan.</p>
        <DialogFooter><Button variant="outline" onClick={onClose}>Kembali</Button><Button variant="destructive" onClick={submit} disabled={!reason.trim()} data-testid="payment-cancel-submit">Batalkan Pembayaran</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function PaymentPanel({ inv, canPay, onChanged }) {
  const [open, setOpen] = useState(false);
  const [cancel, setCancel] = useState(null);
  const [openAtt, setOpenAtt] = useState(null);
  return (
    <div className="space-y-3" data-testid="payment-panel">
      <div className="flex items-center justify-between">
        <h3 className="font-head text-sm font-semibold">Histori Pembayaran</h3>
        {canPay && inv.remaining > 0.005 && <Button size="sm" onClick={() => setOpen(true)} data-testid="payment-add-btn"><Plus className="mr-1 h-4 w-4" />Catat Pembayaran</Button>}
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {["Tanggal", "Nilai Dibayar", "Referensi", "Catatan", "Status", "Dicatat Oleh", "Lampiran", ""].map((x, i) => <th key={i} className={`p-2.5 ${i === 1 ? "text-right" : ""}`}>{x}</th>)}</tr></thead>
          <tbody>
            {(inv.payments || []).length === 0 && <tr><td colSpan={8} className="p-5 text-center text-muted-foreground">Belum ada pembayaran</td></tr>}
            {(inv.payments || []).map((p, i) => [
              <tr key={p.id} className="border-t" data-testid={`payment-row-${i}`}>
                <td className="p-2.5">{fmtD(p.date)}</td>
                <td className="p-2.5 text-right tabular-nums">{rupiah(p.amount)}</td>
                <td className="p-2.5">{p.reference || "-"}</td>
                <td className="p-2.5 text-xs">{p.notes || "-"}{p.cancel_reason && <div className="text-rose-600">Alasan batal: {p.cancel_reason}</div>}</td>
                <td className="p-2.5"><StatusBadge status={p.status} /></td>
                <td className="p-2.5 text-xs">{p.created_by_name || p.created_by}<div className="text-muted-foreground">{fmtDateTime(p.created_at)}</div></td>
                <td className="p-2.5"><Button size="sm" variant="outline" onClick={() => setOpenAtt(openAtt === p.id ? null : p.id)} data-testid={`payment-att-toggle-${i}`}><Paperclip className="mr-1 h-3.5 w-3.5" />{(p.attachments || []).length}</Button></td>
                <td className="p-2.5 text-right">{canPay && p.status === "Aktif" && <Button size="sm" variant="ghost" onClick={() => setCancel(p)} data-testid={`payment-cancel-btn-${i}`}><Ban className="mr-1 h-3.5 w-3.5" />Batalkan</Button>}</td>
              </tr>,
              openAtt === p.id && <tr key={`${p.id}-att`} className="bg-muted/20"><td colSpan={8} className="p-3" data-testid={`payment-attachments-${i}`}>
                <AttachmentPanel entity="invoice_payment" entityId={p.id} multiple canUpload={canPay && p.status === "Aktif"} canDelete={canPay && p.status === "Aktif"} /></td></tr>,
            ])}
          </tbody>
        </table>
      </div>
      {open && <PayDialog inv={inv} open onClose={() => setOpen(false)} onDone={onChanged} />}
      {cancel && <CancelDialog inv={inv} pay={cancel} onClose={() => setCancel(null)} onDone={onChanged} />}
    </div>
  );
}
