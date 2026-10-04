import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useServerList } from "@/lib/serverList";
import { nextSort } from "@/lib/txnList";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ListPager } from "@/components/ListPager";
import { MasterDeleteDialog } from "@/components/MasterDeleteDialog";
import { Combobox } from "@/components/Combobox";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, Package, PackageX, Pencil, Plus, RotateCcw, Search, Trash2, TrendingUp, TriangleAlert } from "lucide-react";

// Status mengikuti business rule Stok Min/Max existing (dihitung backend); frontend hanya menampilkan.
const STATUS = {
  "Out of Stock": { label: "Stok Habis", text: "text-rose-700 dark:text-rose-300", badge: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900" },
  "Low Stock": { label: "Stok Menipis", text: "text-amber-700 dark:text-amber-300", badge: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900" },
  Normal: { label: "Normal", text: "text-emerald-700 dark:text-emerald-300", badge: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900" },
  Overstock: { label: "Overstock", text: "text-violet-700 dark:text-violet-300", badge: "bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-900" },
  "No Stock": { label: "Belum ada stok", text: "text-muted-foreground", badge: "bg-muted text-muted-foreground border-border" },
};
const ACTIVE_FILTER = [{ value: "", label: "Semua Status Barang" }, { value: "Aktif", label: "Aktif" }, { value: "Nonaktif", label: "Nonaktif" }];
const STRIP = ["status_label", "category_label", "division_label", "base_uom_label", "unit_label", "stock", "total_stock", "stock_records", "stock_status"];
const CHECK_W = 44, CODE_W = 132;

function StockBadge({ status, testid }) {
  const s = STATUS[status] || STATUS["No Stock"];
  return <span data-testid={testid} className={cn("inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold", s.badge)}>{s.label}</span>;
}

function SummaryCard({ title, value, subtitle, icon: Icon, tone, active, onClick, testid }) {
  return <button type="button" onClick={onClick} data-testid={testid} aria-pressed={active}
    className={cn("rounded-2xl border bg-card p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md", active ? "border-primary ring-2 ring-primary/15" : "hover:border-primary/30")}>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
        <div className="mt-2 text-3xl font-bold tabular-nums" data-testid={`${testid}-value`}>{num(value)}</div>
        <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
      </div>
      <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", tone)}><Icon className="h-5 w-5" /></div>
    </div>
  </button>;
}

function Th({ label, k, sort, onSort, className = "", style }) {
  const active = sort?.key === k;
  return <th className={cn("p-3 whitespace-nowrap", className)} style={style}>
    {k ? <button type="button" onClick={() => onSort(k)} data-testid={`master-items-sort-${k}`}
      className={cn("inline-flex items-center gap-1 uppercase tracking-wider transition-colors hover:text-foreground", active && "text-foreground")}>
      {label}<span className="w-3 text-[10px]">{active ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
    </button> : label}
  </th>;
}

// Master Barang: barang + posisi stok per gudang. Pagination, search, filter, sort & ringkasan dari backend.
export function ItemStockTab({ FormDialog, newForm, refNames }) {
  const { can } = useAuth();
  const [categoryId, setCategoryId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [divisionId, setDivisionId] = useState("");
  const [active, setActive] = useState("");
  const [stockStatus, setStockStatus] = useState("");
  const list = useServerList("/master-items/stock-list", { category_id: categoryId, warehouse_id: warehouseId, division_id: divisionId, active, stock_status: stockStatus });
  const rows = list.rows;
  const data = list.data || {};
  const warehouses = data.warehouses || [];
  const summary = data.summary || { total: 0, out_of_stock: 0, low_stock: 0, overstock: 0 };
  const filters = data.filters || {};
  const [refs, setRefs] = useState({});
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({});
  const [sel, setSel] = useState(new Set());
  const [delRows, setDelRows] = useState(null);
  const selectable = can("edit", "items") || can("delete", "items");
  const off = selectable ? CHECK_W : 0;

  useEffect(() => { setSel(new Set()); }, [list.q, categoryId, warehouseId, divisionId, active, stockStatus, list.page, list.pageSize, list.sort]);
  const loadRef = useCallback((rn) => api.get(`/lookup/${rn}`).then((r) => setRefs((s) => ({ ...s, [rn]: r.data }))).catch(() => {}), []);
  useEffect(() => { refNames.forEach(loadRef); }, [refNames, loadRef]);

  const opt = (arr, all) => [{ value: "", label: all }, ...(arr || []).map((x) => ({ value: x.id, label: x.name || x.code || "-" }))];
  const catOptions = useMemo(() => opt(filters.categories, "Semua Kategori"), [filters.categories]);
  const whOptions = useMemo(() => opt(filters.warehouses, "Semua Gudang"), [filters.warehouses]);
  const divOptions = useMemo(() => opt(filters.divisions, "Semua Divisi"), [filters.divisions]);
  const anyFilter = list.q || categoryId || warehouseId || divisionId || active || stockStatus;
  const reset = () => { list.setQ(""); setCategoryId(""); setWarehouseId(""); setDivisionId(""); setActive(""); setStockStatus(""); list.setSort(null); };
  const toggleStatus = (s) => setStockStatus((cur) => (cur === s ? "" : s));

  const openAdd = async () => { setForm(await newForm("items")); setOpen(true); };
  const openEdit = (row) => {
    const copy = { ...row };
    STRIP.forEach((k) => delete copy[k]);
    copy.uoms = (row.uoms || []).filter((x) => !x.is_base && x.uom_id !== row.base_uom_id);
    setForm(copy); setOpen(true);
  };
  const labelOf = (r) => [r.code, r.name].filter(Boolean).join(" — ") || "-";
  const selRows = rows.filter((r) => sel.has(r.id));
  const allOn = rows.length > 0 && rows.every((r) => sel.has(r.id));
  const toggle = (id) => setSel((cur) => { const n = new Set(cur); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const askDelete = (arr) => setDelRows(arr.map((r) => ({ id: r.id, label: labelOf(r) })));
  const onSort = (k) => list.setSort(nextSort(list.sort, k));
  const colSpan = 8 + warehouses.length + (selectable ? 1 : 0);
  const stickyHead = "md:sticky z-20 bg-muted";
  // Sel sticky wajib opaque: warna seleksi/hover dilapis di atas warna kartu.
  const stickyCell = (sel_) => cn("md:sticky z-10", sel_ ? "[background:linear-gradient(hsl(var(--primary)/0.06),hsl(var(--primary)/0.06)),hsl(var(--card))]"
    : "bg-card group-hover:[background:linear-gradient(hsl(var(--accent)/0.4),hsl(var(--accent)/0.4)),hsl(var(--card))]");

  return <div className="space-y-4" data-testid="master-items-stock">
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <SummaryCard testid="master-items-summary-total" title="Jumlah Item" value={summary.total} subtitle="Barang sesuai filter aktif" icon={Package} tone="bg-primary/10 text-primary" active={!stockStatus} onClick={() => setStockStatus("")} />
      <SummaryCard testid="master-items-summary-out" title="Stok Habis" value={summary.out_of_stock} subtitle="Total stok = 0" icon={PackageX} tone="bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-300" active={stockStatus === "Out of Stock"} onClick={() => toggleStatus("Out of Stock")} />
      <SummaryCard testid="master-items-summary-low" title="Stok Menipis" value={summary.low_stock} subtitle="Sudah mencapai batas minimum" icon={TriangleAlert} tone="bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-300" active={stockStatus === "Low Stock"} onClick={() => toggleStatus("Low Stock")} />
      <SummaryCard testid="master-items-summary-over" title="Overstock" value={summary.overstock} subtitle="Melebihi batas maksimum" icon={TrendingUp} tone="bg-violet-50 text-violet-600 dark:bg-violet-950/40 dark:text-violet-300" active={stockStatus === "Overstock"} onClick={() => toggleStatus("Overstock")} />
    </div>

    <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
      <div className="flex flex-1 flex-col gap-2 md:flex-row md:flex-wrap md:items-center">
        <div className="relative min-w-[220px] flex-1 md:max-w-sm"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={list.q} onChange={(e) => list.setQ(e.target.value)} placeholder="Cari kode / nama barang..." className="pl-9" data-testid="master-items-search" /></div>
        <div className="md:w-48"><Combobox options={catOptions} value={categoryId} onChange={setCategoryId} placeholder="Semua Kategori" testid="master-items-category-filter" /></div>
        <div className="md:w-48"><Combobox options={whOptions} value={warehouseId} onChange={setWarehouseId} placeholder="Semua Gudang" testid="master-items-warehouse-filter" /></div>
        <div className="md:w-44"><Combobox options={divOptions} value={divisionId} onChange={setDivisionId} placeholder="Semua Divisi" testid="master-items-division-filter" /></div>
        <div className="md:w-52"><Combobox options={ACTIVE_FILTER} value={active} onChange={setActive} placeholder="Semua Status Barang" testid="master-items-status-filter" /></div>
        <Button variant="outline" onClick={reset} disabled={!anyFilter && !list.sort} data-testid="master-items-reset"><RotateCcw className="mr-2 h-4 w-4" />Reset</Button>
      </div>
      {can("create", "items") && <Button onClick={openAdd} data-testid="master-items-add"><Plus className="mr-2 h-4 w-4" />Tambah Barang</Button>}
    </div>

    {selRows.length > 0 && <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm" data-testid="master-items-selection-bar">
      <span className="font-semibold" data-testid="master-items-selected-count">{selRows.length} dipilih</span>
      {selRows.length === 1 && can("edit", "items") && <Button size="sm" variant="outline" onClick={() => openEdit(selRows[0])} data-testid="master-items-bar-edit"><Pencil className="mr-1.5 h-3.5 w-3.5" />Edit</Button>}
      {can("delete", "items") && <Button size="sm" variant="outline" onClick={() => askDelete(selRows)} data-testid="master-items-bar-delete"><Trash2 className="mr-1.5 h-3.5 w-3.5 text-destructive" />{selRows.length === 1 ? "Hapus" : "Hapus Massal"}</Button>}
      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setSel(new Set())} data-testid="master-items-clear-selection">Batal pilih</Button>
    </div>}

    <div className="relative">
      {list.loading && rows.length > 0 && <div className="absolute right-3 top-2.5 z-30 flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-xs text-muted-foreground shadow-sm" data-testid="master-items-loading"><Loader2 className="h-3.5 w-3.5 animate-spin" />Memuat</div>}
      <div className="overflow-x-auto rounded-xl border bg-card shadow-sm" data-testid="master-items-table-wrap">
        <table className="w-full min-w-[980px] border-separate border-spacing-0 text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            {selectable && <th className={cn("w-11 p-3", stickyHead)} style={{ left: 0, minWidth: CHECK_W }}><Checkbox checked={allOn} onCheckedChange={() => setSel(allOn ? new Set() : new Set(rows.map((r) => r.id)))} aria-label="Pilih semua di halaman ini" data-testid="master-items-select-all" /></th>}
            <Th label="Kode" k="code" sort={list.sort} onSort={onSort} className={stickyHead} style={{ left: off, minWidth: CODE_W }} />
            <Th label="Barang" k="name" sort={list.sort} onSort={onSort} className={cn(stickyHead, "min-w-[230px] md:shadow-[inset_-1px_0_0_hsl(var(--border))]")} style={{ left: off + CODE_W }} />
            <Th label="Kategori" k="category_label" sort={list.sort} onSort={onSort} className="bg-muted min-w-[140px]" />
            <Th label="Satuan" k="unit_label" sort={list.sort} onSort={onSort} className="bg-muted" />
            <Th label="Divisi" k="division_label" sort={list.sort} onSort={onSort} className="bg-muted min-w-[130px]" />
            {warehouses.map((w) => <th key={w.id} className="min-w-[118px] whitespace-nowrap bg-muted p-3 text-right" title={w.code ? `${w.code} — ${w.name}` : w.name} data-testid={`master-items-wh-col-${w.code || w.id}`}>{w.name}</th>)}
            <Th label="Total Stok" k="total_stock" sort={list.sort} onSort={onSort} className="bg-muted text-right min-w-[110px]" />
            <Th label="Status" k="stock_status" sort={list.sort} onSort={onSort} className="bg-muted min-w-[130px]" />
            <th className="w-24 bg-muted p-3 text-right">Aksi</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={colSpan} className="p-10 text-center text-muted-foreground" data-testid="master-items-empty">
              {list.loading ? <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />Memuat data barang...</span> : list.error ? "Gagal memuat data barang. Coba muat ulang halaman." : anyFilter ? "Tidak ada barang yang cocok dengan filter" : "Belum ada data barang"}
            </td></tr>}
            {rows.map((r) => {
              const on = sel.has(r.id);
              const rowKey = r.code || r.id;
              return <tr key={r.id} className={cn("group transition-colors [&>td]:border-t", on ? "bg-primary/5" : "hover:bg-accent/40")} data-testid={`master-items-row-${rowKey}`}>
                {selectable && <td className={cn("p-3", stickyCell(on))} style={{ left: 0 }}><Checkbox checked={on} onCheckedChange={() => toggle(r.id)} aria-label={`Pilih ${labelOf(r)}`} data-testid={`master-items-select-${rowKey}`} /></td>}
                <td className={cn("p-3 font-mono text-xs font-semibold whitespace-nowrap", stickyCell(on))} style={{ left: off }}>{r.code || "-"}</td>
                <td className={cn("p-3 md:shadow-[inset_-1px_0_0_hsl(var(--border))]", stickyCell(on))} style={{ left: off + CODE_W }}>
                  <div className="font-medium leading-snug">{r.name || "-"}</div>
                  {(r.part_number || !r.is_active) && <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    {r.part_number && <span className="font-mono">{r.part_number}</span>}
                    {!r.is_active && <span className="rounded-full border px-1.5 py-px text-[10px] font-semibold" data-testid={`master-items-inactive-${rowKey}`}>Nonaktif</span>}
                  </div>}
                </td>
                <td className="p-3">{r.category_label || "-"}</td>
                <td className="p-3 whitespace-nowrap">{r.unit_label || "-"}</td>
                <td className="p-3" data-testid={`master-items-division-${rowKey}`}>{r.division_label || "-"}</td>
                {warehouses.map((w) => {
                  const c = r.stock?.[w.id];
                  const s = STATUS[c ? c.status : "No Stock"];
                  return <td key={w.id} className="p-3 text-right align-top" data-testid={`master-items-cell-${rowKey}-${w.code || w.id}`}>
                    <div className={cn("font-semibold tabular-nums", !c && "text-muted-foreground font-normal")}>{c ? num(c.qty) : "–"}</div>
                    <div className={cn("mt-0.5 text-[10px] font-medium leading-tight", s.text)}>{s.label}</div>
                  </td>;
                })}
                <td className="p-3 text-right font-bold tabular-nums" data-testid={`master-items-total-${rowKey}`}>{r.stock_records ? num(r.total_stock) : <span className="font-normal text-muted-foreground">–</span>}</td>
                <td className="p-3"><StockBadge status={r.stock_status} testid={`master-items-status-${rowKey}`} /></td>
                <td className="p-3"><div className="flex justify-end gap-1">
                  {can("edit", "items") && <Button variant="ghost" size="icon" className="h-8 w-8" title="Edit" aria-label={`Edit ${labelOf(r)}`} onClick={() => openEdit(r)} data-testid={`master-items-edit-${rowKey}`}><Pencil className="h-4 w-4" /></Button>}
                  {can("delete", "items") && <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive hover:text-destructive" title="Hapus" aria-label={`Hapus ${labelOf(r)}`} onClick={() => askDelete([r])} data-testid={`master-items-delete-${rowKey}`}><Trash2 className="h-4 w-4" /></Button>}
                </div></td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
    </div>
    <div className="flex flex-col gap-1">
      <ListPager total={list.total} page={list.page} pageSize={list.pageSize} setPage={list.setPage} setPageSize={list.setPageSize} testid="master-items" unit="barang" />
      <p className="text-xs text-muted-foreground">Stok ditampilkan dalam satuan dasar per gudang. Status mengikuti konfigurasi Stok Min/Max; "Belum ada stok" berarti barang belum memiliki catatan stok di gudang tersebut.</p>
    </div>

    <MasterDeleteDialog open={!!delRows} rows={delRows || []} checkName="items" entityLabel="Barang" onDeselect={(ids) => setSel((c) => new Set([...c].filter((x) => !ids.includes(x))))} onClose={() => setDelRows(null)} onDone={() => { setDelRows(null); setSel(new Set()); list.reload(); }} />
    <FormDialog name="items" open={open} onOpenChange={setOpen} form={form} setForm={setForm} refs={refs} onSaved={() => { setOpen(false); setForm({}); list.reload(); }} />
  </div>;
}
