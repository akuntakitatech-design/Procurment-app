import { useCallback, useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Activity, Filter, RotateCcw, ChevronLeft, ChevronRight, ShieldCheck } from "lucide-react";
import { fmtDateTime } from "@/lib/format";
import { toast } from "sonner";

const ACTION_LABELS = {
  create: "Buat",
  edit: "Edit",
  delete: "Hapus",
  submit: "Submit",
  approve: "Approve",
  reject: "Reject",
  cancel: "Batalkan",
  close: "Tutup",
  upload_file: "Upload File",
};

const ENTITY_LABELS = {
  mro: "MRO",
  ro: "RO",
  po: "PO",
  do: "DO",
  mi: "MI",
  transfer: "Transfer",
  loan: "Pinjaman",
  loan_return: "Return Pinjaman",
  adjustment: "Stock Adjustment",
  opname: "Stock Opname",
  user: "User",
  supplier: "Supplier",
  item: "Barang",
};

function labelAction(value) {
  const key = String(value || "").toLowerCase();
  return ACTION_LABELS[key] || String(value || "Aktivitas").replaceAll("_", " ");
}

function labelEntity(value) {
  const key = String(value || "").toLowerCase();
  return ENTITY_LABELS[key] || String(value || "Sistem").replaceAll("_", " ").toUpperCase();
}

function FilterSelect({ value, onChange, children }) {
  return <select value={value} onChange={(e) => onChange(e.target.value)} className="h-10 rounded-xl border bg-card px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring/30">
    {children}
  </select>;
}

