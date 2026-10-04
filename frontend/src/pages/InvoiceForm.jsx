import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useMasters } from "@/hooks/useMasters";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { DoAllocationTable } from "@/components/invoice/DoAllocationTable";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { rupiah, toNum } from "@/lib/format";
import { todayDate, dateOnly, round2, TOL } from "@/lib/invoice";
import { AttachmentPanel, uploadPendingAttachments } from "@/components/DocMeta";
import { ArrowLeft, Paperclip } from "lucide-react";
import { toast } from "sonner";

const EMPTY = { supplier_id: "", invoice_no: "", invoice_date: todayDate(), received_date: todayDate(), due_date: "", tax_amount: "", amount: "", diff_reason: "", notes: "" };

function Totals({ allocTotal, amount, diff }) {
  const ok = Math.abs(diff) < TOL;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-4" data-testid="invoice-totals">
      <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">Total Alokasi DO</div><div className="font-head text-lg font-bold tabular-nums" data-testid="invoice-alloc-total">{rupiah(allocTotal)}</div></div>
      <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">Nilai Invoice Vendor</div><div className="font-head text-lg font-bold tabular-nums" data-testid="invoice-amount-total">{rupiah(amount)}</div></div>
      <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">Selisih</div><div className={`font-head text-lg font-bold tabular-nums ${ok ? "" : "text-orange-600"}`} data-testid="invoice-diff">{rupiah(diff)}</div></div>
      <div className="flex items-center rounded-lg border p-3"><StatusBadge status={ok ? "Sesuai" : "Ada Selisih"} /></div>
    </div>
  );
}

