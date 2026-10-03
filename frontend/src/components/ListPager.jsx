import { Button } from "@/components/ui/button";
import { PAGE_SIZES } from "@/lib/serverList";
import { ChevronLeft, ChevronRight } from "lucide-react";

// Header kolom yang bisa diurutkan (server-side): klik -> naik, klik lagi -> turun.
export function SortTh({ label, k, sort, onSort, className = "", testid }) {
  const active = sort?.key === k;
  return <th className={`p-3 ${className}`}>
    <button type="button" onClick={() => onSort(k)} className={`inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground ${active ? "text-foreground" : ""}`} data-testid={`${testid}-sort-${k}`}>
      {label}<span className="w-3 text-[10px]">{active ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
    </button>
  </th>;
}

export function ListPager({ total, page, pageSize, setPage, setPageSize, testid, unit = "data" }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  const to = Math.min(total, page * pageSize);
  return <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground" data-testid={`${testid}-pagination`}>
    <span data-testid={`${testid}-total`}>{from}–{to} dari {total} {unit}</span>
    <div className="flex items-center gap-2">
      <label className="mr-2 flex items-center gap-1.5 text-xs">Per halaman<select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))} className="h-8 rounded-md border bg-background px-1.5 text-sm text-foreground" data-testid={`${testid}-page-size`}>{PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
      <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid={`${testid}-prev-page`}><ChevronLeft className="h-4 w-4" /></Button>
      <span className="tabular-nums text-foreground">Hal {Math.min(page, pages)} / {pages}</span>
      <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)} data-testid={`${testid}-next-page`}><ChevronRight className="h-4 w-4" /></Button>
    </div>
  </div>;
}
