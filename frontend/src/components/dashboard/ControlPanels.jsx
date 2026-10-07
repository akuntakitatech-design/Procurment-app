import { ArrowRight } from "lucide-react";
import { TONES } from "@/lib/dashboard";
import { CountUp } from "./KpiCard";

/** Pita judul berwarna (Layer 1, sesuai referensi). Gradient tipis satu hue, hanya pada pita. */
const BANDS = {
  navy: "bg-gradient-to-r from-[#34557E] to-[#5476A3]",
  teal: "bg-gradient-to-r from-[#2F6F6A] to-[#4E8F86]",
};

export function ControlSection({ title, subtitle, icon: Icon, band = "navy", onDetail, testid, children, className = "", delay = 0 }) {
  return <section className={`dash-rise flex min-w-0 flex-col rounded-2xl border border-slate-200/70 bg-card p-2 shadow-[0_1px_2px_rgba(15,23,42,0.03)] dark:border-slate-800 ${className}`}
    style={{ "--d": `${delay}ms` }} data-testid={testid && `${testid}-panel`}>
    <header className={`flex items-center gap-3 rounded-xl px-4 py-2.5 text-white ${BANDS[band] || BANDS.navy}`} data-testid={testid}>
      {Icon && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/15"><Icon className="h-[18px] w-[18px]" /></span>}
      <span className="min-w-0 flex-1">
        <h2 className="truncate font-head text-[15px] font-semibold leading-tight">{title}</h2>
        {subtitle && <span className="mt-0.5 block truncate text-[11.5px] text-white/75">{subtitle}</span>}
      </span>
      {onDetail && <button type="button" onClick={onDetail} data-testid={testid && `${testid}-detail`}
        className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-white/90 transition-colors hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60">
        Lihat Detail<ArrowRight className="h-3.5 w-3.5" /></button>}
    </header>
    <div className="flex flex-1 flex-col p-2 pt-3">{children}</div>
  </section>;
}

function Pulse() {
  return <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#C46A6A] opacity-40" /><span className="relative inline-flex h-2 w-2 rounded-full bg-[#C46A6A]" /></span>;
}

/** Procurement: angka di dalam cincin. Busur = porsi dokumen ini terhadap total dokumen terbuka di panel (tampilan saja). */
export function RingStat({ label, count, share, sub, tone = "navy", hint, alert, onClick, testid, delay = 0 }) {
  const t = TONES[tone] || TONES.navy;
  const size = 52, stroke = 4.5, r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const fill = share == null ? 0 : Math.max(0.03, Math.min(1, share / 100));
  return <button type="button" onClick={onClick} disabled={!onClick} data-testid={testid} title={hint} style={{ "--d": `${delay}ms` }}
    className="dash-rise flex min-w-0 items-center gap-2.5 rounded-xl border border-slate-200/60 bg-white/70 p-2.5 text-left transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-slate-300/80 hover:shadow-[0_12px_28px_-22px_rgba(15,23,42,0.35)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30 active:translate-y-0 disabled:cursor-default dark:border-slate-800 dark:bg-slate-900/40">
    <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-slate-100 dark:text-slate-800" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={t.bar} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={c}
          strokeDashoffset={c * (1 - fill)} className="transition-[stroke-dashoffset] duration-700 ease-out" />
      </svg>
      <span className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-head text-[16px] font-bold leading-none text-slate-900 tabular-nums dark:text-slate-50" data-testid={testid && `${testid}-count`}>
          {count == null ? "-" : <CountUp value={count} />}</span>
        {share != null && <span className="mt-0.5 text-[9px] font-medium text-slate-400 tabular-nums" data-testid={testid && `${testid}-share`}>{Math.round(share)}%</span>}
      </span>
    </span>
    <span className="min-w-0 flex-1">
      <span className="flex items-start gap-1.5"><span className="text-[12px] font-semibold leading-tight text-slate-700 dark:text-slate-200">{label}</span>{alert && <Pulse />}</span>
      <span className="mt-1 block truncate text-[11px] text-slate-400" data-testid={testid && `${testid}-sub`}>{sub}</span>
    </span>
  </button>;
}

/** Finance: tile berlatar warna lembut sesuai tone, ikon di kotak putih. */
export function SoftStat({ label, count, format, sub, icon: Icon, tone = "navy", hint, alert, onClick, testid, delay = 0 }) {
  const t = TONES[tone] || TONES.navy;
  const [bg] = t.icon.split(" ");
  return <button type="button" onClick={onClick} disabled={!onClick} data-testid={testid} title={hint} style={{ "--d": `${delay}ms` }}
    className={`dash-rise flex min-w-0 items-center gap-3 rounded-xl p-3.5 text-left transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-[0_12px_28px_-22px_rgba(15,23,42,0.35)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30 active:translate-y-0 disabled:cursor-default dark:bg-slate-900/50 ${bg}`}>
    {Icon && <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white shadow-[0_1px_2px_rgba(15,23,42,0.05)] dark:bg-slate-900 ${t.text}`}><Icon className="h-[18px] w-[18px]" /></span>}
    <span className="min-w-0 flex-1">
      <span className="flex items-center gap-1.5"><span className={`truncate font-head text-[20px] font-bold leading-tight tabular-nums ${t.text}`} data-testid={testid && `${testid}-count`}>
        {count == null ? "-" : <CountUp value={count} format={format} />}</span>{alert && <Pulse />}</span>
      <span className="mt-0.5 block text-[12px] font-medium leading-snug text-slate-600 dark:text-slate-300">{label}</span>
      <span className="block truncate text-[11px] text-slate-400" data-testid={testid && `${testid}-sub`}>{sub}</span>
    </span>
  </button>;
}

/** Bar mini (sparkline) dari seri tren existing (charts.trend) — data nyata, tanpa angka perbandingan sintetis. */
export function MiniBars({ values = [], tone = "blue", testid }) {
  const t = TONES[tone] || TONES.blue;
  const max = Math.max(...values, 0);
  if (!values.length || max <= 0) return null;
  return <span className="flex h-12 items-end gap-[3px]" aria-hidden data-testid={testid}>
    {values.map((v, i) => <span key={i} className="w-[5px] rounded-t-sm" style={{ height: `${Math.max(6, (v / max) * 100)}%`, background: t.bar, opacity: 0.35 + (0.65 * (i + 1)) / values.length }} />)}
  </span>;
}

/** Aktivitas Pembelian: kartu putih dengan nilai besar (+ bar mini bila ada seri tren). */
export function ActivityStat({ label, count, format, sub, icon: Icon, tone = "navy", hint, onClick, testid, bars, wide, delay = 0 }) {
  const t = TONES[tone] || TONES.navy;
  return <button type="button" onClick={onClick} disabled={!onClick} data-testid={testid} title={hint} style={{ "--d": `${delay}ms` }}
    className={`dash-rise flex min-w-0 flex-col rounded-xl border border-slate-200/60 bg-white/70 p-3.5 text-left transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-slate-300/80 hover:shadow-[0_12px_28px_-22px_rgba(15,23,42,0.35)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30 active:translate-y-0 disabled:cursor-default dark:border-slate-800 dark:bg-slate-900/40 ${wide ? "sm:col-span-2" : ""}`}>
    <span className="flex items-center gap-2.5">
      {Icon && <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${t.icon}`}><Icon className="h-[18px] w-[18px]" /></span>}
      <span className="min-w-0 flex-1 text-[12.5px] font-semibold leading-tight text-slate-700 dark:text-slate-200">{label}</span>
    </span>
    <span className="mt-2.5 flex items-end justify-between gap-3">
      <span className="min-w-0">
        <span className={`block truncate font-head font-bold leading-none tracking-tight text-slate-900 tabular-nums dark:text-slate-50 ${wide ? "text-[28px]" : "text-[22px]"}`} data-testid={testid && `${testid}-count`}>
          {count == null ? "-" : <CountUp value={count} format={format} />}</span>
        <span className="mt-1.5 block truncate text-[11.5px] text-slate-500" data-testid={testid && `${testid}-sub`}>{sub}</span>
      </span>
      {bars}
    </span>
  </button>;
}
