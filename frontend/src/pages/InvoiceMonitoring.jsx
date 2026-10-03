import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { DataTable } from "@/components/invoice/DataTable";
import { InvoiceSummary } from "@/components/invoice/InvoiceSummary";
import { fmtD, splitVals, optsOf, hasVal, dateOnly } from "@/lib/invoice";
import { Plus } from "lucide-react";
import { toast } from "sonner";

const INV_COLS = [
  { key: "supplier_name", label: "Supplier" },
  { key: "invoice_no", label: "No Invoice", mono: true },
  { key: "trace_po", label: "PO", wrap: true },
  { key: "do_nos", label: "DO", wrap: true },
  { key: "trace_spk", label: "SPK", wrap: true },
  { key: "trace_project", label: "Proyek", wrap: true },
  { key: "trace_division", label: "Divisi", wrap: true },
  { key: "invoice_date", label: "Tgl Invoice", date: true },
  { key: "due_date", label: "Jatuh Tempo", render: (r) => <div className="space-y-1"><div>{fmtD(r.due_date)}</div>{["Lewat Jatuh Tempo", "Jatuh Tempo"].includes(r.due_state) && <StatusBadge status={r.due_state} />}</div> },
  { key: "amount", label: "Nilai Invoice", money: true, num: true },
  { key: "paid_total", label: "Sudah Dibayar", money: true, num: true },
  { key: "remaining", label: "Sisa", money: true, num: true },
  { key: "status", label: "Status Invoice", status: true },
  { key: "payment_status", label: "Status Pembayaran", status: true },
];
const DO_COLS = [
  { key: "do_no", label: "No DO", mono: true },
  { key: "date", label: "Tgl DO", date: true },
  { key: "supplier_name", label: "Supplier" },
  { key: "po_nos", label: "PO", wrap: true },
  { key: "spk", label: "SPK", wrap: true },
  { key: "project", label: "Proyek", wrap: true },
  { key: "division", label: "Divisi", wrap: true },
  { key: "do_value", label: "Nilai DO", money: true, num: true },
  { key: "billed", label: "Sudah Ditagihkan", money: true, num: true },
  { key: "remaining", label: "Sisa Belum Ditagihkan", money: true, num: true },
  { key: "billing_status", label: "Status Penagihan", status: true },
];
const F = ({ children }) => <div className="w-44">{children}</div>;

function useFilters(rows, defs) {
  const [f, setF] = useState({});
  const opts = useMemo(() => Object.fromEntries(defs.map(([k, , all]) => [k, optsOf(splitVals(rows, k), all)])), [rows, defs]);
  const ui = defs.map(([k, , all]) => <F key={k}><Combobox options={opts[k]} value={f[k] || ""} onChange={(v) => setF((c) => ({ ...c, [k]: v }))} placeholder={all} testid={`filter-${k}`} dense /></F>);
  const apply = (r) => defs.every(([k]) => hasVal(r, k, f[k]));
  return { ui, apply, f, setF };
}

const INV_FILTERS = [["supplier_name", 0, "Semua Supplier"], ["trace_division", 0, "Semua Divisi"], ["trace_project", 0, "Semua Proyek"], ["trace_spk", 0, "Semua SPK"], ["trace_po", 0, "Semua PO"], ["do_nos", 0, "Semua DO"], ["status", 0, "Semua Status Invoice"], ["payment_status", 0, "Semua Status Pembayaran"], ["due_state", 0, "Semua Jatuh Tempo"]];
const DO_FILTERS = [["supplier_name", 0, "Semua Supplier"], ["division", 0, "Semua Divisi"], ["project", 0, "Semua Proyek"], ["spk", 0, "Semua SPK"], ["billing_status", 0, "Semua Status Penagihan"]];

export default function InvoiceMonitoring() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [invs, setInvs] = useState(null);
  const [dos, setDos] = useState(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  useEffect(() => {
    api.get("/vendor-invoices").then((r) => setInvs(r.data)).catch((e) => { setInvs([]); toast.error(apiError(e.response?.data?.detail)); });
    api.get("/vendor-invoices/do-billing").then((r) => setDos(r.data)).catch(() => setDos([]));
  }, []);
  const fi = useFilters(invs || [], INV_FILTERS);
  const fd = useFilters(dos || [], DO_FILTERS);
  const inRange = (d) => (!from || dateOnly(d) >= from) && (!to || dateOnly(d) <= to);
  const invRows = (invs || []).filter((r) => fi.apply(r) && inRange(r.invoice_date));
  const doRows = (dos || []).filter((r) => fd.apply(r) && inRange(r.date));
  const range = <div className="flex items-center gap-1 text-xs text-muted-foreground">Tanggal
    <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 w-36" data-testid="filter-date-from" />s/d
    <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 w-36" data-testid="filter-date-to" /></div>;
  return (
    <div className="space-y-5" data-testid="invoice-monitoring-page">
      <PageHeader title="Monitoring Invoice Vendor" subtitle="DO → Invoice Diterima → Invoice Dibayar. Pencatatan invoice tidak mengubah PO, DO, SPK, stok maupun Moving Average.">
        {can("invoice.create") && <Button onClick={() => nav("/invoice/new")} data-testid="invoice-create-btn"><Plus className="mr-2 h-4 w-4" />Catat Invoice</Button>}
      </PageHeader>
      <InvoiceSummary />
      <Tabs defaultValue="invoice">
        <TabsList><TabsTrigger value="invoice" data-testid="tab-invoice">Invoice Vendor</TabsTrigger><TabsTrigger value="do" data-testid="tab-do-billing">Status Penagihan DO</TabsTrigger></TabsList>
        <TabsContent value="invoice" className="mt-4">
          <DataTable columns={INV_COLS} rows={invRows} testidPrefix="invoice" countLabel="invoice" minWidth={1700}
            emptyText={invs === null ? "Memuat..." : "Belum ada invoice"} searchPlaceholder="Cari supplier, no invoice, PO, DO, SPK, proyek..."
            onOpen={(r) => nav(`/invoice/${r.id}`)} filters={<>{fi.ui}{range}</>} />
        </TabsContent>
        <TabsContent value="do" className="mt-4">
          <DataTable columns={DO_COLS} rows={doRows} testidPrefix="do-billing" countLabel="DO" minWidth={1400}
            emptyText={dos === null ? "Memuat..." : "Belum ada DO"} searchPlaceholder="Cari no DO, supplier, PO, SPK, proyek..."
            onOpen={(r) => nav(`/do/${r.do_id}`)} filters={<>{fd.ui}{range}</>} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
