import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { DataTable } from "@/components/invoice/DataTable";
import { Combobox } from "@/components/Combobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useServerList } from "@/lib/serverList";
import { optsOf } from "@/lib/invoice";
import { Plus } from "lucide-react";

const COLS = [
  { key: "no", label: "No. Transmittal", mono: true },
  { key: "date", label: "Tanggal", date: true },
  { key: "destination", label: "Tujuan / Departemen" },
  { key: "sender_name", label: "Pengirim" },
  { key: "receiver_name", label: "Penerima" },
  { key: "suppliers", label: "Supplier", wrap: true },
  { key: "invoice_count", label: "Jml Invoice", num: true },
  { key: "total_amount", label: "Total Nilai", money: true, num: true },
  { key: "status", label: "Status", status: true },
];

export default function InvoiceTransmittal() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const list = useServerList("/invoice-transmittals", { f_status: status, date_from: from, date_to: to }, { facets: "status" });
  useEffect(() => { list.setQ(q); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-5" data-testid="transmittal-list-page">
      <TransactionPageHeader type="transmittal" mode="list">
        {can("transmittal.create") && <Button onClick={() => nav("/transmittal/new")} data-testid="transmittal-create-btn"><Plus className="mr-2 h-4 w-4" />Buat Transmittal</Button>}
      </TransactionPageHeader>
      <DataTable
        columns={COLS}
        server={list}
        testidPrefix="transmittal"
        countLabel="transmittal"
        minWidth={1300}
        emptyText="Belum ada Transmittal"
        searchPlaceholder="Cari nomor, tujuan, pengirim, penerima, supplier..."
        onOpen={(r) => nav(`/transmittal/${r.id}`)}
        filters={<>
          <div className="w-44"><Combobox options={optsOf(list.facets.status || [], "Semua Status")} value={status} onChange={setStatus} placeholder="Semua Status" testid="filter-transmittal-status" dense /></div>
          <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">Tanggal
            <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-11 sm:h-9 sm:w-36" aria-label="Tanggal dari" data-testid="transmittal-date-from" />s/d
            <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-11 sm:h-9 sm:w-36" aria-label="Tanggal sampai" data-testid="transmittal-date-to" /></div>
        </>}
      />
    </div>
  );
}
