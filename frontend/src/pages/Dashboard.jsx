import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useMasters } from "@/hooks/useMasters";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Combobox } from "@/components/Combobox";
import { KpiCard } from "@/components/dashboard/KpiCard";
import { TrendChart } from "@/components/dashboard/TrendChart";
import { StatusDonut } from "@/components/dashboard/StatusDonut";
import { UnvaluedStockDialog } from "@/components/dashboard/UnvaluedStockDialog";
import { TopSuppliers } from "@/components/dashboard/TopSuppliers";
import { AttentionTable } from "@/components/dashboard/AttentionTable";
import { FinanceMonitor } from "@/components/dashboard/FinanceMonitor";
import { SpkDetailPanel, SpkSummaryCard } from "@/components/dashboard/SpkBudgetPanel";
import { InventoryPanel } from "@/components/dashboard/InventoryPanel";
import { ContractStatusPanel, PriceControlPanel, PriceExceptionTable } from "@/components/dashboard/VendorContractPanel";
import { DashboardDrillDialog } from "@/components/dashboard/DashboardDrillDialog";
import { PERIODS, asOfLabel, ccParams, compactRupiah, contractDrillParams, drillLink, periodText, priceDrillParams, spkDrillParams } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import {
  AlertTriangle, CalendarDays, Wallet, CheckCircle2, ClipboardList, Clock3, FileClock, FileWarning, Hourglass, HandCoins,
  Landmark, PackageCheck, PackageOpen, Plus, RefreshCw, RotateCcw, Send, Timer, Truck, AlarmClock, CircleAlert,
} from "lucide-react";

const DEFAULT = { period: "this_month", division_id: "", project_id: "", supplier_id: "" };
const REFRESH_MS = 5 * 60 * 1000;

function SubscriptionBanner({ subscription }) {
  if (!subscription?.show_banner) return null;
  const danger = subscription.severity === "danger";
  const label = ({ trial: "Masa Trial", active: "Langganan", grace: "Masa Tenggang", expired: "Langganan Berakhir", suspended: "Langganan Ditangguhkan" })[subscription.status] || "Informasi Langganan";
  return <div className={`rounded-2xl border p-4 ${danger ? "border-[#EEDADA] bg-[#FBF3F3] text-[#8F3F3F]" : "border-[#EEE2CA] bg-[#FBF7EF] text-[#80571D]"}`} data-testid="dash-subscription-banner">
    <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1"><div className="font-head text-sm font-semibold">{label}</div><div className="mt-1 text-sm leading-6">{subscription.message}</div>
        {subscription.tenant_code && <div className="mt-2 text-[11px] opacity-80">Kode Tenant: <span className="font-mono font-semibold">{subscription.tenant_code}</span></div>}</div></div>
  </div>;
}

function Field({ label, children }) {
  return <label className="flex min-w-0 flex-col gap-1.5"><span className="text-xs font-medium text-slate-500">{label}</span>{children}</label>;
}

function SectionLabel({ children, extra, testid }) {
  return <div className="flex items-center justify-between gap-3 pt-1" data-testid={testid}><h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{children}</h2>{extra}</div>;
}

function SectionBadge({ children, testid }) {
  return <span className="rounded-md bg-slate-100/80 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800/60 dark:text-slate-400" data-testid={testid}>{children}</span>;
}

function LoadingState() {
  return <div className="space-y-5" data-testid="dash-loading">
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5 2xl:grid-cols-9">{Array.from({ length: 9 }).map((_, i) => <Skeleton key={i} className="h-[122px] rounded-2xl" />)}</div>
    <div className="grid gap-4 xl:grid-cols-12"><Skeleton className="h-[330px] rounded-2xl xl:col-span-7" /><Skeleton className="h-[330px] rounded-2xl xl:col-span-5" /></div>
  </div>;
}

