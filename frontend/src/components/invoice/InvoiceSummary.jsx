import { useEffect, useState } from "react";
import api from "@/lib/api";
import { rupiah } from "@/lib/format";
import { FileClock, FileCheck2, CircleDollarSign, Hourglass, CheckCircle2, Wallet, CalendarClock, AlertTriangle } from "lucide-react";

const CARDS = [
  ["invoice_not_received", "Invoice Belum Diterima", FileClock, "DO belum/sebagian ditagihkan", "text-slate-600"],
  ["invoice_received", "Invoice Sudah Diterima", FileCheck2, "Total nilai invoice", "text-indigo-600"],
  ["unpaid", "Belum Dibayar", CircleDollarSign, "Sisa tagihan", "text-rose-600"],
  ["partial", "Dibayar Sebagian", Hourglass, "Sisa tagihan", "text-amber-600"],
  ["paid", "Lunas", CheckCircle2, "Nilai invoice lunas", "text-emerald-600"],
  ["total_payable", "Total Hutang Vendor", Wallet, "Seluruh sisa invoice", "text-primary", true],
  ["due_soon", "Invoice Jatuh Tempo", CalendarClock, "Jatuh tempo ≤ 7 hari", "text-amber-700"],
  ["overdue", "Invoice Lewat Jatuh Tempo", AlertTriangle, "Melewati tanggal jatuh tempo", "text-rose-700"],
];

export function InvoiceSummary({ compact = false, reloadKey }) {
  const [s, setS] = useState(null);
  useEffect(() => { api.get("/vendor-invoices/summary").then((r) => setS(r.data)).catch(() => setS(false)); }, [reloadKey]);
  if (s === false) return null;
  return (
    <div className={`grid gap-3 ${compact ? "grid-cols-2 lg:grid-cols-4" : "grid-cols-2 md:grid-cols-4"}`} data-testid="invoice-summary">
      {CARDS.map(([k, label, Icon, hint, tone, moneyOnly]) => (
        <div key={k} className="rounded-xl border bg-card p-4 shadow-sm transition-transform duration-200 hover:-translate-y-0.5" data-testid={`invoice-summary-${k}`}>
          <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Icon className={`h-4 w-4 ${tone}`} />{label}</div>
          <div className="mt-2 font-head text-xl font-bold tabular-nums" data-testid={`invoice-summary-${k}-value`}>
            {s ? (moneyOnly ? rupiah(s[k]) : s[k]) : "…"}
          </div>
          {!moneyOnly && <div className="mt-0.5 text-[11px] text-muted-foreground">{s ? `${hint}: ${rupiah(k === "invoice_received" ? s.invoice_received_value : s[`${k}_value`])}` : hint}</div>}
          {moneyOnly && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
        </div>
      ))}
    </div>
  );
}
