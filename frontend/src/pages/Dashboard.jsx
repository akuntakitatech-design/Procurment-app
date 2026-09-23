import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  ShoppingCart, PackageCheck, Clock3, AlertTriangle, ShieldCheck, FileText,
  ClipboardList, PackageMinus, Handshake, ArrowRight, ChevronDown, ChevronRight,
  Boxes, Building2, Layers3, Plus
} from "lucide-react";
import { rupiah, num } from "@/lib/format";

const money = (v, allowed = true) => allowed && v != null ? rupiah(v) : "***";

function MetricCard({ label, value, sub, icon: Icon, onClick, tone = "navy" }) {
  const tones = {
    navy: "bg-[#F4F7FB] text-[#244B72] ring-[#DDE7F2]",
    green: "bg-[#F2F8F5] text-[#2F6B57] ring-[#D9EADF]",
    amber: "bg-[#FBF7EF] text-[#9A6A22] ring-[#EEE2CA]",
    red: "bg-[#FBF3F3] text-[#A34B4B] ring-[#EEDADA]",
  };
  return <button onClick={onClick} className="group rounded-2xl border bg-card p-4 sm:p-5 text-left transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_16px_40px_-28px_rgba(15,23,42,0.45)]">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
        <div className="mt-2 truncate font-head text-2xl font-bold tracking-tight text-foreground sm:text-[28px]">{value}</div>
        {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
      </div>
      {Icon && <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1 ${tones[tone] || tones.navy}`}><Icon className="h-4.5 w-4.5" /></div>}
    </div>
  </button>;
}

function SectionTitle({ title, subtitle, action }) {
  return <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
    <div><h2 className="font-head text-lg font-semibold">{title}</h2>{subtitle && <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>}</div>
    {action}
  </div>;
}

function MiniRank({ title, icon: Icon, rows, financial }) {
  const max = Math.max(...rows.map((r) => Number(r.value) || 0), 1);
  return <Card className="rounded-2xl shadow-none"><CardContent className="p-5">
    <div className="flex items-center gap-2"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/8 text-primary"><Icon className="h-4 w-4" /></div><h3 className="font-head text-sm font-semibold">{title}</h3></div>
    <div className="mt-5 space-y-4">
      {rows.length === 0 && <div className="text-sm text-muted-foreground">Belum ada data untuk periode ini.</div>}
      {rows.map((r, i) => <div key={`${r.name}-${i}`}>
        <div className="flex items-center justify-between gap-3 text-sm"><span className="truncate font-medium">{r.name}</span><span className="shrink-0 font-mono text-xs text-muted-foreground">{money(r.value, financial)}</span></div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(5, (Number(r.value) || 0) / max * 100)}%` }} /></div>
      </div>)}
    </div>
  </CardContent></Card>;
}

function SubscriptionBanner({ subscription }) {
  if (!subscription?.show_banner) return null;
  const danger = subscription.severity === "danger";
  const style = danger
    ? "border-[#EEDADA] bg-[#FBF3F3] text-[#8F3F3F]"
    : "border-[#EEE2CA] bg-[#FBF7EF] text-[#80571D]";
  const label = ({ trial: "Masa Trial", active: "Langganan", grace: "Masa Tenggang", expired: "Langganan Berakhir", suspended: "Langganan Ditangguhkan" })[subscription.status] || "Informasi Langganan";
  return <div className={`rounded-2xl border p-4 sm:p-5 ${style}`}>
    <div className="flex items-start gap-3">
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-head text-sm font-semibold">{label}</div>
        <div className="mt-1 text-sm leading-6">{subscription.message}</div>
        {subscription.tenant_code && <div className="mt-2 text-[11px] opacity-80">Kode Tenant: <span className="font-mono font-semibold">{subscription.tenant_code}</span></div>}
      </div>
    </div>
  </div>;
}

