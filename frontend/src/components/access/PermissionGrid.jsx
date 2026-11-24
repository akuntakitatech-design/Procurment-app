import { Fragment, useMemo } from "react";
import { Checkbox } from "@/components/ui/checkbox";

const COLS = ["view", "create", "edit", "delete", "post", "cancel", "print"];
const EXTRA = ["approve", "reject", "send_email", "direct"];

// Generic module x action grid. renderCell(key, module, action) draws each cell (checkbox or tri-state).
export function PermissionGrid({ catalog, search, renderCell, testid }) {
  const groups = useMemo(() => (catalog?.groups || []).map((g) => ({
    ...g, modules: g.modules.filter((m) => !search || m.label.toLowerCase().includes(search.toLowerCase())),
  })).filter((g) => g.modules.length), [catalog, search]);
  const A = catalog?.actions || {};
  return <div className="space-y-5" data-testid={testid}>
    {groups.map((g) => {
      const cols = COLS.filter((c) => g.modules.some((m) => m.actions.includes(c)));
      const hasExtra = g.modules.some((m) => m.actions.some((a) => EXTRA.includes(a)));
      return <div key={g.key} className="overflow-x-auto rounded-xl border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted/60"><tr className="text-xs text-muted-foreground">
            <th className="sticky left-0 z-10 min-w-[190px] bg-muted p-2.5 text-left font-semibold uppercase tracking-wide">{g.label}</th>
            {cols.map((c) => <th key={c} className="w-20 p-2.5 text-center font-medium">{A[c]}</th>)}
            {hasExtra && <th className="p-2.5 text-left font-medium">Lainnya</th>}
          </tr></thead>
          <tbody>{g.modules.map((m) => <tr key={m.key} className="border-t hover:bg-accent/30" data-testid={`perm-row-${m.key}`}>
            <td className="sticky left-0 z-10 bg-card p-2.5 font-medium">{m.label}</td>
            {cols.map((c) => <td key={c} className="p-2 text-center">{m.actions.includes(c) ? renderCell(`${m.key}.${c}`, m, c) : <span className="text-muted-foreground/40">—</span>}</td>)}
            {hasExtra && <td className="p-2"><div className="flex flex-wrap gap-3">{m.actions.filter((a) => EXTRA.includes(a)).map((a) => <span key={a} className="flex items-center gap-1.5 text-xs">{renderCell(`${m.key}.${a}`, m, a)}{A[a]}</span>)}</div></td>}
          </tr>)}</tbody>
        </table>
      </div>;
    })}
  </div>;
}

export function SpecialList({ catalog, renderCell }) {
  return <div className="rounded-xl border bg-card p-4">
    <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Izin Khusus</div>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {(catalog?.specials || []).map((s) => <Fragment key={s.key}><span className="flex items-center gap-2 text-sm">{renderCell(s.key, null, null)}{s.label}</span></Fragment>)}
    </div>
  </div>;
}

// Pusat Laporan: satu centang per laporan (`report.<key>`). Yang tidak dicentang tidak muncul di daftar
// laporan maupun bisa dibuka. `onBulk` (opsional) = pilih semua / kosongkan per kategori.
export function ReportList({ catalog, renderCell, search, onBulk }) {
  const groups = catalog?.report_groups || [];
  const reports = (catalog?.reports || []).filter((r) => !search || r.label.toLowerCase().includes(search.toLowerCase()));
  if (!reports.length) return null;
  return <div className="rounded-xl border bg-card p-4" data-testid="report-perm-list">
    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pusat Laporan (per laporan)</div>
    <p className="mb-3 mt-1 text-xs text-muted-foreground">Laporan yang tidak dicentang tidak muncul di daftar Pusat Laporan. Halaman Pusat Laporan tetap butuh izin <b>Lihat Pusat Laporan</b>.</p>
    <div className="space-y-4">{groups.map((g) => {
      const items = reports.filter((r) => r.group === g.key);
      if (!items.length) return null;
      const keys = items.map((r) => r.key);
      return <div key={g.key}>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{g.label}</span>
          <span className="text-xs text-muted-foreground">({items.length} laporan)</span>
          {onBulk && <span className="ml-auto flex gap-2">
            <button type="button" className="text-xs font-semibold text-primary hover:underline" onClick={() => onBulk(keys, true)} data-testid={`report-bulk-${g.key}-all`}>Pilih semua</button>
            <button type="button" className="text-xs font-semibold text-muted-foreground hover:underline" onClick={() => onBulk(keys, false)} data-testid={`report-bulk-${g.key}-none`}>Kosongkan</button>
          </span>}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((r) => <label key={r.key} className="flex items-start gap-2 text-sm" data-testid={`report-perm-${r.key}`}>
            <span className="mt-0.5">{renderCell(r.key, null, null)}</span>
            <span>{r.label}{r.requires_price && <span className="ml-1 text-xs text-amber-700">(juga butuh Lihat Harga Beli)</span>}</span>
          </label>)}
        </div>
      </div>;
    })}</div>
  </div>;
}

export function CheckCell({ checked, onChange, disabled, testid }) {
  return <Checkbox checked={checked} onCheckedChange={(v) => onChange(!!v)} disabled={disabled} data-testid={testid} />;
}
