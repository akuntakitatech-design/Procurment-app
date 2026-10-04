import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { PaymentPanel } from "@/components/invoice/PaymentPanel";
import { AttachmentPanel } from "@/components/DocMeta";
import { rupiah, fmtDateTime } from "@/lib/format";
import { fmtD } from "@/lib/invoice";
import { ArrowLeft, Pencil, Printer, Trash2 } from "lucide-react";
import { toast } from "sonner";

const ACT = { create: "Invoice dicatat", edit: "Invoice diubah", delete: "Invoice dihapus", payment: "Pembayaran dicatat", payment_cancel: "Pembayaran dibatalkan", upload_file: "Lampiran diunggah", delete_file: "Lampiran dihapus" };
const Info = ({ label, children, tid }) => <div><div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div><div className="mt-0.5 text-sm font-medium" data-testid={tid}>{children || "-"}</div></div>;
const Big = ({ label, value, tone, tid }) => <div className="rounded-xl border bg-card p-4"><div className="text-xs text-muted-foreground">{label}</div><div className={`mt-1 font-head text-2xl font-bold tabular-nums ${tone || ""}`} data-testid={tid}>{rupiah(value)}</div></div>;

function Allocations({ rows }) {
  const head = ["No DO", "Tgl DO", "MRO", "RO", "PO", "SPK", "Proyek", "Divisi", "Nilai DO", "Alokasi Invoice", "Sisa DO", "Status Penagihan"];
  return (
    <div className="overflow-x-auto rounded-lg border" data-testid="invoice-allocations">
      <table className="w-full min-w-[1300px] text-sm">
        <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{head.map((x, i) => <th key={x} className={`p-2.5 ${i >= 8 && i <= 10 ? "text-right" : ""}`}>{x}</th>)}</tr></thead>
        <tbody>{rows.map((a) => (
          <tr key={a.id} className="border-t" data-testid={`invoice-alloc-row-${a.do_no}`}>
            <td className="p-2.5 font-mono text-xs font-semibold"><Link to={`/do/${a.do_id}`} className="text-primary hover:underline">{a.do_no}</Link></td>
            <td className="p-2.5 text-xs">{fmtD(a.do_date)}</td>
            {["trace_mro", "trace_ro", "trace_po", "trace_spk", "trace_project", "trace_division"].map((k) => <td key={k} className="p-2.5 text-xs">{a[k] || "-"}</td>)}
            <td className="p-2.5 text-right tabular-nums">{rupiah(a.do_value_now)}</td>
            <td className="p-2.5 text-right tabular-nums font-semibold">{rupiah(a.amount)}</td>
            <td className="p-2.5 text-right tabular-nums">{rupiah(a.remaining_now)}</td>
            <td className="p-2.5"><StatusBadge status={a.billing_status} /></td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

function History({ rows }) {
  return <div className="space-y-2" data-testid="invoice-history">{(rows || []).map((h) => (
    <div key={h.id} className="rounded-lg border p-2.5 text-xs">
      <div className="flex flex-wrap gap-2"><span className="font-semibold">{ACT[h.action] || h.action}</span><span className="text-muted-foreground">{h.user_name || h.user} · {fmtDateTime(h.at)}</span></div>
      {h.reason && <div className="mt-1">Alasan: {h.reason}</div>}
      {h.after && h.action.startsWith("payment") && <div className="mt-1 text-muted-foreground">{Object.entries(h.after).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "number" ? rupiah(v) : v}`).join(" · ")}</div>}
    </div>))}</div>;
}

export default function InvoiceDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const [inv, setInv] = useState(null);
  const [del, setDel] = useState(false);
  const load = useCallback(() => api.get(`/vendor-invoices/${id}`).then((r) => setInv(r.data)).catch((e) => { setInv(false); toast.error(apiError(e.response?.data?.detail)); }), [id]);
  useEffect(() => { load(); }, [load]);
  const print = async () => { try { await api.get(`/vendor-invoices/${id}/print`); window.print(); } catch (e) { toast.error(apiError(e.response?.data?.detail)); } };
  const remove = async () => { try { await api.delete(`/vendor-invoices/${id}`); toast.success("Invoice Vendor dihapus"); nav("/invoice"); } catch (e) { toast.error(apiError(e.response?.data?.detail)); setDel(false); } };
  if (inv === false) return <div className="p-8 text-muted-foreground" data-testid="invoice-detail-error">Invoice tidak dapat ditampilkan.</div>;
  if (!inv) return <div className="p-8 text-muted-foreground">Memuat...</div>;
  return (
    <div className="space-y-4" data-testid="invoice-detail-page">
      <TransactionPageHeader type="invoice" mode="view" number={inv.no || inv.invoice_no} subtitle={<span className="flex flex-wrap items-center gap-2">{inv.invoice_no && <span data-testid="invoice-detail-vendor-no">No. Faktur {inv.invoice_no}</span>}{inv.invoice_no && " · "}<StatusBadge status={inv.status} /><StatusBadge status={inv.payment_status} />{["Lewat Jatuh Tempo", "Jatuh Tempo"].includes(inv.due_state) && <StatusBadge status={inv.due_state} />}</span>}>
        <Button variant="outline" onClick={() => nav("/invoice")}><ArrowLeft className="mr-2 h-4 w-4" />Kembali</Button>
        {can("invoice.print") && <Button variant="outline" onClick={print} data-testid="invoice-print-btn"><Printer className="mr-2 h-4 w-4" />Cetak</Button>}
        {can("invoice.edit") && <Button variant="outline" onClick={() => nav(`/invoice/${id}/edit`)} data-testid="invoice-edit-btn"><Pencil className="mr-2 h-4 w-4" />Edit</Button>}
        {can("invoice.delete") && <Button variant="outline" className="text-destructive" onClick={() => setDel(true)} data-testid="invoice-delete-btn"><Trash2 className="mr-2 h-4 w-4" />Hapus</Button>}
      </TransactionPageHeader>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Big label="Nilai Invoice" value={inv.amount} tid="invoice-detail-amount" />
        <Big label="Sudah Dibayar" value={inv.paid_total} tone="text-emerald-600" tid="invoice-detail-paid" />
        <Big label="Sisa" value={inv.remaining} tone={inv.remaining > 0 ? "text-rose-600" : ""} tid="invoice-detail-remaining" />
      </div>
      <Card><CardContent className="grid grid-cols-2 gap-4 pt-6 md:grid-cols-4">
        <Info label="Supplier" tid="invoice-detail-supplier">{inv.supplier_name}</Info>
        <Info label="No Invoice">{inv.invoice_no}</Info>
        <Info label="Tanggal Invoice">{fmtD(inv.invoice_date)}</Info>
        <Info label="Tanggal Invoice Diterima">{fmtD(inv.received_date)}</Info>
        <Info label="Jatuh Tempo" tid="invoice-detail-due">{fmtD(inv.due_date)}</Info>
        <Info label="PO">{inv.trace_po}</Info>
        <Info label="DO">{inv.do_nos}</Info>
        <Info label="SPK">{inv.trace_spk}</Info>
        <Info label="Proyek">{inv.trace_project}</Info>
        <Info label="Divisi">{inv.trace_division}</Info>
        <Info label="DPP">{rupiah(inv.dpp)}</Info>
        <Info label="Pajak">{rupiah(inv.tax_amount)}</Info>
        <Info label="Total Alokasi DO">{rupiah(inv.alloc_total)}</Info>
        <Info label="Selisih" tid="invoice-detail-diff"><span className="flex items-center gap-2">{rupiah(inv.diff)}<StatusBadge status={inv.diff_status} /></span></Info>
        {inv.diff_reason && <Info label="Alasan Selisih">{inv.diff_reason}</Info>}
        <Info label="Catatan">{inv.notes}</Info>
      </CardContent></Card>
      <Card><CardContent className="space-y-3 pt-6"><h3 className="font-head text-sm font-semibold">Alokasi DO & Traceability (Invoice → DO → PO → RO → MRO)</h3><Allocations rows={inv.allocations || []} /></CardContent></Card>
      <Card><CardContent className="pt-6"><PaymentPanel inv={inv} canPay={can("invoice.pay")} onChanged={load} /></CardContent></Card>
      <Card className="no-print"><CardContent className="space-y-3 pt-6"><h3 className="font-head text-sm font-semibold">Lampiran Invoice</h3><div data-testid="invoice-attachments"><AttachmentPanel entity="invoice" entityId={inv.id} multiple canUpload={can("invoice.edit")} canDelete={can("invoice.edit")} /></div></CardContent></Card>
      <Card className="no-print"><CardContent className="space-y-3 pt-6"><h3 className="font-head text-sm font-semibold">Riwayat Perubahan & Pembayaran</h3><History rows={inv.history} /></CardContent></Card>
      <AlertDialog open={del} onOpenChange={setDel}>
        <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Hapus Invoice {inv.invoice_no}?</AlertDialogTitle>
          <AlertDialogDescription>Alokasi DO akan dilepas sehingga DO kembali dapat ditagihkan. Invoice dengan pembayaran aktif tidak dapat dihapus.</AlertDialogDescription></AlertDialogHeader>
          <AlertDialogFooter><AlertDialogCancel>Batal</AlertDialogCancel><AlertDialogAction onClick={remove} data-testid="invoice-delete-confirm">Hapus</AlertDialogAction></AlertDialogFooter></AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