export default function Dashboard() {
  const [d, setD] = useState(null);
  const [p, setP] = useState(null);
  const [subscription, setSubscription] = useState(null);
  const [expanded, setExpanded] = useState({});
  const nav = useNavigate();

  useEffect(() => {
    Promise.all([
      api.get("/dashboard"),
      api.get("/dashboard-premium"),
      api.get("/subscription/status").catch(() => ({ data: null })),
    ]).then(([base, premium, sub]) => {
      setD(base.data);
      setP(premium.data);
      setSubscription(sub.data || null);
    });
  }, []);

  const dateText = useMemo(() => new Date().toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long", year: "numeric" }), []);
  if (!d || !p) return <div className="rounded-2xl border bg-card p-6 text-sm text-muted-foreground">Memuat control center...</div>;

  const po = p.po || {};
  const financial = !!p.financial_visible;
  const attention = [
    { label: "Approval menunggu tindakan", value: p.attention?.pending_approvals || 0, to: "/approval", tone: "amber" },
    { label: "PO melewati estimasi datang", value: p.attention?.overdue_po || 0, to: "/po", tone: "red" },
    { label: "Pinjaman melewati jatuh tempo", value: p.attention?.overdue_loans || 0, to: "/loan", tone: "amber" },
    { label: "Item stok habis", value: d.stock?.out_of_stock || 0, to: "/inventory", tone: "red" },
    { label: "Item stok menipis", value: d.stock?.low_stock || 0, to: "/inventory", tone: "amber" },
  ].filter((x) => x.value > 0);

  const flow = [
    { code: "MRO", label: "Permintaan Material", value: d.mro_open, to: "/mro", icon: FileText },
    { code: "RO", label: "Permintaan Pembelian", value: d.ro_open, to: "/ro", icon: ClipboardList },
    { code: "PO", label: "PO Outstanding", value: d.po_outstanding, to: "/po", icon: ShoppingCart },
    { code: "DO", label: "Diterima Hari Ini", value: d.do_today, to: "/do", icon: PackageCheck },
    { code: "MI", label: "Keluar Hari Ini", value: d.mi_today, to: "/mi", icon: PackageMinus },
  ];

  return <div className="space-y-7">
    <PageHeader title="Dashboard" subtitle={`Control center operasional · ${dateText}`}>
      <Button variant="outline" onClick={() => nav("/mro/new")} className="rounded-xl"><Plus className="mr-2 h-4 w-4" />MRO Baru</Button>
      <Button onClick={() => nav("/po/new")} className="rounded-xl"><Plus className="mr-2 h-4 w-4" />PO Baru</Button>
    </PageHeader>

    <SubscriptionBanner subscription={subscription} />

    <section className="space-y-4">
      <SectionTitle title="Ringkasan Pembelian" subtitle={`Kinerja Purchase Order tahun ${p.year}. Nilai menggunakan basis DPP / sebelum pajak.`} />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard label="Total PO" value={num(po.total_docs)} sub={`${num(po.line_count)} item pembelian`} icon={ShoppingCart} onClick={() => nav("/po")} />
        <MetricCard label="Closed" value={num(po.closed_lines)} sub="item selesai diterima" icon={ShieldCheck} tone="green" onClick={() => nav("/po")} />
        <MetricCard label="Partial" value={num(po.partial_lines)} sub="item diterima sebagian" icon={Clock3} tone="amber" onClick={() => nav("/po")} />
        <MetricCard label="Belum Diterima" value={num(po.not_received_lines)} sub="item belum diterima" icon={PackageMinus} tone="amber" onClick={() => nav("/po")} />
        <MetricCard label="Over Delivery" value={num(po.over_delivery_lines)} sub="item melebihi qty PO" icon={AlertTriangle} tone={po.over_delivery_lines ? "red" : "green"} onClick={() => nav("/po")} />
        <MetricCard label="Nilai PO" value={money(po.po_value, financial)} sub="DPP sebelum pajak" icon={ShoppingCart} />
        <MetricCard label="Nilai Diterima" value={money(po.received_value, financial)} sub="berdasarkan harga PO" icon={PackageCheck} tone="green" />
        <MetricCard label="Outstanding" value={money(po.outstanding_value, financial)} sub="qty pending × harga PO" icon={Clock3} tone="amber" />
      </div>
    </section>

    <section className="space-y-4">
      <SectionTitle title="Alur Operasional" subtitle="Posisi pekerjaan utama dari permintaan sampai barang keluar gudang." />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-5">
        {flow.map((x, i) => <div key={x.code} className="flex items-stretch gap-2">
          <button onClick={() => nav(x.to)} className="flex-1 rounded-2xl border bg-card p-4 text-left transition-all hover:border-primary/25 hover:shadow-sm">
            <div className="flex items-center justify-between"><span className="font-head text-xs font-bold tracking-[0.12em] text-primary">{x.code}</span><x.icon className="h-4 w-4 text-muted-foreground" /></div>
            <div className="mt-3 font-head text-2xl font-bold">{num(x.value)}</div>
            <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{x.label}</div>
          </button>
          {i < flow.length - 1 && <div className="hidden items-center text-muted-foreground/40 sm:flex"><ArrowRight className="h-4 w-4" /></div>}
        </div>)}
      </div>
    </section>

    <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <Card className="rounded-2xl shadow-none"><CardContent className="p-5">
        <SectionTitle title="Perlu Perhatian" subtitle="Item yang memerlukan tindakan operasional." />
        <div className="mt-4 divide-y">
          {attention.length === 0 && <div className="rounded-xl bg-[#F2F8F5] p-4 text-sm text-[#2F6B57]">Tidak ada isu kritis yang terdeteksi saat ini.</div>}
          {attention.map((x) => <button key={x.label} onClick={() => nav(x.to)} className="flex w-full items-center gap-3 py-3 text-left hover:bg-muted/30 px-1 rounded-lg">
            <span className={`h-2.5 w-2.5 rounded-full ${x.tone === "red" ? "bg-[#B54747]" : "bg-[#B7791F]"}`} />
            <span className="flex-1 text-sm font-medium">{x.label}</span>
            <span className="font-head text-lg font-bold">{num(x.value)}</span><ChevronRight className="h-4 w-4 text-muted-foreground" />
          </button>)}
        </div>
      </CardContent></Card>

      <Card className="rounded-2xl shadow-none"><CardContent className="p-5">
        <SectionTitle title="Kesehatan Persediaan" subtitle="Ringkasan kondisi stok saat ini." />
        <div className="mt-5 grid grid-cols-2 gap-3">
          <button onClick={() => nav("/inventory")} className="rounded-xl bg-[#F4F7FB] p-4 text-left"><div className="text-xs text-muted-foreground">Total SKU</div><div className="mt-1 font-head text-2xl font-bold">{num(d.stock?.total)}</div></button>
          <button onClick={() => nav("/inventory")} className="rounded-xl bg-[#F2F8F5] p-4 text-left"><div className="text-xs text-muted-foreground">Normal</div><div className="mt-1 font-head text-2xl font-bold text-[#2F6B57]">{num(d.stock?.normal)}</div></button>
          <button onClick={() => nav("/inventory")} className="rounded-xl bg-[#FBF7EF] p-4 text-left"><div className="text-xs text-muted-foreground">Menipis</div><div className="mt-1 font-head text-2xl font-bold text-[#9A6A22]">{num(d.stock?.low_stock)}</div></button>
          <button onClick={() => nav("/inventory")} className="rounded-xl bg-[#FBF3F3] p-4 text-left"><div className="text-xs text-muted-foreground">Habis</div><div className="mt-1 font-head text-2xl font-bold text-[#A34B4B]">{num(d.stock?.out_of_stock)}</div></button>
        </div>
      </CardContent></Card>
    </section>

    <section className="space-y-4">
      <SectionTitle title="Ringkasan Nilai Bulanan" subtitle="Klik bulan untuk melihat detail nilai per kategori barang." />
      <Card className="rounded-2xl shadow-none overflow-hidden">
        <CardContent className="p-0">
          {!financial && <div className="p-5 text-sm text-muted-foreground">Nilai pembelian disembunyikan karena user tidak memiliki izin melihat harga pembelian.</div>}
          {financial && <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm">
            <thead className="bg-muted/55 text-[11px] uppercase tracking-wider text-muted-foreground"><tr><th className="p-3 text-left w-12"></th><th className="p-3 text-left">Bulan</th><th className="p-3 text-right">Nilai PO</th><th className="p-3 text-right">Nilai Diterima</th><th className="p-3 text-right">Outstanding</th></tr></thead>
            <tbody>{p.monthly.map((r) => <MonthRows key={r.month} row={r} open={!!expanded[r.month]} toggle={() => setExpanded((s) => ({ ...s, [r.month]: !s[r.month] }))} />)}</tbody>
          </table></div>}
        </CardContent>
      </Card>
    </section>

    <section className="grid gap-4 xl:grid-cols-2">
      <MiniRank title="Top Kategori Pembelian" icon={Layers3} rows={p.top_categories || []} financial={financial} />
      <MiniRank title="Top Supplier" icon={Building2} rows={p.top_suppliers || []} financial={financial} />
    </section>
  </div>;
}

function MonthRows({ row, open, toggle }) {
  return <>
    <tr className="border-t hover:bg-muted/25 cursor-pointer" onClick={toggle}>
      <td className="p-3 text-center">{open ? <ChevronDown className="inline h-4 w-4 text-muted-foreground" /> : <ChevronRight className="inline h-4 w-4 text-muted-foreground" />}</td>
      <td className="p-3 font-mono text-xs font-semibold">{row.month}</td>
      <td className="p-3 text-right font-medium">{rupiah(row.po_value)}</td>
      <td className="p-3 text-right">{rupiah(row.received_value)}</td>
      <td className="p-3 text-right font-semibold">{rupiah(row.outstanding)}</td>
    </tr>
    {open && (row.categories || []).map((c) => <tr key={`${row.month}-${c.category}`} className="border-t bg-muted/18">
      <td></td><td className="p-3 pl-8 text-xs text-muted-foreground">↳ {c.category}</td><td className="p-3 text-right text-xs">{rupiah(c.po_value)}</td><td className="p-3 text-right text-xs">{rupiah(c.received_value)}</td><td className="p-3 text-right text-xs font-medium">{rupiah(c.outstanding)}</td>
    </tr>)}
  </>;
}
