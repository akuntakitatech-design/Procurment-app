import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { nextSort, searchRows, sortRows } from "@/lib/txnList";
import { rupiah } from "@/lib/format";
import { fmtD } from "@/lib/invoice";
import { Search } from "lucide-react";

function cell(c, r) {
  if (c.render) return c.render(r);
  const v = r[c.key];
  if (c.status) return <StatusBadge status={v} />;
  if (c.money) return rupiah(v);
  if (c.date) return fmtD(v);
  return v === null || v === undefined || v === "" ? "-" : v;
}

export function DataTable({ columns, rows, testidPrefix, onOpen, filters, emptyText = "Belum ada data", searchPlaceholder, minWidth = 1100, countLabel = "data" }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState(null);
  const view = useMemo(() => sortRows(searchRows(rows || [], columns, q), columns, sort), [rows, columns, q, sort]);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder={searchPlaceholder || "Cari..."} value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" data-testid={`${testidPrefix}-search`} /></div>
        {filters}
        <span className="ml-auto text-xs text-muted-foreground" data-testid={`${testidPrefix}-count`}>{view.length} {countLabel}</span>
      </div>
      <div className="overflow-x-auto rounded-xl border bg-card shadow-sm">
        <table className="w-full text-sm zebra" style={{ minWidth }}>
          <thead className="bg-muted"><tr className="text-left text-xs font-semibold text-muted-foreground">
            {columns.map((c) => <th key={c.key} className={`p-3 ${c.num || c.money ? "text-right" : ""}`}>
              <button type="button" onClick={() => setSort((s) => nextSort(s, c.key))} className="inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground" data-testid={`${testidPrefix}-sort-${c.key}`}>
                {c.label}<span className="w-3 text-[10px]">{sort?.key === c.key ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span></button></th>)}
          </tr></thead>
          <tbody>
            {view.length === 0 && <tr><td colSpan={columns.length} className="p-8 text-center text-muted-foreground" data-testid={`${testidPrefix}-empty`}>{emptyText}</td></tr>}
            {view.map((r) => <tr key={r.id || r.do_id} onClick={() => onOpen?.(r)} data-testid={`${testidPrefix}-row-${r.invoice_no || r.do_no || r.id}`} className={`border-t transition-colors hover:bg-accent/40 ${onOpen ? "cursor-pointer" : ""}`}>
              {columns.map((c) => <td key={c.key} className={`p-3 ${c.mono ? "font-mono text-xs font-semibold" : ""} ${c.num || c.money ? "text-right tabular-nums" : ""} ${c.wrap ? "max-w-[200px] text-xs" : ""}`}>{cell(c, r)}</td>)}
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  );
}
