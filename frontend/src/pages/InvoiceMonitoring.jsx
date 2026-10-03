import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { DataTable } from "@/components/invoice/DataTable";
import { InvoiceSummary } from "@/components/invoice/InvoiceSummary";
import { fmtD, optsOf } from "@/lib/invoice";
import { useServerList } from "@/lib/serverList";
import { Plus } from "lucide-react";

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

const INV_FILTERS = [["supplier_name", 0, "Semua Supplier"], ["trace_division", 0, "Semua Divisi"], ["trace_project", 0, "Semua Proyek"], ["trace_spk", 0, "Semua SPK"], ["trace_po", 0, "Semua PO"], ["do_nos", 0, "Semua DO"], ["status", 0, "Semua Status Invoice"], ["payment_status", 0, "Semua Status Pembayaran"], ["due_state", 0, "Semua Jatuh Tempo"]];
const DO_FILTERS = [["supplier_name", 0, "Semua Supplier"], ["division", 0, "Semua Divisi"], ["project", 0, "Semua Proyek"], ["spk", 0, "Semua SPK"], ["billing_status", 0, "Semua Status Penagihan"]];

function useFilterUI(defs, facets) {
  const [f, setF] = useState({});
  const ui = defs.map(([k, , all]) => <F key={k}><Combobox options={optsOf(facets[k] || [], all)} value={f[k] || ""} onChange={(v) => setF((c) => ({ ...c, [k]: v }))} placeholder={all} testid={`filter-${k}`} dense /></F>);
  const params = Object.fromEntries(defs.map(([k]) => [`f_${k}`, f[k] || ""]));
  return { ui, params };
}

function RangeUI({ from, to, setFrom, setTo }) {
  return <div className="flex items-center gap-1 text-xs text-muted-foreground">Tanggal
    <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 w-36" data-testid="filter-date-from" />s/d
    <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 w-36" data-testid="filter-date-to" /></div>;
}

// Satu tab = satu list server-side (search/filter/sort/pagination di backend). Tab DO baru dimuat saat dibuka.
function ServerTable({ url, defs, cols, from, to, setFrom, setTo, ...rest }) {
  const [fParams, setFParams] = useState(() => Object.fromEntries(defs.map(([k]) => [`f_${k}`, ""])));
  const list = useServerList(url, { ...fParams, date_from: from, date_to: to }, { facets: defs.map(([k]) => k).join(",") });
  const fx = useFilterUI(defs, list.facets);
  const key = JSON.stringify(fx.params);
  useEffect(() => { setFParams(JSON.parse(key)); }, [key]);
  return <DataTable columns={cols} server={list} filters={<>{fx.ui}<RangeUI from={from} to={to} setFrom={setFrom} setTo={setTo} /></>} {...rest} />;
}

export default function InvoiceMonitoring() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [tab, setTab] = useState("invoice");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const rp = { from, to, setFrom, setTo };
  return (
    <div className="space-y-5" data-testid="invoice-monitoring-page">
      <PageHeader title="Monitoring Invoice Vendor" subtitle="DO → Invoice Diterima → Invoice Dibayar. Pencatatan invoice tidak mengubah PO, DO, SPK, stok maupun Moving Average.">
        {can("invoice.create") && <Button onClick={() => nav("/invoice/new")} data-testid="invoice-create-btn"><Plus className="mr-2 h-4 w-4" />Catat Invoice</Button>}
      </PageHeader>
      <InvoiceSummary />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList><TabsTrigger value="invoice" data-testid="tab-invoice">Invoice Vendor</TabsTrigger><TabsTrigger value="do" data-testid="tab-do-billing">Status Penagihan DO</TabsTrigger></TabsList>
        <TabsContent value="invoice" className="mt-4">
          <ServerTable url="/vendor-invoices" defs={INV_FILTERS} cols={INV_COLS} {...rp} testidPrefix="invoice" countLabel="invoice" minWidth={1700}
            emptyText="Belum ada invoice" searchPlaceholder="Cari supplier, no invoice, PO, DO, SPK, proyek..." onOpen={(r) => nav(`/invoice/${r.id}`)} />
        </TabsContent>
        <TabsContent value="do" className="mt-4">
          {tab === "do" && <ServerTable url="/vendor-invoices/do-billing" defs={DO_FILTERS} cols={DO_COLS} {...rp} testidPrefix="do-billing" countLabel="DO" minWidth={1400}
            emptyText="Belum ada DO" searchPlaceholder="Cari no DO, supplier, PO, SPK, proyek..." onOpen={(r) => nav(`/do/${r.do_id}`)} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}
