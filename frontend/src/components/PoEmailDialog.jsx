import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/DatePicker";
import { Paperclip, AlertTriangle, Loader2, Send } from "lucide-react";
import { fmtDateTime } from "@/lib/format";
import { toast } from "sonner";

export function PoEmailDialog({ poId, open, onClose, onSent }) {
  const [ctx, setCtx] = useState(null);
  const [form, setForm] = useState({ to: "", cc: "", subject: "", message: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !poId) return;
    setCtx(null);
    api.get(`/po/${poId}/email-context`).then((r) => { setCtx(r.data); setForm({ to: r.data.default_to || "", cc: "", subject: r.data.subject, message: r.data.message }); })
      .catch((e) => { toast.error(apiError(e.response?.data?.detail)); onClose(); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, poId]);

  const send = async () => {
    if (!form.to.includes("@")) return toast.error("Email tujuan wajib diisi");
    setBusy(true);
    try { await api.post(`/po/${poId}/email`, form); toast.success(`PO berhasil dikirim ke ${form.to}`); onSent?.(); onClose(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent className="max-w-lg" data-testid="po-email-dialog">
        <DialogHeader><DialogTitle>Kirim Email PO {ctx?.po_no || ""}</DialogTitle><DialogDescription>Periksa penerima dan isi pesan sebelum mengirim.</DialogDescription></DialogHeader>
        {!ctx ? <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Memuat...</div> : (
          <div className="space-y-3">
            {!ctx.email_ready && <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800" data-testid="po-email-not-ready"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Email keluar belum dikonfigurasi (Settings → Email). Pengiriman akan gagal sampai SMTP diatur.</div>}
            <Field label="Kepada"><Input value={form.to} onChange={set("to")} placeholder="email@supplier.com" data-testid="po-email-to" /></Field>
            <Field label="CC (opsional, pisahkan koma)"><Input value={form.cc} onChange={set("cc")} data-testid="po-email-cc" /></Field>
            <Field label="Subject"><Input value={form.subject} onChange={set("subject")} data-testid="po-email-subject" /></Field>
            <Field label="Pesan"><Textarea rows={4} value={form.message} onChange={set("message")} data-testid="po-email-message" /></Field>
            <div className="flex items-center gap-2 rounded-md border bg-muted/30 p-2 text-xs" data-testid="po-email-attachment"><Paperclip className="h-4 w-4 text-muted-foreground" /><span>Lampiran: <b>{ctx.attachment_name}</b> (salinan dokumen PO format {ctx.attachment_format}; PDF via tombol Print)</span></div>
            {ctx.logs?.length > 0 && <div className="text-[11px] text-muted-foreground">Terakhir: {ctx.logs[0].status === "sent" ? "Terkirim" : "Gagal"} ke {ctx.logs[0].to} · {fmtDateTime(ctx.logs[0].sent_at)}</div>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Batal</Button>
          <Button onClick={send} disabled={busy || !ctx} data-testid="po-email-send">{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}Kirim Email</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
