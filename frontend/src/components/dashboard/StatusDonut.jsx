import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import { statusColor, statusLabel } from "@/lib/dashboard";
import { CircleDot } from "lucide-react";
import { CountUp } from "./KpiCard";
import { EmptyNote, Panel } from "./Panel";

export function StatusDonut({ composition, onPick, delay }) {
  const items = composition?.items || [];
  const total = composition?.total || 0;
  return (
    <Panel title="Komposisi Status Dokumen" icon={CircleDot} testid="dash-composition" delay={delay}>
      {!total ? <EmptyNote>Belum ada PO pada filter ini.</EmptyNote> :
        <div className="flex flex-1 flex-col items-center gap-5 sm:flex-row">
          <div className="relative h-[170px] w-[170px] shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={items} dataKey="count" nameKey="status" innerRadius={55} outerRadius={80} paddingAngle={1.5} stroke="none" animationDuration={900}>
                  {items.map((x) => <Cell key={x.status} fill={statusColor(x.status)} className="cursor-pointer outline-none" onClick={() => onPick?.(x.status)} />)}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="font-head text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-50" data-testid="dash-composition-total"><CountUp value={total} /></span>
              <span className="text-[11px] text-slate-500">Total PO</span>
            </div>
          </div>
          <ul className="w-full min-w-0 space-y-1.5">
            {items.map((x) => (
              <li key={x.status}>
                <button type="button" onClick={() => onPick?.(x.status)} data-testid={`dash-composition-${x.status.toLowerCase().replace(/\s+/g, "-")}`}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-[13px] transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 dark:hover:bg-slate-800/50">
                  <i className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: statusColor(x.status) }} />
                  <span className="min-w-0 flex-1 leading-tight text-slate-600 dark:text-slate-300">{statusLabel(x.status)}</span>
                  <b className="tabular-nums text-slate-800 dark:text-slate-100">{x.count}</b>
                  <span className="w-10 text-right text-xs tabular-nums text-slate-400">{Math.round((x.count / total) * 100)}%</span>
                </button>
              </li>
            ))}
          </ul>
        </div>}
    </Panel>
  );
}
