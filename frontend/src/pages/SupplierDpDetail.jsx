import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Field } from "@/components/DatePicker";
import { AttachmentPanel } from "@/components/DocMeta";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { rupiah, fmtDateTime } from "@/lib/format";
import { fmtD, dateOnly } from "@/lib/invoice";
import { DP_STATUS, dpTypeLabel } from "@/lib/supplierDp";
import { ArrowLeft, BadgeCheck, Ban, Play, Printer, Save, Paperclip } from "lucide-react";
import { toast } from "sonner";

const Info = ({ label, children, tid }) => <div><div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div><div className="mt-0.5 text-sm font-medium" data-testid={tid}>{children || "-"}</div></div>;
const ACT = { create: "Draft DP dibuat", edit: "Draft DP diubah", approve: "Pembayaran DP di-approve", cancel: "Draft DP dibatalkan", upload_file: "Bukti diunggah", delete_file: "Bukti dihapus", print: "Dicetak" };
const STATUS_LABEL = { Draft: DP_STATUS.pending, Approved: DP_STATUS.paid, Cancelled: DP_STATUS.cancelled };

function CancelDraftDialog({ pay, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { await api.post(`/supplier-dp/payments/${pay.id}/cancel`, { reason }); toast.success("Draft DP dibatalkan"); onDone(); onClose(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="supplier-dp-cancel-dialog">
        <DialogHeader><DialogTitle>Batalkan Draft {pay.no}?</DialogTitle>
          <DialogDescription>Draft tidak dihapus; riwayat dan bukti tetap tersimpan dengan status Dibatalkan. PO dapat dibuatkan draft DP baru.</DialogDescription></DialogHeader>
        <Field label="Alasan Pembatalan (wajib)"><Input value={reason} onChange={(e) => setReason(e.target.value)} data-testid="supplier-dp-cancel-reason" /></Field>
        <DialogFooter><Button variant="outline" onClick={onClose}>Kembali</Button>
          <Button variant="destructive" onClick={submit} disabled={!reason.trim() || busy} data-testid="supplier-dp-cancel-submit">Batalkan Draft</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function SupplierDpDetail() {
  const { poId } = useParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const [d, setD] = useState(null);
  const [f, setF] = useState({ payment_date: "", fund_source: "", reference: "", notes: "" });
  const [busy, setBusy] = useState("");
  const [cancel, setCancel] = useState(false);
  const canApprove = can("supplier_dp.approve");

  const apply = (data) => {
    setD(data);
    const p = data.active_payment;
    if (p) setF({ payment_date: dateOnly(p.payment_date) || data.today, fund_source: p.fund_source || "", reference: p.reference || "", notes: p.notes || "" });
  };
  const load = useCallback(() => api.get(`/supplier-dp/${poId}`).then((r) => apply(r.data)).catch((e) => { setD(false); toast.error(apiError(e.response?.data?.detail)); }), [poId]);
  useEffect(() => { load(); }, [load]);

  const run = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (r?.data) apply(r.data); if (ok) toast.success(ok); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(""); }
  };
  const pay = d?.active_payment;
  const draft = pay?.status === "Draft";
  const set = (k) => (e) => setF((c) => ({ ...c, [k]: e.target.value }));
  const start = () => run("start", () => api.post(`/supplier-dp/${poId}/draft`, {}), "Draft pembayaran DP dibuat");
  const saveDraft = () => run("save", () => api.put(`/supplier-dp/payments/${pay.id}`, f), "Draft DP disimpan");
  const approve = () => {
    if (!f.payment_date) return toast.error("Tanggal Pembayaran wajib diisi");
    if (!f.fund_source.trim()) return toast.error("Sumber Dana wajib diisi");
    return run("approve", () => api.post(`/supplier-dp/payments/${pay.id}/approve`, f), "Pembayaran DP di-approve. Status: Sudah Dibayar");
  };
  const print = async () => { try { await api.get(`/supplier-dp/payments/${pay.id}/print`); window.print(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };

  if (!can("supplier_dp.view")) return <div className="p-8 text-muted-foreground" data-testid="supplier-dp-denied">Anda tidak memiliki izin untuk melihat DP Supplier.</div>;
  if (d === false) return <div className="p-8 text-muted-foreground" data-testid="supplier-dp-detail-error">DP Supplier tidak dapat ditampilkan. <Button variant="link" onClick={() => nav("/dp-supplier")}>Kembali ke daftar</Button></div>;
  if (!d) return <div className="space-y-3 p-2"><Skeleton className="h-16 w-full" /><Skeleton className="h-40 w-full" /><Skeleton className="h-56 w-full" /></div>;
  const po = d.po || {};
  return (
    <div className="space-y-4" data-testid="supplier-dp-detail-page">
      <TransactionPageHeader type="supplier_dp" mode="view" number={d.dp_no || po.no}
        subtitle={<span className="flex flex-wrap items-center gap-2"><span>PO {po.no}</span><StatusBadge status={d.status_label} /></span>}>
        <Button variant="outline" onClick={() => nav("/dp-supplier")} data-testid="supplier-dp-back-btn"><ArrowLeft className="mr-2 h-4 w-4" />Kembali</Button>
        {pay?.status === "Approved" && can("supplier_dp.print") && <Button variant="outline" onClick={print} data-testid="supplier-dp-print-btn"><Printer className="mr-2 h-4 w-4" />Cetak</Button>}
      </TransactionPageHeader>

      <Card><CardContent className="space-y-4 pt-6">
        <h3 className="font-head text-sm font-semibold">Informasi PO</h3>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4" data-testid="supplier-dp-po-info">
          <Info label="No PO" tid="supplier-dp-po-no"><Link to={`/po/${po.id}`} className="font-mono text-primary hover:underline">{po.no}</Link></Info>
          <Info label="Tanggal PO">{fmtD(po.date)}</Info>
          <Info label="Supplier" tid="supplier-dp-supplier">{po.supplier_name}</Info>
          <Info label="Divisi">{po.division_name}</Info>
          <Info label="Nilai PO (Grand Total)" tid="supplier-dp-po-value">{rupiah(po.grand_total)}</Info>
          <Info label="Tipe DP" tid="supplier-dp-type">{dpTypeLabel(d)}</Info>
          <Info label="Nilai DP" tid="supplier-dp-amount">{rupiah(d.dp_amount)}</Info>
          <Info label="Ketentuan Pembayaran" tid="supplier-dp-terms">{[d.payment_notes, po.payment_term].filter(Boolean).join(" · ")}</Info>
        </div>
      </CardContent></Card>

      <Card><CardContent className="space-y-4 pt-6" data-testid="supplier-dp-realization">
        <div className="flex items-center justify-between"><h3 className="font-head text-sm font-semibold">Realisasi Pembayaran DP</h3>{pay && <span className="font-mono text-xs text-muted-foreground">{pay.no}</span>}</div>
        {!pay && <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground" data-testid="supplier-dp-no-payment">
          Belum ada proses pembayaran DP untuk PO ini.
          {canApprove && d.eligible && <div className="mt-3"><Button onClick={start} disabled={busy === "start"} data-testid="supplier-dp-start-btn"><Play className="mr-2 h-4 w-4" />Mulai Proses Pembayaran</Button></div>}
        </div>}
        {pay && <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Field label="Tanggal Pembayaran (wajib)"><Input type="date" value={f.payment_date} onChange={set("payment_date")} disabled={!draft || !canApprove} data-testid="supplier-dp-date-input" /></Field>
            <Field label="Sumber Dana (wajib)"><Input value={f.fund_source} onChange={set("fund_source")} disabled={!draft || !canApprove} placeholder="mis. Bank BCA Operasional / Kas Besar" data-testid="supplier-dp-fund-input" /></Field>
            <Field label="Referensi Pembayaran"><Input value={f.reference} onChange={set("reference")} disabled={!draft || !canApprove} placeholder="No. transfer / giro" data-testid="supplier-dp-reference-input" /></Field>
            <Field label="Nilai DP (mengikuti PO)"><Input value={rupiah(pay.amount)} disabled readOnly data-testid="supplier-dp-amount-readonly" /></Field>
          </div>
          <Field label="Catatan"><Textarea value={f.notes} onChange={set("notes")} disabled={!draft || !canApprove} data-testid="supplier-dp-notes-input" /></Field>
          <div className="rounded-lg border bg-muted/10 p-4" data-testid="supplier-dp-proof">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Paperclip className="h-4 w-4 text-muted-foreground" />Bukti Pembayaran {draft && <span className="text-xs font-normal text-muted-foreground">(wajib sebelum Approve)</span>}</div>
            <AttachmentPanel entity="supplier_dp_payment" entityId={pay.id} multiple canUpload={draft && canApprove} canDelete={draft && canApprove} />
          </div>
          {pay.status === "Approved" && <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300" data-testid="supplier-dp-approved-info">
            <BadgeCheck className="mr-1 inline h-4 w-4" />Sudah Dibayar — di-approve oleh {pay.approved_by_name || pay.approved_by} pada {fmtDateTime(pay.approved_at)}.</div>}
          {draft && canApprove && <div className="flex flex-wrap justify-end gap-2 no-print">
            <Button variant="outline" onClick={() => nav("/dp-supplier")} data-testid="supplier-dp-cancel-btn">Batal</Button>
            <Button variant="outline" className="text-destructive" onClick={() => setCancel(true)} data-testid="supplier-dp-cancel-draft-btn"><Ban className="mr-2 h-4 w-4" />Batalkan Draft</Button>
            <Button variant="outline" onClick={saveDraft} disabled={!!busy} data-testid="supplier-dp-save-btn"><Save className="mr-2 h-4 w-4" />Simpan Draft</Button>
            <Button onClick={approve} disabled={!!busy} data-testid="supplier-dp-approve-btn"><BadgeCheck className="mr-2 h-4 w-4" />{busy === "approve" ? "Memproses..." : "Approve Pembayaran DP"}</Button>
          </div>}
        </>}
      </CardContent></Card>

      {pay?.status === "Approved" && <Card><CardContent className="space-y-3 pt-6">
        <h3 className="font-head text-sm font-semibold">Pemakaian DP di Invoice Vendor</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {[["DP Sudah Dibayar", d.paid_amount, "supplier-dp-paid"], ["DP Sudah Digunakan", d.dp_used, "supplier-dp-used"], ["DP Tersedia", d.dp_available, "supplier-dp-available"]].map(([l, v, t]) =>
            <div key={t} className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">{l}</div><div className="font-head text-lg font-bold tabular-nums" data-testid={t}>{rupiah(v)}</div></div>)}
        </div>
        <div className="overflow-x-auto rounded-lg border"><table className="w-full text-sm" data-testid="supplier-dp-usage">
          <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"><th className="p-2.5">Invoice</th><th className="p-2.5">No. Faktur</th><th className="p-2.5">Tanggal</th><th className="p-2.5 text-right">Alokasi DP</th></tr></thead>
          <tbody>{(d.invoice_usage || []).length === 0 && <tr><td colSpan={4} className="p-5 text-center text-muted-foreground">DP belum dialokasikan ke Invoice Vendor</td></tr>}
            {(d.invoice_usage || []).map((u) => <tr key={u.id} className="border-t"><td className="p-2.5 font-mono text-xs"><Link className="text-primary hover:underline" to={`/invoice/${u.invoice_id}`}>{u.invoice_sys_no}</Link></td>
              <td className="p-2.5">{u.invoice_no}</td><td className="p-2.5 text-xs">{fmtD(u.invoice_date)}</td><td className="p-2.5 text-right tabular-nums">{rupiah(u.amount)}</td></tr>)}</tbody>
        </table></div>
      </CardContent></Card>}

      <Card className="no-print"><CardContent className="space-y-3 pt-6">
        <h3 className="font-head text-sm font-semibold">Riwayat Pembayaran DP</h3>
        <div className="overflow-x-auto rounded-lg border"><table className="w-full text-sm" data-testid="supplier-dp-payments">
          <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{["No. DP", "Tanggal", "Sumber Dana", "Nilai", "Status", "Keterangan"].map((h) => <th key={h} className={`p-2.5 ${h === "Nilai" ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
          <tbody>{(d.payments || []).length === 0 && <tr><td colSpan={6} className="p-5 text-center text-muted-foreground">Belum ada riwayat</td></tr>}
            {(d.payments || []).map((p) => <tr key={p.id} className="border-t"><td className="p-2.5 font-mono text-xs">{p.no}</td><td className="p-2.5 text-xs">{fmtD(p.payment_date)}</td>
              <td className="p-2.5">{p.fund_source || "-"}</td><td className="p-2.5 text-right tabular-nums">{rupiah(p.amount)}</td><td className="p-2.5"><StatusBadge status={STATUS_LABEL[p.status] || p.status} /></td>
              <td className="p-2.5 text-xs">{p.cancel_reason ? `Alasan batal: ${p.cancel_reason}` : p.reference || "-"}</td></tr>)}</tbody>
        </table></div>
        <div className="space-y-2" data-testid="supplier-dp-history">{(d.history || []).map((h) => (
          <div key={h.id} className="rounded-lg border p-2.5 text-xs"><span className="font-semibold">{ACT[h.action] || h.action}</span> <span className="text-muted-foreground">{h.doc_no} · {h.user_name || h.user} · {fmtDateTime(h.at)}</span>{h.reason && <div className="mt-1">Alasan: {h.reason}</div>}</div>))}</div>
      </CardContent></Card>
      {cancel && pay && <CancelDraftDialog pay={pay} onClose={() => setCancel(false)} onDone={load} />}
    </div>
  );
}
