import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { rupiah } from "@/lib/format";
import { fmtD } from "@/lib/invoice";
import { DP_STATUS } from "@/lib/supplierDp";
import { HandCoins, RefreshCw, Search, FolderOpen, Play } from "lucide-react";
import { toast } from "sonner";

const HEAD = ["No. DP", "PO", "Tanggal PO", "Supplier", "Divisi", "Nilai PO", "Ketentuan DP", "Nilai DP", "Sudah Dibayar", "Status", ""];
const RIGHT = new Set([5, 7, 8]);

function Stat({ label, count, value, tid, tone }) {
  return (
    <div className="rounded-xl border bg-card p-4" data-testid={tid}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 font-head text-2xl font-bold tabular-nums ${tone || ""}`}>{rupiah(value)}</div>
      {count !== undefined && <div className="mt-0.5 text-xs text-muted-foreground">{count} PO</div>}
    </div>
  );
}

export default function SupplierDp() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState("pending");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(null);
  const canApprove = can("supplier_dp.approve");

  const load = useCallback(() => {
    setError(false);
    api.get("/supplier-dp").then((r) => setRows(r.data)).catch((e) => { setError(true); setRows([]); toast.error(apiError(e.response?.data?.detail)); });
  }, []);
  useEffect(() => { load(); }, [load]);

  const list = useMemo(() => {
    const k = q.trim().toLowerCase();
    return (rows || []).filter((r) => (tab === "all" || (tab === "pending" ? r.status_label === DP_STATUS.pending : r.status_label === DP_STATUS.paid))
      && (!k || [r.dp_no, r.po_no, r.supplier_name, r.division_name].some((v) => String(v || "").toLowerCase().includes(k))));
  }, [rows, tab, q]);
  const pend = (rows || []).filter((r) => r.status_label === DP_STATUS.pending);
  const paid = (rows || []).filter((r) => r.status_label === DP_STATUS.paid);

  const open = async (r) => {
    if (r.status_label === DP_STATUS.pending && !r.payment_id && canApprove) {
      setBusy(r.po_id);
      try { await api.post(`/supplier-dp/${r.po_id}/draft`, {}); }
      catch (e) { toast.error(apiError(e.response?.data?.detail)); setBusy(null); return; }
      setBusy(null);
    }
    nav(`/dp-supplier/${r.po_id}`);
  };

  if (!can("supplier_dp.view")) return <div className="p-8 text-muted-foreground" data-testid="supplier-dp-denied">Anda tidak memiliki izin untuk melihat DP Supplier.</div>;
  return (
    <div className="space-y-4" data-testid="supplier-dp-page">
      <TransactionPageHeader type="supplier_dp" mode="list" subtitle="PO Approved yang menggunakan DP otomatis muncul di sini. Finance memverifikasi dan mencatat realisasi pembayaran uang muka.">
        <Button variant="outline" onClick={load} data-testid="supplier-dp-refresh-btn"><RefreshCw className="mr-2 h-4 w-4" />Muat Ulang</Button>
      </TransactionPageHeader>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Stat label="Menunggu Verifikasi" count={pend.length} value={pend.reduce((s, r) => s + r.dp_amount, 0)} tone="text-amber-600" tid="supplier-dp-stat-pending" />
        <Stat label="Sudah Dibayar" count={paid.length} value={paid.reduce((s, r) => s + r.paid_amount, 0)} tone="text-emerald-600" tid="supplier-dp-stat-paid" />
        <Stat label="DP Tersedia (belum dialokasikan ke Invoice)" value={paid.reduce((s, r) => s + r.dp_available, 0)} tid="supplier-dp-stat-available" />
      </div>
      <Card><CardContent className="space-y-3 pt-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList data-testid="supplier-dp-tabs">
              <TabsTrigger value="pending" data-testid="supplier-dp-tab-pending">Menunggu Verifikasi ({pend.length})</TabsTrigger>
              <TabsTrigger value="paid" data-testid="supplier-dp-tab-paid">Sudah Dibayar ({paid.length})</TabsTrigger>
              <TabsTrigger value="all" data-testid="supplier-dp-tab-all">Semua</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="relative md:w-80"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Cari No. DP, PO, supplier, divisi" value={q} onChange={(e) => setQ(e.target.value)} data-testid="supplier-dp-search" /></div>
        </div>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[1200px] text-sm" data-testid="supplier-dp-table">
            <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {HEAD.map((h, i) => <th key={i} className={`p-2.5 ${RIGHT.has(i) ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
            <tbody>
              {rows === null && [0, 1, 2].map((i) => <tr key={i} className="border-t"><td colSpan={HEAD.length} className="p-2.5"><Skeleton className="h-6 w-full" /></td></tr>)}
              {rows !== null && error && <tr><td colSpan={HEAD.length} className="p-6 text-center text-muted-foreground" data-testid="supplier-dp-error">Data DP Supplier gagal dimuat. <Button variant="link" onClick={load}>Coba lagi</Button></td></tr>}
              {rows !== null && !error && list.length === 0 && <tr><td colSpan={HEAD.length} className="p-8 text-center text-muted-foreground" data-testid="supplier-dp-empty">
                <HandCoins className="mx-auto mb-2 h-8 w-8 opacity-40" />Belum ada DP pada kategori ini. DP muncul otomatis saat PO yang menggunakan DP sudah Approved.</td></tr>}
              {list.map((r) => (
                <tr key={r.po_id} className="border-t transition-colors hover:bg-muted/40" data-testid={`supplier-dp-row-${r.po_no}`}>
                  <td className="p-2.5 font-mono text-xs font-semibold">{r.dp_no || "-"}</td>
                  <td className="p-2.5 font-mono text-xs">{r.po_no}</td>
                  <td className="p-2.5 text-xs">{fmtD(r.po_date)}</td>
                  <td className="p-2.5">{r.supplier_name || "-"}</td>
                  <td className="p-2.5 text-xs">{r.division_name || "-"}</td>
                  <td className="p-2.5 text-right tabular-nums">{rupiah(r.po_value)}</td>
                  <td className="p-2.5 text-xs">{r.dp_terms}</td>
                  <td className="p-2.5 text-right font-semibold tabular-nums" data-testid={`supplier-dp-amount-${r.po_no}`}>{rupiah(r.dp_amount)}</td>
                  <td className="p-2.5 text-right tabular-nums">{rupiah(r.paid_amount)}</td>
                  <td className="p-2.5"><StatusBadge status={r.status_label} /></td>
                  <td className="p-2.5 text-right">
                    {r.status_label === DP_STATUS.pending && canApprove
                      ? <Button size="sm" onClick={() => open(r)} disabled={busy === r.po_id} data-testid={`supplier-dp-process-${r.po_no}`}><Play className="mr-1 h-3.5 w-3.5" />{busy === r.po_id ? "Memproses..." : "Proses"}</Button>
                      : <Button size="sm" variant="outline" onClick={() => open(r)} data-testid={`supplier-dp-open-${r.po_no}`}><FolderOpen className="mr-1 h-3.5 w-3.5" />Buka</Button>}
                  </td>
                </tr>))}
            </tbody>
          </table>
        </div>
      </CardContent></Card>
    </div>
  );
}