export default function Dashboard() {
  const nav = useNavigate();
  const { can } = useAuth();
  const { data: m } = useMasters(["divisions", "projects", "suppliers"]);
  const [f, setF] = useState(DEFAULT);
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unvaluedOpen, setUnvaluedOpen] = useState(false);
  const [drill, setDrill] = useState(null); // drill-down SPK / Kontrak (posisi: date_to) / Price Control (periode)
  const [subscription, setSubscription] = useState(null);
  const [updated, setUpdated] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.get("/dashboard/control-center", { params: ccParams(f) });
      setD(r.data); setUpdated(new Date());
    } catch (e) { setError(apiError(e.response?.data?.detail) || "Dashboard gagal dimuat."); }
    finally { setLoading(false); }
  }, [f]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(load, REFRESH_MS); return () => clearInterval(t); }, [load]);
  useEffect(() => { api.get("/subscription/status").then((r) => setSubscription(r.data)).catch(() => {}); }, []);

  const scopeDivs = d?.scope?.divisions; // null = semua divisi; daftar = cakupan user (backend tetap menolak di luar cakupan)
  const opts = useMemo(() => ({
    div: [{ value: "", label: "Semua Divisi" },
      ...(m.divisions || []).filter((x) => !scopeDivs || scopeDivs.includes(x.id)).map((x) => ({ value: x.id, label: x.name }))],
    prj: [{ value: "", label: "Semua Project" }, ...(m.projects || []).map((x) => ({ value: x.id, label: x.name }))],
    sup: [{ value: "", label: "Semua Supplier" }, ...(m.suppliers || []).map((x) => ({ value: x.id, label: x.name }))],
  }), [m, scopeDivs]);
  const set = (k) => (v) => setF((c) => ({ ...c, [k]: v || "" }));
  const dirty = JSON.stringify(f) !== JSON.stringify(DEFAULT);
  const perms = d?.permissions || {};
  const go = (kind) => nav(drillLink(kind, f, perms));
  const P = d?.procurement, F = d?.finance;
  const val = (x, compact = true) => (x?.value == null ? null : compact ? compactRupiah(x.value) : rupiah(x.value));
  const sub = (x, extra) => [val(x), extra].filter(Boolean).join(" · ");
  const STATUS_KIND = { "Waiting Approval 1": "waiting_a1", "Ready Approval 2": "ready_a2", "Waiting Approval 2": "waiting_a2", "Approved": "approved" };
  const pickStatus = (s) => {
    if (STATUS_KIND[s]) return nav(drillLink(STATUS_KIND[s], f, {}));
    const base = drillLink("po_all", f, {});
    return nav(`${base}${base.includes("?") ? "&" : "?"}f_document_status=${encodeURIComponent(s)}`);
  };
  const pickSupplier = (id) => nav(drillLink("valid", { ...f, supplier_id: id }, {}));

  const procCards = P ? [
    P.mro_open && { k: "mro_open", label: "MRO Belum Diproses", icon: ClipboardList, tone: "slate", x: P.mro_open, hint: "MRO yang masih memiliki sisa qty belum diproses menjadi RO / MI." },
    P.ro_open && { k: "ro_open", label: "RO Belum Menjadi PO", icon: PackageOpen, tone: "slate", x: P.ro_open, hint: "RO yang masih memiliki sisa qty belum dibuatkan PO." },
    { k: "waiting_a1", label: "Menunggu Approval 1", icon: Hourglass, tone: "amber", x: P.waiting_a1 },
    { k: "ready_a2", label: "Siap Diajukan Approval 2", icon: Send, tone: "blue", x: P.ready_a2 },
    { k: "waiting_a2", label: "Menunggu Approval 2", icon: Clock3, tone: "amber", x: P.waiting_a2 },
    { k: "not_received", label: "PO Belum Diterima", icon: Truck, tone: "navy", x: P.not_received },
    { k: "partial", label: "PO Diterima Sebagian", icon: PackageCheck, tone: "indigo", x: P.partial },
    { k: "late", label: "PO Terlambat", icon: Timer, tone: "red", x: P.late, alert: P.late.count > 0, hint: "Disetujui, belum diterima penuh, dan ETA sudah lewat." },
  ].filter(Boolean) : [];
  const finCards = F ? [
    { k: "invoice_unbilled", label: "Invoice Belum Diterima", icon: FileClock, tone: "blue", x: F.invoice_unbilled, unit: "DO", hint: "Barang sudah diterima tetapi invoice supplier belum diterima seluruhnya." },
    { k: "unpaid", label: "Invoice Belum Dibayar", icon: FileWarning, tone: "navy", x: F.invoice_unpaid, hint: "Invoice dengan sisa kewajiban (nilai − DP dialokasikan − pembayaran) > 0." },
    { k: "due_soon", label: "Jatuh Tempo ≤ 7 Hari", icon: AlarmClock, tone: "amber", x: F.due_soon, alert: F.due_soon.count > 0 },
    { k: "overdue", label: "Lewat Jatuh Tempo", icon: CircleAlert, tone: "red", x: F.overdue, alert: F.overdue.count > 0 },
    { k: "payable", label: "Sisa Hutang Supplier", icon: Landmark, tone: "navy", x: F.payable, money: true, hint: "Σ max(nilai invoice − DP dialokasikan − pembayaran, 0)." },
    F.dp_unallocated && { k: "dp_unallocated", label: "DP Supplier Belum Dialokasikan", icon: HandCoins, tone: "slate", x: F.dp_unallocated, money: true, hint: "DP yang sudah dibayar dikurangi DP yang sudah dialokasikan ke invoice." },
  ].filter(Boolean) : [];
  // Kelompok B — aktivitas di dalam periode filter (drill membawa date_from + date_to).
  const actCards = [
    P && { k: "po_all", label: "Total PO", icon: ClipboardList, tone: "navy", x: P.po_total, sub: P.po_value?.value != null ? `Nilai PO valid ${compactRupiah(P.po_value.value)}` : "dokumen" },
    P && { k: "approved", label: "PO Disetujui", icon: CheckCircle2, tone: "green", x: P.approved },
    F?.dp_paid && { k: "dp_paid", label: "DP Sudah Dibayar", icon: Wallet, tone: "green", x: F.dp_paid, money: true, hint: "Pembayaran DP Supplier bertanggal di dalam periode." },
  ].filter(Boolean);
  const posLabel = `Posisi s/d ${asOfLabel(d?.as_of)}`;
  const actLabel = "Transaksi periode ini";
  const SP = d?.spk, VC = d?.vendor_contract;
  const drillSpk = (kind) => setDrill({ type: "spk", params: spkDrillParams(SP?.as_of, f, kind) });
  const drillContract = (kind) => setDrill({ type: "contract", params: contractDrillParams(VC?.as_of, f, kind) });
  const drillPrice = (status) => setDrill({ type: "price", params: priceDrillParams(f, status) });

  return <div className="space-y-5" data-testid="dashboard-page">
    <SubscriptionBanner subscription={subscription} />
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-head text-[26px] font-semibold tracking-tight text-slate-900 dark:text-slate-50">Dashboard Procurement &amp; Finance</h1>
        <p className="mt-1 text-sm text-slate-500">Ringkasan pembelian, penerimaan, invoice, dan hutang supplier.</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="hidden items-center gap-2 text-xs text-slate-400 md:flex" data-testid="dash-updated">
          <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#5E9C82] opacity-40" /><span className="relative inline-flex h-2 w-2 rounded-full bg-[#5E9C82]" /></span>
          {updated ? `Diperbarui ${updated.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}` : "Memuat..."}
        </span>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} className="rounded-xl" data-testid="dash-refresh-btn"><RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />Muat Ulang</Button>
        {can("create", "mro") && <Button variant="outline" size="sm" onClick={() => nav("/mro/new")} className="rounded-xl" data-testid="dashboard-new-mro-btn"><Plus className="mr-2 h-4 w-4" />MRO Baru</Button>}
      </div>
    </div>

    <div className="dash-rise grid grid-cols-1 gap-3 rounded-2xl border border-slate-200/70 bg-card p-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:grid-cols-2 lg:grid-cols-[1.2fr_1fr_1fr_1fr_auto] dark:border-slate-800" data-testid="dash-filters">
      <Field label="Periode">
        <Select value={f.period} onValueChange={set("period")}>
          <SelectTrigger className="h-10 rounded-xl" data-testid="dash-filter-period"><CalendarDays className="mr-2 h-4 w-4 text-slate-400" /><SelectValue /></SelectTrigger>
          <SelectContent>{PERIODS.map((p) => <SelectItem key={p.key} value={p.key} data-testid={`dash-period-${p.key}`}>{p.key === "this_month" ? `Bulan Ini (${periodText("this_month")})` : p.label}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <Field label="Divisi"><Combobox options={opts.div} value={f.division_id} onChange={set("division_id")} placeholder="Semua Divisi" testid="dash-filter-division" /></Field>
      <Field label="Project"><Combobox options={opts.prj} value={f.project_id} onChange={set("project_id")} placeholder="Semua Project" testid="dash-filter-project" /></Field>
      <Field label="Supplier"><Combobox options={opts.sup} value={f.supplier_id} onChange={set("supplier_id")} placeholder="Semua Supplier" testid="dash-filter-supplier" /></Field>
      <div className="flex items-end"><Button variant="secondary" onClick={() => setF(DEFAULT)} disabled={!dirty} className="h-10 w-full rounded-xl lg:w-auto" data-testid="dash-filter-reset"><RotateCcw className="mr-2 h-4 w-4" />Reset</Button></div>
    </div>

    {error && <div className="flex items-center justify-between gap-3 rounded-2xl border border-[#EEDADA] bg-[#FBF3F3] p-4 text-sm text-[#8F3F3F]" data-testid="dash-error">
      <span>{error}</span><Button size="sm" variant="outline" onClick={load} data-testid="dash-retry-btn">Coba Lagi</Button></div>}
    {!d && loading && <LoadingState />}

    {d && <div className={`space-y-5 transition-opacity duration-200 ${loading ? "opacity-60" : "opacity-100"}`}>
      {/* LAYER 1 — Kondisi operasional utama: Procurement · Finance · Aktivitas Pembelian */}
      <div className="space-y-5" data-testid="dash-layer-1">
      {P && <>
        <SectionLabel testid="dash-section-procurement" extra={<SectionBadge testid="dash-procurement-asof">saldo terbuka s/d tanggal posisi · termasuk periode sebelumnya</SectionBadge>}>Procurement — {posLabel}</SectionLabel>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 2xl:grid-cols-8" data-testid="dash-procurement-kpis">
          {procCards.map((c, i) => <KpiCard key={c.k} label={c.label} icon={c.icon} tone={c.tone} count={c.x.count} sub={sub(c.x) || (c.x.count ? "dokumen" : "Tidak ada")}
            hint={c.hint} alert={c.alert} delay={i * 45} onClick={() => go(c.k)} testid={`dash-kpi-${c.k}`} />)}
        </div>
      </>}
      {F && <>
        <SectionLabel testid="dash-section-finance" extra={<SectionBadge testid="dash-finance-asof">saldo terbuka s/d tanggal posisi · termasuk periode sebelumnya</SectionBadge>}>Finance — {posLabel}</SectionLabel>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6" data-testid="dash-finance-kpis">
          {finCards.map((c, i) => <KpiCard key={c.k} label={c.label} icon={c.icon} tone={c.tone} hint={c.hint} alert={c.alert} delay={200 + i * 45}
            count={c.money ? c.x.value : c.x.count} format={c.money ? (v) => compactRupiah(v) : undefined}
            sub={c.money ? `${c.x.count} ${c.k === "payable" ? "invoice" : "PO"}` : `${c.unit || "invoice"} · ${compactRupiah(c.x.value)}`}
            onClick={() => go(c.k)} testid={`dash-kpi-${c.k}`} />)}
        </div>
      </>}

      <SectionLabel testid="dash-section-activity" extra={<SectionBadge testid="dash-activity-period">{actLabel} · {periodText(f.period)}</SectionBadge>}>Aktivitas Pembelian — {actLabel}</SectionLabel>
      {actCards.length > 0 && <div className="grid grid-cols-2 gap-3 md:grid-cols-3" data-testid="dash-activity-kpis">
        {actCards.map((c, i) => <KpiCard key={c.k} label={c.label} icon={c.icon} tone={c.tone} hint={c.hint} delay={240 + i * 45}
          count={c.money ? c.x.value : c.x.count} format={c.money ? (v) => compactRupiah(v) : undefined}
          sub={c.money ? `${c.x.count} PO` : c.sub || sub(c.x) || (c.x.count ? "dokumen" : "Tidak ada")}
          onClick={() => go(c.k)} testid={`dash-kpi-${c.k}`} />)}
      </div>}
      </div>{/* /Layer 1 */}

      {/* LAYER 2 — Kontrol aset, budget & kontrak: Persediaan | SPK | Kontrak Harga Vendor */}
      {(d.inventory?.stock || SP || VC) && <div className="grid grid-cols-1 gap-4 pt-1 xl:grid-cols-2 2xl:grid-cols-3" data-testid="dash-layer-2">
        {d.inventory?.stock && <div className="min-w-0" data-testid="dash-section-inventory">
          <InventoryPanel inv={d.inventory} f={f} nav={nav} onUnvalued={() => setUnvaluedOpen(true)} delay={260} /></div>}
        {SP && <div className="min-w-0" data-testid="dash-section-spk">
          <SpkSummaryCard spk={SP} subtitle={<span data-testid="dash-spk-asof">Posisi s/d {asOfLabel(SP.as_of)} · ikut Divisi &amp; Project</span>} onDrill={drillSpk} delay={300} /></div>}
        {VC && <div className="min-w-0 xl:col-span-2 2xl:col-span-1" data-testid="dash-section-contract">
          <ContractStatusPanel vc={VC} posLabel={`Posisi s/d ${asOfLabel(VC.as_of)}`} onDrill={drillContract} canDrill={!!perms.vendor_contract} nav={nav} delay={340} /></div>}
      </div>}

      {/* LAYER 3 — Analitik */}
      <div data-testid="dash-layer-3">
      <div className="grid gap-4 xl:grid-cols-12">
        <div className={`min-w-0 ${d.charts?.composition || d.supplier_rank ? "xl:col-span-6" : "xl:col-span-12"}`}><TrendChart trend={d.charts?.trend} delay={380} /></div>
        {d.charts?.composition && <div className="min-w-0 xl:col-span-3"><StatusDonut composition={d.charts.composition} onPick={pickStatus} delay={420} /></div>}
        {d.supplier_rank && <div className={`min-w-0 ${d.charts?.composition ? "xl:col-span-3" : "xl:col-span-6"}`}><TopSuppliers rank={d.supplier_rank} onPick={pickSupplier} delay={460} /></div>}
      </div>
      </div>

      {/* LAYER 4 — Tindakan / monitoring */}
      <div className="space-y-5" data-testid="dash-layer-4">
      <SectionLabel testid="dash-section-attention" extra={<SectionBadge testid="dash-attention-asof">saldo terbuka s/d tanggal posisi · termasuk periode sebelumnya</SectionBadge>}>Perlu Ditindaklanjuti — {posLabel}</SectionLabel>
      <div className="grid gap-4 xl:grid-cols-12">
        <div className={`min-w-0 ${F ? "xl:col-span-8" : "xl:col-span-12"}`}><AttentionTable attention={d.attention} finance={!!F} filters={f} delay={380} /></div>
        {F && <div className="flex min-w-0 flex-col gap-4 xl:col-span-4">
          <FinanceMonitor finance={F} periodLabel={posLabel} delay={430} onPick={(k) => go(k === "invoice_unpaid" ? "unpaid" : k)} />
        </div>}
      </div>
      </div>

      {/* Detail lanjutan (section existing): Pemakaian Budget SPK + Price Control / Price Exception */}
      {(SP?.with_value || VC?.price_control) && <div className="space-y-5" data-testid="dash-layer-detail">
        {SP?.with_value && <>
          <SectionLabel testid="dash-section-spk-detail" extra={<SectionBadge testid="dash-spk-detail-asof">posisi s/d tanggal akhir filter · ikut Divisi &amp; Project</SectionBadge>}>SPK &amp; Budget Control — Posisi s/d {asOfLabel(SP.as_of)}</SectionLabel>
          <SpkDetailPanel spk={SP} onDrill={drillSpk} nav={nav} delay={540} />
        </>}
        {VC?.price_control && <>
          <SectionLabel testid="dash-section-price" extra={<SectionBadge testid="dash-contract-semantics">status kontrak per tanggal posisi · Price Control per periode</SectionBadge>}>Kontrak Harga Vendor — Price Control</SectionLabel>
          <div className="grid gap-4 xl:grid-cols-12" data-testid="dash-contract-grid">
            <div className="min-w-0 xl:col-span-5">
              <PriceControlPanel vc={VC} actLabel={`Price Control — ${actLabel} · ${periodText(f.period)}`} onDrill={drillPrice} delay={580} /></div>
            <div className="min-w-0 xl:col-span-7">
              <PriceExceptionTable vc={VC} actLabel={`${actLabel} · ${periodText(f.period)}`} nav={nav} onDrill={drillPrice} delay={620} /></div>
          </div>
        </>}
      </div>}
    </div>}
    <DashboardDrillDialog drill={drill} onOpenChange={(o) => !o && setDrill(null)} nav={nav} />
    {d?.inventory?.unvalued_items > 0 && <UnvaluedStockDialog open={unvaluedOpen} onOpenChange={setUnvaluedOpen} divisionId={f.division_id} />}
  </div>;
}
