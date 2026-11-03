import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { periodRange } from "@/lib/dashboard";

// Preset periode memakai fungsi yang sama dengan Dashboard (batas bulan/tahun, WIB-agnostic tanggal bisnis).
const PRESETS = [
  ["this_month", "Bulan ini"],
  ["last_month", "Bulan lalu"],
  ["last_3", "3 bulan terakhir"],
  ["this_year", "Tahun ini"],
  ["all", "Semua periode"],
];

/** Filter periode daftar transaksi: Dari–Sampai + preset cepat. `value` = {from, to} (YYYY-MM-DD). */
export function DateRangeFilter({ value = { from: "", to: "" }, onChange, testid = "date-range" }) {
  const set = (patch) => onChange({ from: value.from || "", to: value.to || "", ...patch });
  const applyPreset = (key) => {
    if (!key) return;
    const r = periodRange(key);
    onChange({ from: r.date_from || "", to: r.date_to || "" });
  };
  const active = !!(value.from || value.to);
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testid}>
      <Input type="date" value={value.from || ""} onChange={(e) => set({ from: e.target.value })}
        aria-label="Dari tanggal" data-testid={`${testid}-from`} className="h-9 w-[150px]" />
      <span className="text-sm text-muted-foreground">s/d</span>
      <Input type="date" value={value.to || ""} onChange={(e) => set({ to: e.target.value })}
        aria-label="Sampai tanggal" data-testid={`${testid}-to`} className="h-9 w-[150px]" />
      <select value="" onChange={(e) => applyPreset(e.target.value)} aria-label="Pilih periode cepat"
        data-testid={`${testid}-preset`} className="h-9 rounded-md border bg-background px-2 text-sm">
        <option value="">Periode…</option>
        {PRESETS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
      </select>
      {active && <Button variant="ghost" size="sm" onClick={() => onChange({ from: "", to: "" })}
        data-testid={`${testid}-reset`}>Reset</Button>}
    </div>
  );
}

export default DateRangeFilter;
