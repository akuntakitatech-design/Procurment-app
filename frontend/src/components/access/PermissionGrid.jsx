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

export function CheckCell({ checked, onChange, disabled, testid }) {
  return <Checkbox checked={checked} onCheckedChange={(v) => onChange(!!v)} disabled={disabled} data-testid={testid} />;
}
