import { useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/StatusBadge";
import { TxnHoverPreview } from "@/components/TxnHoverPreview";
import { TxnSelectionBar } from "@/components/TxnSelectionBar";
import { TxnBulkDeleteDialog } from "@/components/TxnBulkDeleteDialog";
import { colValue, nextSort, searchRows, sortRows } from "@/lib/txnList";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";

const PAGE = 25;
const STOCK = new Set(["do", "mi", "transfer", "loan", "adjustment", "opname"]);

function SortHead({ col, sort, onSort }) {
  const active = sort?.key === col.key;
  return (
    <th className={`p-3 ${col.num ? "text-right" : ""}`}>
      <button type="button" onClick={() => onSort(col.key)} className={`inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground ${active ? "text-foreground" : ""}`} data-testid={`sort-${col.key}`}>
        {col.label}<span className="w-3 text-[10px]">{active ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
      </button>
    </th>
  );
}

function Cell({ col, row, onOpen }) {
  if (col.hover) return <TxnHoverPreview row={row} onOpen={onOpen} />;
  if (col.render) return col.render(row);
  if (col.status) return <StatusBadge status={row[col.key]} />;
  const v = colValue(col, row);
  return v === null || v === undefined || v === "" ? "-" : v;
}

export function TxnList({ module, columns, rows, onOpen, onPrint, onEdit, onEmail, emailEligible, canEditRow, onReload, filters, resetKey, testidPrefix, emptyText = "Belum ada data", minWidth = 900, selectedId, searchPlaceholder = "Cari nomor, MRO, RO, PO, SPK, project, divisi, barang..." }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState(null);
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState(new Set());
  const [bulk, setBulk] = useState(false);

  const filtered = useMemo(() => sortRows(searchRows(rows || [], columns, q), columns, sort), [rows, columns, q, sort]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const view = filtered.slice(page * PAGE, page * PAGE + PAGE);
  useEffect(() => { setSel(new Set()); setPage(0); }, [q, resetKey]);
  useEffect(() => { setSel(new Set()); }, [page, rows]);
  useEffect(() => { if (page >= pages) setPage(0); }, [page, pages]);

  const selectedRows = view.filter((r) => sel.has(r.id));
  const allOn = view.length > 0 && view.every((r) => sel.has(r.id));
  const toggle = (id) => setSel((cur) => { const n = new Set(cur); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleAll = () => setSel(allOn ? new Set() : new Set(view.map((r) => r.id)));

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-md"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input placeholder={searchPlaceholder} value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" data-testid={`${testidPrefix}-search`} /></div>
        {filters}
        <span className="ml-auto text-xs text-muted-foreground" data-testid={`${testidPrefix}-result-count`}>{filtered.length} transaksi</span>
      </div>
      <TxnSelectionBar module={module} selected={selectedRows} onClear={() => setSel(new Set())} onPrint={onPrint} onEdit={onEdit} onEmail={onEmail} emailEligible={emailEligible} canEditRow={canEditRow} onBulkDelete={() => setBulk(true)} testidPrefix={testidPrefix} />
      <div className="overflow-x-auto rounded-md border bg-card shadow-sm">
        <table className="w-full text-sm zebra" style={{ minWidth }}>
          <thead className="bg-muted"><tr className="text-left text-xs font-semibold text-muted-foreground">
            <th className="w-10 p-3"><Checkbox checked={allOn} onCheckedChange={toggleAll} aria-label="Pilih semua di halaman" data-testid={`${testidPrefix}-select-all`} /></th>
            {columns.map((c) => <SortHead key={c.key} col={c} sort={sort} onSort={(k) => setSort(nextSort(sort, k))} />)}
          </tr></thead>
          <tbody>
            {view.length === 0 && <tr><td colSpan={columns.length + 1} className="p-8 text-center text-muted-foreground">{emptyText}</td></tr>}
            {view.map((r) => (
              <tr key={r.id} onClick={() => onOpen?.(r)} data-testid={`${testidPrefix}-row-${r.no || r.id}`} className={`cursor-pointer border-t transition-colors hover:bg-accent/40 ${sel.has(r.id) || selectedId === r.id ? "bg-primary/5" : ""}`}>
                <td className="p-3" onClick={(e) => e.stopPropagation()}><Checkbox checked={sel.has(r.id)} onCheckedChange={() => toggle(r.id)} aria-label={`Pilih ${r.no}`} data-testid={`${testidPrefix}-select-${r.no || r.id}`} /></td>
                {columns.map((c) => <td key={c.key} className={`p-3 ${c.mono ? "font-mono text-xs font-semibold" : ""} ${c.num ? "text-right tabular-nums" : ""} ${c.wrap ? "max-w-[220px] text-xs" : ""}`}><Cell col={c} row={r} onOpen={onOpen} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && <div className="mt-3 flex items-center justify-end gap-2 text-sm" data-testid={`${testidPrefix}-pagination`}>
        <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)} data-testid={`${testidPrefix}-prev-page`}><ChevronLeft className="h-4 w-4" /></Button>
        <span className="tabular-nums">Hal {page + 1} / {pages}</span>
        <Button size="sm" variant="outline" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} data-testid={`${testidPrefix}-next-page`}><ChevronRight className="h-4 w-4" /></Button>
      </div>}
      <TxnBulkDeleteDialog open={bulk} module={module} rows={selectedRows} stockModule={STOCK.has(module)} onClose={() => setBulk(false)} onDone={() => { setBulk(false); setSel(new Set()); onReload?.(); }} />
    </div>
  );
}
