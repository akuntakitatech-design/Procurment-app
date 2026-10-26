import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { DataTable } from "@/components/invoice/DataTable";
import { Combobox } from "@/components/Combobox";
import { ListExportButtons } from "@/components/ListExportButtons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useServerList } from "@/lib/serverList";
import { optsOf } from "@/lib/invoice";
import api, { apiError } from "@/lib/api";
import { openTransmittalPrintMany } from "@/lib/transmittalPrint";
import { companyLogoPath, printImage } from "@/lib/printAssets";
import { FileText, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

const BASE_COLS = [
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

// Kunci laporan Excel daftar transmittal (backend/reporting/reports_txn.py). PDF memakai layout dokumen
// landscape (satu halaman per transmittal), bukan tabel laporan, sehingga tidak didaftarkan di LIST_EXPORT_KEYS.
const REPORT_KEY = "txn-transmittal";
// Export PDF massal dibatasi agar dokumen cetak tetap wajar (1 transmittal = 1 halaman).
const PDF_MAX = 100;

export default function InvoiceTransmittal() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState([]);
  const [busyPdf, setBusyPdf] = useState(false);
  const list = useServerList("/invoice-transmittals", { f_status: status, date_from: from, date_to: to }, { facets: "status" });
  useEffect(() => { list.setQ(q); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const canEdit = can("transmittal.edit");
  const canDelete = can("transmittal.delete");
  const canPrint = can("transmittal.print");

  const remove = async (r) => {
    if (!window.confirm(`Hapus Transmittal ${r.no}? Tindakan ini tidak dapat dibatalkan.`)) return;
    try {
      await api.delete(`/invoice-transmittals/${r.id}`);
      setSel((cur) => cur.filter((id) => id !== r.id));
      toast.success("Transmittal dihapus");
      list.reload();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  const columns = useMemo(() => {
    if (!canEdit && !canDelete) return BASE_COLS;
    return [...BASE_COLS, {
      key: "actions", label: "Aksi", num: true,
      render: (r) => {
        const draft = r.status === "Draft";
        return (
          <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
            {canEdit && (
              <Button size="sm" variant="ghost" className="h-8 px-2" disabled={!draft} title={draft ? "Ubah transmittal" : "Hanya Draft yang dapat diubah"}
                onClick={() => nav(`/transmittal/${r.id}`)} data-testid={`transmittal-edit-${r.no}`}>
                <Pencil className="h-4 w-4" /><span className="sr-only">Ubah</span>
              </Button>
            )}
            {canDelete && (
              <Button size="sm" variant="ghost" className="h-8 px-2 text-destructive" disabled={!draft} title={draft ? "Hapus transmittal" : "Hanya Draft yang dapat dihapus"}
                onClick={() => remove(r)} data-testid={`transmittal-delete-${r.no}`}>
                <Trash2 className="h-4 w-4" /><span className="sr-only">Hapus</span>
              </Button>
            )}
          </div>
        );
      },
    }];
  }, [canEdit, canDelete, nav]); // eslint-disable-line react-hooks/exhaustive-deps

  // Seluruh id hasil filter (bukan hanya halaman aktif) untuk export PDF massal.
  const filteredIds = async () => {
    const ids = [];
    let page = 1;
    for (;;) {
      const params = { ...list.query, page, page_size: 100 };
      Object.keys(params).forEach((k) => (params[k] === "" || params[k] == null) && delete params[k]);
      const r = await api.get("/invoice-transmittals", { params });
      const items = r.data?.items || [];
      ids.push(...items.map((x) => x.id));
      if (!items.length || ids.length >= Number(r.data?.total || 0) || page >= 50) return ids;
      page += 1;
    }
  };

  const exportPdf = async () => {
    setBusyPdf(true);
    try {
      const ids = sel.length ? sel : await filteredIds();
      if (!ids.length) { toast.error("Tidak ada transmittal untuk diekspor."); return; }
      const take = ids.slice(0, PDF_MAX);
      const docs = [];
      for (const id of take) {
        const r = await api.get(`/invoice-transmittals/${id}/print`);
        docs.push(r.data);
      }
      const logoImg = await printImage(companyLogoPath(docs[0]?.company || {}));
      if (!openTransmittalPrintMany(docs.map((d) => ({ ...d, logoImg })))) {
        toast.error("Popup diblokir browser. Izinkan popup untuk mencetak/export PDF.");
        return;
      }
      if (ids.length > take.length) toast.warning(`Export PDF dibatasi ${PDF_MAX} transmittal pertama. Persempit filter untuk sisanya.`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setBusyPdf(false); }
  };

  return (
    <div className="space-y-5" data-testid="transmittal-list-page">
      <TransactionPageHeader type="transmittal" mode="list">
        {can("transmittal.create") && <Button onClick={() => nav("/transmittal/new")} data-testid="transmittal-create-btn"><Plus className="mr-2 h-4 w-4" />Buat Transmittal</Button>}
      </TransactionPageHeader>
      <DataTable
        columns={columns}
        server={list}
        testidPrefix="transmittal"
        countLabel="transmittal"
        minWidth={1450}
        emptyText="Belum ada Transmittal"
        searchPlaceholder="Cari nomor, tujuan, pengirim, penerima, supplier..."
        onOpen={(r) => nav(`/transmittal/${r.id}`)}
        selectable
        selected={sel}
        onToggleAll={setSel}
        onToggle={(id) => setSel((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))}
        filters={<>
          <div className="w-44"><Combobox options={optsOf(list.facets.status || [], "Semua Status")} value={status} onChange={setStatus} placeholder="Semua Status" testid="filter-transmittal-status" dense /></div>
          <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">Tanggal
            <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-11 sm:h-9 sm:w-36" aria-label="Tanggal dari" data-testid="transmittal-date-from" />s/d
            <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-11 sm:h-9 sm:w-36" aria-label="Tanggal sampai" data-testid="transmittal-date-to" /></div>
          <ListExportButtons reportKey={REPORT_KEY} formats={["xlsx"]}
            query={{ ...list.query, ...(sel.length ? { ids: sel.join(",") } : {}) }} total={sel.length || list.total} testidPrefix="transmittal" />
          {canPrint && (
            <Button type="button" variant="outline" size="sm" className="h-11 sm:h-9" onClick={exportPdf} disabled={busyPdf}
              title={sel.length ? `Export PDF ${sel.length} transmittal terpilih` : "Export PDF seluruh hasil filter (1 halaman per transmittal)"}
              data-testid="transmittal-export-pdf">
              <FileText className="mr-1.5 h-4 w-4" />{busyPdf ? "Menyiapkan..." : "Export PDF"}
            </Button>
          )}
          {sel.length > 0 && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground" data-testid="transmittal-selected-info">
              {sel.length} dipilih
              <Button type="button" variant="ghost" size="sm" className="h-8 px-2" onClick={() => setSel([])} data-testid="transmittal-clear-selection">Kosongkan</Button>
            </span>
          )}
        </>}
      />
    </div>
  );
}