export default function InvoiceForm() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const masters = useMasters(["suppliers"]);
  const [h, setH] = useState(EMPTY);
  const [rows, setRows] = useState([]);
  const [alloc, setAlloc] = useState({});
  const [loading, setLoading] = useState(false);
  const [autoAmount, setAutoAmount] = useState(!id);
  const [pending, setPending] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.get(`/vendor-invoices/${id}`).then((r) => {
      const d = r.data;
      setH({ ...EMPTY, ...d, invoice_date: dateOnly(d.invoice_date), received_date: dateOnly(d.received_date), due_date: dateOnly(d.due_date) });
      setAlloc(Object.fromEntries((d.allocations || []).map((a) => [a.do_id, a.amount])));
    }).catch((e) => toast.error(apiError(e.response?.data?.detail)));
  }, [id]);
  useEffect(() => {
    if (!h.supplier_id) { setRows([]); return; }
    setLoading(true);
    api.get(`/vendor-invoices/eligible-dos?supplier_id=${h.supplier_id}${id ? `&invoice_id=${id}` : ""}`)
      .then((r) => setRows(r.data)).catch((e) => toast.error(apiError(e.response?.data?.detail))).finally(() => setLoading(false));
  }, [h.supplier_id, id]);

  const allocTotal = useMemo(() => round2(Object.values(alloc).reduce((s, v) => s + toNum(v), 0)), [alloc]);
  const taxAuto = useMemo(() => round2(rows.reduce((s, r) => s + (alloc[r.do_id] !== undefined && r.do_value ? toNum(r.do_tax) * toNum(alloc[r.do_id]) / toNum(r.do_value) : 0), 0)), [rows, alloc]);
  useEffect(() => { if (autoAmount) setH((c) => ({ ...c, amount: allocTotal ? String(allocTotal) : "", tax_amount: allocTotal ? String(taxAuto) : "" })); }, [autoAmount, allocTotal, taxAuto]);
  const amount = round2(h.amount), tax = round2(h.tax_amount), diff = round2(amount - allocTotal);
  const set = (k) => (e) => setH((c) => ({ ...c, [k]: e.target.value }));
  const setMoney = (k) => (e) => { setAutoAmount(false); setH((c) => ({ ...c, [k]: e.target.value })); };

  const save = async () => {
    if (!h.supplier_id) return toast.error("Supplier wajib dipilih");
    if (!String(h.invoice_no || "").trim()) return toast.error("No Invoice wajib diisi");
    if (!h.due_date) return toast.error("Jatuh Tempo wajib diisi");
    if (!Object.keys(alloc).length) return toast.error("Pilih minimal satu DO");
    if (Math.abs(diff) >= TOL && !String(h.diff_reason || "").trim()) return toast.error("Total Alokasi DO berbeda dengan Nilai Invoice. Alasan Selisih wajib diisi.");
    const body = { supplier_id: h.supplier_id, invoice_no: h.invoice_no, invoice_date: h.invoice_date, received_date: h.received_date, due_date: h.due_date,
      amount, tax_amount: tax, dpp: round2(amount - tax), diff_reason: h.diff_reason, notes: h.notes,
      allocations: Object.entries(alloc).map(([do_id, v]) => ({ do_id, amount: round2(v) })) };
    setSaving(true);
    try {
      const r = id ? await api.put(`/vendor-invoices/${id}`, body) : await api.post("/vendor-invoices", body);
      const { failed } = pending.length ? await uploadPendingAttachments("invoice", r.data.id, pending) : { failed: [] };
      if (failed.length) toast.error(`Invoice tersimpan, tetapi lampiran "${failed.map((f) => f.name).join(", ")}" gagal diunggah. Silakan unggah ulang dari halaman invoice.`);
      else toast.success(id ? "Invoice Vendor diperbarui" : "Invoice Vendor dicatat");
      nav(`/invoice/${r.data.id}`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  if (!can(id ? "invoice.edit" : "invoice.create")) return <div className="p-8 text-muted-foreground" data-testid="invoice-form-denied">Anda tidak memiliki izin untuk {id ? "mengubah" : "menambah"} Invoice Vendor.</div>;
  return (
    <div data-testid="invoice-form-page">
      <TransactionPageHeader type="invoice" mode={id ? "edit" : "new"} number={h.no || h.invoice_no} subtitle="Pilih DO dari supplier yang sama, tentukan alokasi per DO, lalu cocokkan dengan nilai faktur vendor.">
        <Button variant="outline" onClick={() => nav(id ? `/invoice/${id}` : "/invoice")}><ArrowLeft className="mr-2 h-4 w-4" />Kembali</Button>
        <Button onClick={save} disabled={saving} data-testid="invoice-save-btn">{saving ? "Menyimpan..." : "Simpan Invoice"}</Button>
      </TransactionPageHeader>
      <Card><CardContent className="space-y-6 pt-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="Supplier"><div data-testid="invoice-supplier">{id ? <Input value={h.supplier_name || ""} disabled /> :
            <Combobox options={masters.opts("suppliers", (d) => d.name)} value={h.supplier_id} onChange={(v) => { setAlloc({}); setAutoAmount(true); setH((c) => ({ ...c, supplier_id: v })); }} testid="invoice-supplier-combobox" />}</div></Field>
          <Field label="No Invoice"><Input value={h.invoice_no} onChange={set("invoice_no")} data-testid="invoice-no-input" /></Field>
          <Field label="Tanggal Invoice"><Input type="date" value={h.invoice_date} onChange={set("invoice_date")} data-testid="invoice-date-input" /></Field>
          <Field label="Tanggal Invoice Diterima"><Input type="date" value={h.received_date} onChange={set("received_date")} data-testid="invoice-received-date-input" /></Field>
          <Field label="Jatuh Tempo"><Input type="date" value={h.due_date} onChange={set("due_date")} data-testid="invoice-due-date-input" /></Field>
          <Field label="Pajak (bila relevan)"><Input type="number" step="0.01" value={h.tax_amount} onChange={setMoney("tax_amount")} data-testid="invoice-tax-input" /></Field>
          <Field label="Nilai Invoice (sesuai faktur vendor)"><Input type="number" step="0.01" value={h.amount} onChange={setMoney("amount")} data-testid="invoice-amount-input" /></Field>
          <Field label="DPP"><Input value={rupiah(round2(amount - tax))} disabled data-testid="invoice-dpp" /></Field>
        </div>
        <div>
          <h3 className="mb-2 font-head text-sm font-semibold">DO yang Ditagihkan</h3>
          {!h.supplier_id ? <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">Pilih Supplier untuk menampilkan DO yang dapat ditagihkan</div>
            : <DoAllocationTable rows={rows} alloc={alloc} setAlloc={setAlloc} loading={loading} />}
        </div>
        <Totals allocTotal={allocTotal} amount={amount} diff={diff} />
        {Math.abs(diff) >= TOL && <Field label="Alasan Selisih (wajib)"><Textarea value={h.diff_reason} onChange={set("diff_reason")} data-testid="invoice-diff-reason" /></Field>}
        <Field label="Catatan"><Textarea value={h.notes} onChange={set("notes")} data-testid="invoice-notes" /></Field>
        <div className="rounded-lg border bg-muted/10 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Paperclip className="h-4 w-4 text-muted-foreground" />Lampiran Invoice (Invoice, Faktur Pajak, Rekap Tagihan, Surat Jalan, dll.)</div>
          <AttachmentPanel entity="invoice" entityId={id} pending={pending} onPendingChange={setPending} multiple />
        </div>
      </CardContent></Card>
    </div>
  );
}
