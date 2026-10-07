import { useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { compactRupiah, monthLabel } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import { BarChart3 } from "lucide-react";
import { Panel } from "./Panel";

const PO_C = "#3D5A80", INV_C = "#5E9C82";

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  return (
    <div className="rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-[0_12px_30px_-18px_rgba(15,23,42,0.4)] backdrop-blur">
      <div className="mb-1 font-semibold text-slate-700">{monthLabel(label)}</div>
      <div className="flex items-center justify-between gap-6"><span className="flex items-center gap-1.5 text-slate-500"><i className="h-2 w-2 rounded-full" style={{ background: PO_C }} />Nilai PO</span><b className="tabular-nums text-slate-800">{r.po_value == null ? "***" : rupiah(r.po_value)}</b></div>
      {r.invoice_value !== null && <div className="flex items-center justify-between gap-6"><span className="flex items-center gap-1.5 text-slate-500"><i className="h-2 w-2 rounded-full" style={{ background: INV_C }} />Nilai Invoice</span><b className="tabular-nums text-slate-800">{rupiah(r.invoice_value)}</b></div>}
    </div>
  );
}

export function TrendChart({ trend, delay }) {
  const [n, setN] = useState("12");
  const data = useMemo(() => (trend?.series || []).slice(-Number(n)), [trend, n]);
  const hasInv = data.some((d) => d.invoice_value !== null);
  const hasPo = data.some((d) => d.po_value !== null);
  return (
    <Panel title="Tren Pembelian & Invoice" icon={BarChart3} testid="dash-trend" delay={delay}
      action={<ToggleGroup type="single" value={n} onValueChange={(v) => v && setN(v)} className="rounded-lg border border-slate-200 p-0.5">
        <ToggleGroupItem value="6" className="h-7 rounded-md px-2.5 text-xs data-[state=on]:bg-slate-100 data-[state=on]:text-slate-900" data-testid="dash-trend-6">6 Bulan</ToggleGroupItem>
        <ToggleGroupItem value="12" className="h-7 rounded-md px-2.5 text-xs data-[state=on]:bg-slate-100 data-[state=on]:text-slate-900" data-testid="dash-trend-12">12 Bulan</ToggleGroupItem>
      </ToggleGroup>}>
      {!hasPo && !hasInv ? <div className="py-16 text-center text-sm text-slate-400">Nilai tidak ditampilkan sesuai hak akses Anda.</div> :
        <div className="h-[240px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#EEF1F5" vertical={false} />
              <XAxis dataKey="month" tickFormatter={monthLabel} tick={{ fontSize: 11, fill: "#8A94A3" }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v) => compactRupiah(v).replace("Rp ", "")} tick={{ fontSize: 11, fill: "#8A94A3" }} axisLine={false} tickLine={false} width={56} />
              <Tooltip content={<Tip />} cursor={{ stroke: "#CBD3DE", strokeDasharray: "3 3" }} />
              {hasPo && <Area type="monotone" dataKey="po_value" name="Nilai PO" stroke={PO_C} strokeWidth={2} fill={PO_C} fillOpacity={0.07} dot={{ r: 2.5, strokeWidth: 0, fill: PO_C }} activeDot={{ r: 4.5 }} animationDuration={900} />}
              {hasInv && <Area type="monotone" dataKey="invoice_value" name="Nilai Invoice" stroke={INV_C} strokeWidth={2} fill={INV_C} fillOpacity={0.06} dot={{ r: 2.5, strokeWidth: 0, fill: INV_C }} activeDot={{ r: 4.5 }} animationDuration={1100} />}
            </AreaChart>
          </ResponsiveContainer>
        </div>}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: PO_C }} />Nilai PO (Grand Total)</span>
          {hasInv && <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: INV_C }} />Nilai Invoice</span>}
        </div>
        <span className="text-slate-400">PO valid: Disetujui, Diterima Sebagian, Ditutup</span>
      </div>
    </Panel>
  );
}