export default function ActivityLog() {
  const [data, setData] = useState({ rows: [], page: 1, pages: 1, total: 0, entities: [], actions: [], scope: "global" });
  const [filters, setFilters] = useState({ q: "", entity: "", action: "", user_email: "", date_from: "", date_to: "" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams({ page: String(page), size: "50" });
    Object.entries(applied).forEach(([k, v]) => { if (v) p.set(k, v); });
    return p.toString();
  }, [applied, page]);

  const load = useCallback(() => {
    setLoading(true);
    api.get(`/activity-log?${params}`).then((r) => setData(r.data)).catch((e) => toast.error(apiError(e.response?.data?.detail))).finally(() => setLoading(false));
  }, [params]);

  useEffect(() => { load(); }, [load]);

  const apply = (e) => {
    e?.preventDefault?.();
    setPage(1);
    setApplied({ ...filters });
  };

  const reset = () => {
    const empty = { q: "", entity: "", action: "", user_email: "", date_from: "", date_to: "" };
    setFilters(empty); setApplied(empty); setPage(1);
  };

  return <div className="space-y-6">
    <PageHeader title="Log Aktivitas" subtitle="Jejak audit perubahan dan aktivitas pengguna di dalam sistem." />

    <Card className="rounded-2xl shadow-none">
      <CardContent className="p-5">
        <form onSubmit={apply} className="space-y-4">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/8 text-primary"><Filter className="h-4 w-4" /></div>
            <div><div className="font-head text-sm font-semibold">Filter Aktivitas</div><div className="text-xs text-muted-foreground">Cari berdasarkan dokumen, aktivitas, user, atau periode.</div></div>
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(240px,1.7fr)_1fr_1fr_1fr_1fr]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} placeholder="Cari no. dokumen, user, aktivitas..." className="h-10 rounded-xl pl-9" />
            </div>
            <FilterSelect value={filters.entity} onChange={(v) => setFilters({ ...filters, entity: v })}>
              <option value="">Semua Modul</option>
              {(data.entities || []).map((x) => <option key={x} value={x}>{labelEntity(x)}</option>)}
            </FilterSelect>
            <FilterSelect value={filters.action} onChange={(v) => setFilters({ ...filters, action: v })}>
              <option value="">Semua Aktivitas</option>
              {(data.actions || []).map((x) => <option key={x} value={x}>{labelAction(x)}</option>)}
            </FilterSelect>
            <Input type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} className="h-10 rounded-xl" title="Dari tanggal" />
            <Input type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} className="h-10 rounded-xl" title="Sampai tanggal" />
          </div>
          {data.scope === "global" && <div className="grid gap-3 sm:grid-cols-[minmax(240px,420px)_auto_1fr]">
            <Input value={filters.user_email} onChange={(e) => setFilters({ ...filters, user_email: e.target.value })} placeholder="Filter email user (opsional)" className="h-10 rounded-xl" />
            <Button type="submit" className="rounded-xl">Terapkan Filter</Button>
            <Button type="button" variant="outline" onClick={reset} className="rounded-xl sm:justify-self-start"><RotateCcw className="mr-2 h-4 w-4" />Reset</Button>
          </div>}
          {data.scope !== "global" && <div className="flex flex-wrap items-center gap-2"><Button type="submit" className="rounded-xl">Terapkan Filter</Button><Button type="button" variant="outline" onClick={reset} className="rounded-xl"><RotateCcw className="mr-2 h-4 w-4" />Reset</Button><span className="text-xs text-muted-foreground">Akses terbatas menampilkan aktivitas akun Anda sendiri.</span></div>}
        </form>
      </CardContent>
    </Card>

    <Card className="overflow-hidden rounded-2xl shadow-none">
      <CardContent className="p-0">
        <div className="flex flex-col gap-2 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#F4F7FB] text-[#244B72] ring-1 ring-[#DDE7F2]"><ShieldCheck className="h-4 w-4" /></div><div><div className="font-head text-sm font-semibold">Audit Trail</div><div className="text-xs text-muted-foreground">{Number(data.total || 0).toLocaleString("id-ID")} aktivitas tercatat</div></div></div>
          <div className="text-xs text-muted-foreground">Halaman {data.page || 1} dari {data.pages || 1}</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-sm">
            <thead className="bg-muted/45 text-[11px] uppercase tracking-wider text-muted-foreground"><tr><th className="p-3 text-left">Waktu</th><th className="p-3 text-left">Aktivitas</th><th className="p-3 text-left">Dokumen / Objek</th><th className="p-3 text-left">User</th><th className="p-3 text-left">Keterangan</th></tr></thead>
            <tbody>
              {loading && <tr><td colSpan={5} className="p-10 text-center text-muted-foreground">Memuat log aktivitas...</td></tr>}
              {!loading && data.rows.length === 0 && <tr><td colSpan={5} className="p-10 text-center text-muted-foreground">Tidak ada aktivitas yang sesuai filter.</td></tr>}
              {!loading && data.rows.map((r) => <tr key={r.id} className="border-t transition-colors hover:bg-muted/20">
                <td className="p-3 whitespace-nowrap text-xs text-muted-foreground">{fmtDateTime(r.at)}</td>
                <td className="p-3"><div className="inline-flex items-center gap-2 rounded-lg bg-primary/7 px-2.5 py-1.5 text-xs font-semibold text-primary"><Activity className="h-3.5 w-3.5" />{labelAction(r.action)}</div></td>
                <td className="p-3"><div className="font-medium">{labelEntity(r.entity)}</div><div className="mt-0.5 font-mono text-xs text-muted-foreground">{r.doc_no || r.entity_id || "-"}</div></td>
                <td className="p-3"><div className="font-medium">{r.user_name || "-"}</div><div className="mt-0.5 text-xs text-muted-foreground">{r.user || "-"}</div></td>
                <td className="p-3 text-xs text-muted-foreground">{r.reason || "-"}</td>
              </tr>)}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between border-t px-5 py-4">
          <Button variant="outline" size="sm" className="rounded-xl" disabled={(data.page || 1) <= 1 || loading} onClick={() => setPage((x) => Math.max(1, x - 1))}><ChevronLeft className="mr-1 h-4 w-4" />Sebelumnya</Button>
          <span className="text-xs text-muted-foreground">Menampilkan maksimal 50 aktivitas per halaman</span>
          <Button variant="outline" size="sm" className="rounded-xl" disabled={(data.page || 1) >= (data.pages || 1) || loading} onClick={() => setPage((x) => x + 1)}>Berikutnya<ChevronRight className="ml-1 h-4 w-4" /></Button>
        </div>
      </CardContent>
    </Card>
  </div>;
}
