import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { fmtDate, rupiah } from "@/lib/format";
import { Check, X, Search, RefreshCw, Layers } from "lucide-react";
import { Approval2Panel } from "@/components/approval2/Approval2Panel";
import { isLevel2PoTask } from "@/lib/approval2";
import { toast } from "sonner";

const ROUTES = { mro: "/mro/", ro: "/ro/", po: "/po/" };

export default function Approval() {
  const { user, can } = useAuth();
  const canA2 = can("po_approval2.view");
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [params, setParams] = useSearchParams();
  const [view, setViewState] = useState(params.get("view") === "approval2" ? "approval2" : "pending");
  const setView = (v) => { setViewState(v); setParams(v === "approval2" ? { view: "approval2" } : {}, { replace: true }); };
  const [scope, setScope] = useState("mine");
  const [moduleFilter, setModuleFilter] = useState("all");
  const [loading, setLoading] = useState(false);

  const isAdmin = user?.role === "admin";
  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get(`/approvals/inbox?scope=${isAdmin ? scope : "mine"}`);
      setRows(res.data || []);
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, [scope, isAdmin]);

  useEffect(() => { load(); }, [load]);

  const modules = useMemo(() => Array.from(new Set(rows.map((r) => r.module).filter(Boolean))), [rows]);
  const filtered = useMemo(() => rows.filter((r) => {
    if (view === "pending" && r.status !== "Pending") return false;
    if (view === "processed" && !["Approved", "Rejected"].includes(r.status)) return false;
    if (moduleFilter !== "all" && r.module !== moduleFilter) return false;
    const text = `${r.document_type || ""} ${r.document_no || ""} ${r.context_name || ""} ${r.approver_name || ""} ${r.approver_email || ""}`.toLowerCase();
    return !q || text.includes(q.toLowerCase());
  }), [rows, q, view, moduleFilter]);

  const act = async (row, action) => {
    try {
      if (action === "reject" && !window.confirm(`Tolak ${row.document_no}?`)) return;
      await api.post(`/approvals/${row.id}/${action}`, action === "reject" ? { reason: "Ditolak dari menu Approval" } : {});
      toast.success(action === "approve" ? "Approval disetujui" : "Approval ditolak");
      load();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail));
    }
  };

  const openDoc = (row) => {
    const base = ROUTES[row.module];
    if (base) nav(base + row.document_id);
  };

  const pending = rows.filter((r) => r.status === "Pending").length;
  const processed = rows.filter((r) => ["Approved", "Rejected"].includes(r.status)).length;
  const level2 = rows.filter(isLevel2PoTask).length;

  return <div>
    <PageHeader title="Approval" subtitle="Inbox approval lintas modul berdasarkan user/email yang ditugaskan">
      <Button variant="outline" onClick={load} disabled={loading}><RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />Refresh</Button>
    </PageHeader>

    <div className="grid grid-cols-1 gap-3 mb-5 max-w-3xl sm:grid-cols-3">
      <button onClick={() => setView("pending")} data-testid="approval-tab-pending" className={`rounded-xl border bg-card p-4 text-left ${view === "pending" ? "border-primary ring-1 ring-primary/20" : ""}`}>
        <div className="text-2xl font-bold">{pending}</div><div className="text-sm font-semibold">Menunggu Saya</div><div className="text-xs text-muted-foreground">Perlu tindakan sekarang</div>
      </button>
      <button onClick={() => setView("processed")} data-testid="approval-tab-processed" className={`rounded-xl border bg-card p-4 text-left ${view === "processed" ? "border-primary ring-1 ring-primary/20" : ""}`}>
        <div className="text-2xl font-bold">{processed}</div><div className="text-sm font-semibold">Sudah Diproses</div><div className="text-xs text-muted-foreground">Approved / Rejected</div>
      </button>
      {canA2 && <button onClick={() => setView("approval2")} data-testid="approval-tab-approval2" className={`rounded-xl border bg-card p-4 text-left ${view === "approval2" ? "border-primary ring-1 ring-primary/20" : ""}`}>
        <div className="flex items-center gap-2 text-2xl font-bold">{level2}<Layers className="h-4 w-4 text-muted-foreground" /></div><div className="text-sm font-semibold">Pengajuan Approval 2</div><div className="text-xs text-muted-foreground">PO Level 2 via batch pimpinan</div>
      </button>}
    </div>

    {view === "approval2" && canA2 ? <Approval2Panel scope={isAdmin ? scope : "mine"} onChanged={load} /> : <>
    <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
      <div className="relative max-w-md flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari modul, nomor dokumen, pemohon/supplier, approver..." className="pl-9" /></div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={moduleFilter === "all" ? "default" : "outline"} onClick={() => setModuleFilter("all")}>Semua Modul</Button>
        {modules.map((m) => <Button key={m} size="sm" variant={moduleFilter === m ? "default" : "outline"} onClick={() => setModuleFilter(m)}>{m.toUpperCase()}</Button>)}
      </div>
      {user?.role === "admin" && <div className="flex gap-2"><Button variant={scope === "mine" ? "default" : "outline"} onClick={() => setScope("mine")}>Milik Saya</Button><Button variant={scope === "all" ? "default" : "outline"} onClick={() => setScope("all")}>Semua Approval</Button></div>}
    </div>

    <Card><CardContent className="p-0 overflow-x-auto">
      <table className="w-full min-w-[1050px] text-sm zebra">
        <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">Modul</th><th className="p-3">Dokumen</th><th className="p-3">Tanggal</th><th className="p-3">Pemohon / Supplier</th><th className="p-3">Level</th><th className="p-3">Approver</th><th className="p-3 text-right">Nilai</th><th className="p-3">Status</th><th className="p-3 text-right">Aksi</th></tr></thead>
        <tbody>
          {filtered.length === 0 && <tr><td colSpan={9} className="p-8 text-center text-muted-foreground">Tidak ada approval pada filter ini</td></tr>}
          {filtered.map((r) => <tr key={r.id} className="border-t">
            <td className="p-3"><span className="rounded-md bg-muted px-2 py-1 font-mono text-xs font-semibold">{r.document_type || r.module?.toUpperCase()}</span></td>
            <td className="p-3"><button onClick={() => openDoc(r)} className="font-mono text-xs font-semibold text-primary hover:underline">{r.document_no}</button></td>
            <td className="p-3">{fmtDate(r.date)}</td><td className="p-3">{r.context_name || "-"}</td><td className="p-3">Level {r.seq}</td>
            <td className="p-3"><div className="font-medium">{r.approver_name || "-"}</div><div className="text-xs text-muted-foreground">{r.approver_email || ""}</div></td>
            <td className="p-3 text-right tabular-nums">{r.module === "po" && r.grand_total != null ? rupiah(r.grand_total) : "-"}</td><td className="p-3"><StatusBadge status={r.status} /></td>
            <td className="p-3"><div className="flex justify-end gap-2">{isLevel2PoTask(r) ? <Button size="sm" variant="outline" onClick={() => setView("approval2")} data-testid={`approval-process-l2-${r.document_no}`}><Layers className="h-4 w-4 mr-1" />Proses Approval 2</Button> : r.status === "Pending" && <><Button size="sm" onClick={() => act(r, "approve")}><Check className="h-4 w-4 mr-1" />Approve</Button><Button size="sm" variant="outline" onClick={() => act(r, "reject")}><X className="h-4 w-4 mr-1" />Reject</Button></>}</div></td>
          </tr>)}
        </tbody>
      </table>
    </CardContent></Card>
    </>}
    {view === "approval2" && isAdmin && <div className="mt-3 flex gap-2"><Button size="sm" variant={scope === "mine" ? "default" : "outline"} onClick={() => setScope("mine")}>Milik Saya</Button><Button size="sm" variant={scope === "all" ? "default" : "outline"} onClick={() => setScope("all")}>Semua Approval</Button></div>}
  </div>;
}
