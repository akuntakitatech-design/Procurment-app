import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AlertCircle, BarChart3, FileSpreadsheet, FileText, RotateCcw, Search } from "lucide-react";
import api from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { PageHeader } from "@/components/PageHeader";
import { ListPager } from "@/components/ListPager";
import { Combobox } from "@/components/Combobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { NUMERIC_TYPES, buildQuery, exportState, formatCell, reportPath, validateFilters } from "@/lib/reportCenter";

const errMsg = async (e) => {
  const d = e?.response?.data;
  if (d instanceof Blob) { try { return JSON.parse(await d.text()).detail; } catch { return "Export gagal."; } }
  return d?.detail || "Terjadi kesalahan saat memuat laporan.";
};

function GroupNav({ catalog, activeKey }) {
  return (
    <nav className="space-y-4" data-testid="report-center-nav">
      {catalog.groups.map((g, gi) => (
        <div key={g.key} data-testid={`report-group-${g.key}`}>
          <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{gi + 1}. {g.title}</div>
          {g.reports.length === 0 && <div className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">Segera tersedia</div>}
          {g.reports.map((r) => (
            <Link key={r.key} to={reportPath(r.key)} data-testid={`report-link-${r.key}`}
              className={`block rounded-md px-3 py-2 text-sm transition-colors ${activeKey === r.key ? "bg-primary/10 font-semibold text-primary" : "hover:bg-muted"}`}>
              {r.title}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}

function FilterBar({ res, draft, setDraft, onApply, onReset, divisionOpts }) {
  const set = (k, v) => setDraft((s) => ({ ...s, [k]: v }));
  return (
    <form className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="report-center-filters"
      onSubmit={(e) => { e.preventDefault(); onApply(); }}>
      {res.filters.map((f) => (
        <div key={f.key} className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground" htmlFor={`rc-f-${f.key}`}>{f.label}</label>
          {f.type === "date" && <Input id={`rc-f-${f.key}`} type="date" value={draft[f.key] || ""} onChange={(e) => set(f.key, e.target.value)} data-testid={`report-filter-${f.key}`} />}
          {f.type === "division" && <Combobox options={[{ value: "", label: "Semua Divisi" }, ...divisionOpts]} value={draft[f.key] || ""} onChange={(v) => set(f.key, v)} testid={`report-filter-${f.key}`} />}
          {f.type === "select" && <Combobox options={[{ value: "", label: `Semua ${f.label}` }, ...f.options]} value={draft[f.key] || ""} onChange={(v) => set(f.key, v)} testid={`report-filter-${f.key}`} />}
          {f.type === "text" && <Input id={`rc-f-${f.key}`} value={draft[f.key] || ""} onChange={(e) => set(f.key, e.target.value)} data-testid={`report-filter-${f.key}`} />}
        </div>
      ))}
      <div className="space-y-1.5">
        <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground" htmlFor="rc-f-q">Pencarian</label>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input id="rc-f-q" className="pl-8" placeholder="Kode, nama, no. dokumen" value={draft.q || ""} onChange={(e) => set("q", e.target.value)} data-testid="report-filter-q" />
        </div>
      </div>
      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-5">
        <Button type="submit" data-testid="report-center-apply">Terapkan</Button>
        <Button type="button" variant="outline" onClick={onReset} data-testid="report-center-reset"><RotateCcw className="mr-1.5 h-4 w-4" />Reset</Button>
      </div>
    </form>
  );
}

function ReportTable({ res }) {
  const cols = res.columns;
  const hasTotal = cols.some((c) => c.total);
  return (
    <div className="overflow-x-auto rounded-md border bg-card shadow-sm">
      <table className="w-full text-sm zebra" data-testid="report-center-table">
        <thead className="bg-muted">
          <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            {cols.map((c) => <th key={c.key} className={`whitespace-nowrap p-3 ${NUMERIC_TYPES.has(c.type) ? "text-right" : ""}`}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {res.rows.length === 0 && <tr><td colSpan={cols.length} className="p-8 text-muted-foreground"><div className="sticky left-8 w-fit" data-testid="report-center-empty">Tidak ada data sesuai filter. Ubah atau reset filter.</div></td></tr>}
          {res.rows.map((r, i) => (
            <tr key={i} className="border-t" data-testid={`report-row-${i}`}>
              {cols.map((c, ci) => {
                const v = formatCell(r[c.key], c.type);
                const drill = ci === cols.findIndex((x) => x.key === "mro_no") && r._drill?.to;
                return (
                  <td key={c.key} className={`p-3 align-top ${NUMERIC_TYPES.has(c.type) ? "whitespace-nowrap text-right tabular-nums" : ""}`}>
                    {drill ? <Link to={r._drill.to} className="font-mono text-xs font-semibold text-primary hover:underline" data-testid={`report-drill-${i}`}>{v}</Link> : v}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        {hasTotal && (
          <tfoot>
            <tr className="border-t-2 bg-muted/60 font-semibold" data-testid="report-center-total-row">
              {cols.map((c, i) => (
                <td key={c.key} className={`p-3 ${NUMERIC_TYPES.has(c.type) ? "whitespace-nowrap text-right tabular-nums" : "whitespace-nowrap"}`}>
                  {c.total ? formatCell(res.totals[c.key], c.type) : i === 0 ? `TOTAL (${res.total_rows} baris)` : ""}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

export default function ReportCenter() {
  const { key } = useParams();
  const nav = useNavigate();
  const { data: m } = useMasters(["divisions"]);
  const [catalog, setCatalog] = useState(null);
  const [catErr, setCatErr] = useState("");
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({});
  const [applied, setApplied] = useState({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    api.get("/report-center/catalog").then((r) => setCatalog(r.data)).catch(async (e) => setCatErr(await errMsg(e)));
  }, []);

  const firstKey = useMemo(() => catalog?.groups.flatMap((g) => g.reports)[0]?.key, [catalog]);
  useEffect(() => { if (!key && firstKey) nav(reportPath(firstKey), { replace: true }); }, [key, firstKey, nav]);
  useEffect(() => { setDraft({}); setApplied({}); setPage(1); setRes(null); }, [key]);

  const load = useCallback(async () => {
    if (!key) return;
    setLoading(true); setError("");
    try {
      const r = await api.get(`/report-center/${encodeURIComponent(key)}?${buildQuery(applied, { page, page_size: pageSize })}`);
      setRes(r.data);
    } catch (e) { setError(await errMsg(e)); } finally { setLoading(false); }
  }, [key, applied, page, pageSize]);
  useEffect(() => { load(); }, [load]);

  const apply = () => {
    const msg = validateFilters(draft);
    if (msg) { toast.error(msg); return; }
    setPage(1); setApplied({ ...draft });
  };

  const doExport = async (fmt) => {
    const st = exportState(res, fmt, catalog?.can_export);
    if (!st.ok) { toast.error(st.reason); return; }
    setBusy(fmt);
    try {
      const r = await api.get(`/report-center/${encodeURIComponent(key)}/export.${fmt}?${buildQuery(applied)}`, { responseType: "blob" });
      const cd = r.headers?.["content-disposition"] || "";
      const name = (cd.match(/filename="([^"]+)"/) || [])[1] || `${key}.${fmt}`;
      const url = window.URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`Export ${fmt === "pdf" ? "PDF" : "Excel"} berhasil (${r.headers?.["x-report-rows"] ?? res.total_rows} baris).`);
    } catch (e) { toast.error(await errMsg(e)); } finally { setBusy(""); }
  };

  const divisionOpts = (m?.divisions || []).map((d) => ({ value: d.id, label: d.name }));

  return (
    <div data-testid="report-center-page">
      <PageHeader title="Pusat Laporan" subtitle="Laporan Procurement & Warehouse dengan filter, total, dan export Excel/PDF dari satu sumber perhitungan." testid="report-center-header">
        <Button variant="outline" onClick={() => nav("/reports")} data-testid="report-center-legacy-link"><BarChart3 className="mr-1.5 h-4 w-4" />Laporan Lama</Button>
      </PageHeader>
      {catErr && <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" data-testid="report-center-catalog-error"><AlertCircle className="h-4 w-4" />{catErr}</div>}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="h-fit"><CardContent className="pt-5">
          {catalog ? <GroupNav catalog={catalog} activeKey={key} /> : <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>}
        </CardContent></Card>
        <div className="min-w-0 space-y-4">
          {res && (
            <Card><CardContent className="space-y-4 pt-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground" data-testid="report-center-group">{res.meta.group_title}</div>
                  <h2 className="font-head text-lg font-bold" data-testid="report-center-title">{res.meta.title}</h2>
                  <p className="text-sm text-muted-foreground">{res.meta.description}</p>
                  {res.meta.date_basis && <p className="mt-1 text-xs text-muted-foreground">Dasar tanggal: {res.meta.date_basis}</p>}
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={() => doExport("xlsx")} disabled={!!busy || !catalog?.can_export} data-testid="report-center-export-xlsx"><FileSpreadsheet className="mr-1.5 h-4 w-4" />{busy === "xlsx" ? "Menyiapkan..." : "Export Excel"}</Button>
                  <Button variant="outline" onClick={() => doExport("pdf")} disabled={!!busy || !catalog?.can_export} data-testid="report-center-export-pdf"><FileText className="mr-1.5 h-4 w-4" />{busy === "pdf" ? "Menyiapkan..." : "Export PDF"}</Button>
                </div>
              </div>
              <FilterBar res={res} draft={draft} setDraft={setDraft} onApply={apply} onReset={() => { setDraft({}); setPage(1); setApplied({}); }} divisionOpts={divisionOpts} />
              <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="report-center-applied">
                {res.filters_applied.length === 0 ? <Badge variant="secondary">Semua data</Badge> : res.filters_applied.map((f) => <Badge key={f.key} variant="secondary">{f.label}: {f.value}</Badge>)}
                {!res.price_visible && <Badge variant="outline" data-testid="report-center-price-hidden">Kolom harga disembunyikan sesuai hak akses</Badge>}
              </div>
            </CardContent></Card>
          )}
          {error && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" data-testid="report-center-error">
              <span className="flex items-center gap-2"><AlertCircle className="h-4 w-4" />{error}</span>
              <Button size="sm" variant="outline" onClick={load} data-testid="report-center-retry">Coba lagi</Button>
            </div>
          )}
          {loading && !res && <div className="space-y-2" data-testid="report-center-loading">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-9 w-full" />)}</div>}
          {res && (
            <div className={loading ? "opacity-60 transition-opacity" : ""}>
              <ReportTable res={res} />
              <ListPager total={res.total_rows} page={res.page} pageSize={res.page_size} setPage={setPage}
                setPageSize={(s) => { setPageSize(s); setPage(1); }} testid="report-center" unit="baris" />
            </div>
          )}
          {catalog && !firstKey && !key && <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground" data-testid="report-center-no-reports">Belum ada laporan yang dapat Anda akses.</div>}
        </div>
      </div>
    </div>
  );
}
