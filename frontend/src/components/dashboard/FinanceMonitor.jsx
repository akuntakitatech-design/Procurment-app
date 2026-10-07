import { TONES } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import { AlarmClock, CircleAlert, FileClock, FileWarning, HandCoins, Wallet } from "lucide-react";
import { Panel } from "./Panel";

const ROWS = [
  ["invoice_unbilled", "Invoice belum diterima", FileClock, "blue", "DO"],
  ["invoice_unpaid", "Invoice belum dibayar", FileWarning, "navy", "invoice"],
  ["dp_unallocated", "DP belum dialokasikan", HandCoins, "slate", "PO"],
  ["due_soon", "Hutang jatuh tempo 0–7 hari", AlarmClock, "amber", "invoice"],
  ["overdue", "Hutang lewat jatuh tempo", CircleAlert, "red", "invoice"],
];

export function FinanceMonitor({ finance, onPick, periodLabel, delay }) {
  return (
    <Panel title="Monitoring Finance" icon={Wallet} testid="dash-finance-monitor" delay={delay}
      action={<span className="rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-500">{periodLabel}</span>}>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {ROWS.map(([k, label, Icon, tone, unit]) => {
          const v = finance?.[k];
          if (v === undefined) return null;
          const warn = (k === "overdue" || k === "due_soon") && v?.count > 0;
          return (
            <li key={k}>
              <button type="button" disabled={!v} onClick={() => onPick?.(k)} data-testid={`dash-fin-${k}`}
                className="flex w-full items-center gap-3 py-2.5 text-left transition-colors duration-150 hover:bg-slate-50/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:opacity-50 dark:hover:bg-slate-800/40">
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${TONES[tone].icon}`}><Icon className="h-4 w-4" /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-slate-600 dark:text-slate-300">{label}</span>
                  <span className="text-[11px] text-slate-400">{v ? `${v.count} ${unit}` : "Tanpa akses"}</span>
                </span>
                <span className={`shrink-0 text-right text-[13px] font-semibold tabular-nums ${warn ? TONES[tone].text : "text-slate-800 dark:text-slate-100"}`}>{v ? rupiah(v.value) : "***"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
