import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { TONES } from "@/lib/dashboard";
import { useCountUp } from "./useCountUp";
import { Info } from "lucide-react";

export function CountUp({ value, format = (v) => Math.round(v).toLocaleString("id-ID") }) {
  const v = useCountUp(value);
  return <>{format(v)}</>;
}

/** Kartu KPI soft: warna hanya pada ikon & indikator kecil; kartu tetap putih. */
export function KpiCard({ label, count, sub, icon: Icon, tone = "navy", onClick, hint, alert = false, delay = 0, testid, format }) {
  const t = TONES[tone] || TONES.navy;
  const body = (
    <button type="button" onClick={onClick} disabled={!onClick} data-testid={testid}
      style={{ "--d": `${delay}ms` }}
      className="dash-rise group relative flex h-full min-w-0 flex-col rounded-2xl border border-slate-200/70 bg-card p-4 text-left shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-0.5 hover:border-slate-300/80 hover:shadow-[0_14px_32px_-24px_rgba(15,23,42,0.35)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 active:translate-y-0 disabled:cursor-default disabled:hover:translate-y-0 dark:border-slate-800">
      <div className="flex items-start gap-3">
        {Icon && <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${t.icon}`}><Icon className="h-[18px] w-[18px]" /></span>}
        <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-slate-600 dark:text-slate-300">{label}</span>
        {hint && <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-300" aria-hidden />}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-head text-[26px] font-semibold leading-none tracking-tight text-slate-900 tabular-nums dark:text-slate-50" data-testid={testid && `${testid}-count`}>
          {count == null ? "-" : <CountUp value={count} format={format} />}
        </span>
        {alert && <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#C46A6A] opacity-40" /><span className="relative inline-flex h-2 w-2 rounded-full bg-[#C46A6A]" /></span>}
      </div>
      <div className="mt-2 min-h-[18px] truncate text-xs text-slate-500" data-testid={testid && `${testid}-sub`}>{sub}</div>
    </button>
  );
  if (!hint) return body;
  return <TooltipProvider delayDuration={250}><Tooltip><TooltipTrigger asChild>{body}</TooltipTrigger><TooltipContent className="max-w-[240px] text-xs">{hint}</TooltipContent></Tooltip></TooltipProvider>;
}
