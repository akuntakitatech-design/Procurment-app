import { TONES } from "@/lib/dashboard";
import { CountUp } from "./KpiCard";

/** Cincin lembut (SVG) dengan ikon di tengah. pct 0–100 mengisi busur; null -> busur dekoratif tipis. */
export function Ring({ pct, tone = "navy", icon: Icon, size = 52, stroke = 4, testid }) {
  const t = TONES[tone] || TONES.navy;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const fill = pct == null ? 0.28 : Math.max(0.04, Math.min(1, Number(pct) / 100));
  return <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }} data-testid={testid}>
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-slate-100 dark:text-slate-800" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={t.bar} strokeOpacity={pct == null ? 0.45 : 0.9} strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - fill)} className="transition-[stroke-dashoffset] duration-700 ease-out" />
    </svg>
    {Icon && <span className={`absolute inset-[7px] flex items-center justify-center rounded-full ${t.icon}`}><Icon className="h-[17px] w-[17px]" /></span>}
  </span>;
}

/** KPI ringkas dengan cincin: nilai besar + label + keterangan. Klik = drill-down (bila ada). */
export function RingKpi({ label, value, format, sub, icon, tone, pct, onClick, testid, title, delay = 0 }) {
  const body = <>
    <Ring pct={pct} tone={tone} icon={icon} testid={testid && `${testid}-ring`} />
    <span className="min-w-0 flex-1">
      <span className="block truncate font-head text-[19px] font-semibold leading-tight tracking-tight text-slate-900 tabular-nums dark:text-slate-50" data-testid={testid && `${testid}-value`}>
        {value == null ? "–" : typeof value === "number" ? <CountUp value={value} format={format} /> : value}
      </span>
      <span className="mt-0.5 block text-[12.5px] font-medium leading-snug text-slate-600 dark:text-slate-300">{label}</span>
      {sub && <span className="mt-0.5 block truncate text-[11px] text-slate-400" data-testid={testid && `${testid}-sub`}>{sub}</span>}
    </span>
  </>;
  const cls = "dash-rise flex min-w-0 items-center gap-3 rounded-xl border border-slate-200/60 bg-white/70 p-3 text-left dark:border-slate-800 dark:bg-slate-900/40";
  if (!onClick) return <div className={cls} style={{ "--d": `${delay}ms` }} title={title} data-testid={testid}>{body}</div>;
  return <button type="button" onClick={onClick} style={{ "--d": `${delay}ms` }} title={title} data-testid={testid}
    className={`${cls} transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-slate-300/80 hover:shadow-[0_12px_28px_-22px_rgba(15,23,42,0.35)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D5A80]/30 active:translate-y-0`}>{body}</button>;
}

/** Label sub-bagian di dalam panel (mis. "Posisi s/d 30/06/2026" / "Transaksi periode ini"). */
export function SubLabel({ children, extra, testid }) {
  return <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2" data-testid={testid}>
    <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">{children}</span>{extra}
  </div>;
}
