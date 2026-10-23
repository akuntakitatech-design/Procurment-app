import { useCallback, useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { fmtDate } from "@/lib/format";
import { Check, X, Search, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const TABS = [["pending", "Menunggu Approval"], ["approved", "Disetujui"], ["rejected", "Ditolak"]];
const BADGE = {
  pending: "bg-amber-50 text-amber-700 border-amber-200",
  approved: "bg-emerald-50 text-emerald-700 border-emerald-200",
  rejected: "bg-rose-50 text-rose-700 border-rose-200",
};
const LABEL = { pending: "Menunggu Approval", approved: "Disetujui", rejected: "Ditolak" };

function SupplierStatus({ status }) {
  const key = BADGE[status] ? status : "pending";
  return <span data-testid={`supplier-approval-status-${key}`} className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${BADGE[key]}`}>{LABEL[key]}</span>;
}

export function SupplierApprovalPanel({ onChanged }) {
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get(`/supplier-approvals?status=${status}`);
      setItems(res.data?.items || []);
      setCounts(res.data?.counts || {});
      setSelected(new Set());
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((r) => `${r.code || ""} ${r.name || ""} ${r.legal_name || ""}`.toLowerCase().includes(needle));
  }, [items, q]);

  const toggle = (id) => setSelected((cur) => { const next = new Set(cur); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const allChecked = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const toggleAll = () => setSelected(allChecked ? new Set() : new Set(rows.map((r) => r.id)));

  const act = async (ids, action, reason) => {
    const list = ids.filter(Boolean);
    if (!list.length) return toast.error("Pilih minimal satu supplier");
    try {
      setBusy(true);
      const body = action === "approve" ? { ids: list, note: "Disetujui dari menu Approval" } : { ids: list, reason };
      await api.post(`/supplier-approvals/${action}`, body);
      toast.success(`${list.length} supplier ${action === "approve" ? "disetujui" : "ditolak"}`);
      await load();
      onChanged?.();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  const approveOne = (row) => act([row.id], "approve");
  const rejectMany = (ids) => {
    const reason = window.prompt("Alasan penolakan (wajib diisi):", "Dokumen/lengkapan supplier belum memadai");
    if (reason === null) return;
    if (!reason.trim()) return toast.error("Alasan penolakan wajib diisi");
    act(ids, "reject", reason.trim());
  };

  const pendingCount = Number(counts.pending || 0);

  return <div className="space-y-4">
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap gap-2">
        {TABS.map(([value, label]) => <Button key={value} size="sm" variant={status === value ? "default" : "outline"} onClick={() => setStatus(value)} data-testid={`supplier-approval-tab-${value}`} aria-pressed={status === value}>
          {label}{value === "pending" && pendingCount > 0 ? ` (${pendingCount})` : ""}
        </Button>)}
      </div>
      <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
        <div className="relative max-w-md flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode / nama supplier..." className="pl-9 h-11 sm:h-9" data-testid="supplier-approval-search" /></div>
        <Button variant="outline" onClick={load} disabled={loading || busy} className="h-11 sm:h-9"><RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />Refresh</Button>
      </div>
    </div>

    {status === "pending" && selected.size > 0 && <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2" data-testid="supplier-approval-bulk-bar">
      <span className="text-sm font-medium">{selected.size} supplier dipilih</span>
      <Button size="sm" onClick={() => act([...selected], "approve")} disabled={busy} data-testid="supplier-approval-bulk-approve"><Check className="h-4 w-4 mr-1" />Setujui Terpilih</Button>
      <Button size="sm" variant="outline" onClick={() => rejectMany([...selected])} disabled={busy} data-testid="supplier-approval-bulk-reject"><X className="h-4 w-4 mr-1" />Tolak Terpilih</Button>
      <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} disabled={busy}>Batal Pilih</Button>
    </div>}

    <Card><CardContent className="p-0 overflow-x-auto">
      <table className="m-stack w-full min-w-[980px] text-sm zebra">
        <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
          {status === "pending" && <th className="p-3 w-10"><input type="checkbox" checked={allChecked} onChange={toggleAll} aria-label="Pilih semua supplier" data-testid="supplier-approval-check-all" /></th>}
          <th className="p-3">Kode</th><th className="p-3">Nama Supplier</th><th className="p-3">Kota</th><th className="p-3">Diajukan Oleh</th><th className="p-3">Tanggal</th><th className="p-3">Status</th><th className="p-3 text-right">Aksi</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={status === "pending" ? 8 : 7} className="p-8 text-center text-muted-foreground">{loading ? "Memuat..." : "Tidak ada supplier pada filter ini"}</td></tr>}
          {rows.map((r) => <tr key={r.id} className="border-t">
            {status === "pending" && <td data-label="Pilih" className="p-3"><input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Pilih ${r.code}`} data-testid={`supplier-approval-check-${r.code}`} /></td>}
            <td data-label="Kode" className="p-3 font-mono text-xs font-semibold">{r.code || "-"}</td>
            <td data-label="Nama Supplier" className="m-full p-3"><div className="font-medium">{r.name || "-"}</div>{r.legal_name ? <div className="text-xs text-muted-foreground">{r.legal_name}</div> : null}</td>
            <td data-label="Kota" className="p-3">{r.city || "-"}</td>
            <td data-label="Diajukan Oleh" className="p-3"><div className="text-xs">{r.approval_requested_by_name || r.approval_requested_by || "-"}</div></td>
            <td data-label="Tanggal" className="p-3">{r.approval_requested_at ? fmtDate(r.approval_requested_at) : fmtDate(r.created_at)}</td>
            <td data-label="Status" className="p-3"><SupplierStatus status={r.approval_status} /></td>
            <td data-label="Aksi" className="m-full p-3"><div className="flex flex-wrap justify-end gap-2">
              {r.approval_status === "pending"
                ? <><Button size="sm" onClick={() => approveOne(r)} disabled={busy} data-testid={`supplier-approval-approve-${r.code}`}><Check className="h-4 w-4 mr-1" />Setujui</Button>
                  <Button size="sm" variant="outline" onClick={() => rejectMany([r.id])} disabled={busy} data-testid={`supplier-approval-reject-${r.code}`}><X className="h-4 w-4 mr-1" />Tolak</Button></>
                : <span className="text-xs text-muted-foreground">{r.approval_acted_by_name || r.approval_acted_by || "-"}{r.approval_acted_at ? ` · ${fmtDate(r.approval_acted_at)}` : ""}</span>}
            </div></td>
          </tr>)}
        </tbody>
      </table>
    </CardContent></Card>

    {status !== "pending" && <p className="text-xs text-muted-foreground">Riwayat keputusan approval supplier. Supplier yang disetujui langsung tersedia di form PO.</p>}
  </div>;
}

export default SupplierApprovalPanel;