import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { useServerList } from "@/lib/serverList";
import { ListPager } from "@/components/ListPager";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { num, fmtDateTime } from "@/lib/format";
import { SortTh, sortToggle } from "@/components/SortTh";
import { nextSort } from "@/lib/txnList";
import { Search, Package, PackageX, TriangleAlert, TrendingUp, RotateCcw, CircleOff } from "lucide-react";

const ALL = "__all__";
const SORT_DEFAULT = "__default__";
const whSortKey = (id) => `wh:${id}`; // key sort kolom stok per gudang (didukung backend stock_summary)

/**
 * Tinggi area tabel = sisa ruang di <main> setelah header/filter/pager, supaya halaman tidak perlu
 * di-scroll dan header tabel (sticky) selalu terlihat. Diukur, bukan angka ajaib, agar tetap benar
 * saat banner langganan muncul atau jendela di-resize. < 640px (mode kartu) tidak dibatasi.
 */
function useTableFillHeight(rootRef, depKey) {
  const [maxHeight, setMaxHeight] = useState(null);
  const measure = useCallback(() => {
    const root = rootRef.current;
    const main = root?.closest("main");
    const wrap = root?.querySelector('[data-table-wrap="1"]');
    if (!main || !wrap) return;
    if (window.innerWidth < 640) { setMaxHeight(null); return; }
    const offset = wrap.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
    const below = 64; // ruang untuk pager di bawah tabel
    setMaxHeight(Math.max(240, Math.floor(main.clientHeight - offset - below)));
  }, [rootRef]);
  useEffect(() => {
    measure();
    const main = rootRef.current?.closest("main");
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (ro && main) ro.observe(main);
    window.addEventListener("resize", measure);
    return () => { if (ro) ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [measure, depKey, rootRef]);
  return maxHeight;
}

// Tampilan HP: header tabel disembunyikan (kelas m-stack), jadi urutan dipilih lewat dropdown.
function SortControl({ sort, onChange, options, testid }) {
  const key = sort?.key || SORT_DEFAULT;
  const dir = sort?.dir || "asc";
  return (
    <div className="flex items-center gap-2 sm:hidden" data-testid={testid}>
      <span className="shrink-0 text-xs text-muted-foreground">Urutkan</span>
      <Select value={key} onValueChange={(v) => onChange(v === SORT_DEFAULT ? null : { key: v, dir })}>
        <SelectTrigger className="h-9 min-w-0 flex-1" data-testid={`${testid}-field`}><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={SORT_DEFAULT}>Default (terbaru)</SelectItem>
          {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>
      <Button variant="outline" className="h-9 shrink-0 px-3 text-xs font-semibold" disabled={!sort?.key}
        onClick={() => onChange(sort?.key ? { key: sort.key, dir: dir === "asc" ? "desc" : "asc" } : null)}
        aria-label={dir === "asc" ? "Urutan naik (A→Z), tekan untuk turun" : "Urutan turun (Z→A), tekan untuk naik"}
        data-testid={`${testid}-dir`}>{dir === "asc" ? "A→Z" : "Z→A"}</Button>
    </div>
  );
}

function statusLabel(status) {
  if (status === "Out of Stock") return "Habis";
  if (status === "Low Stock") return "Menipis";
  if (status === "Overstock") return "Overstock";
  return "Normal";
}

function SummaryCard({ title, value, subtitle, icon: Icon, active, onClick, testid }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      aria-pressed={active}
      className={`min-w-0 rounded-2xl border bg-card p-3 sm:p-4 text-left shadow-sm transition-transform hover:-translate-y-0.5 hover:shadow-md ${active ? "border-primary ring-2 ring-primary/10" : "hover:border-primary/30"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] sm:text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
          <div className="mt-1 sm:mt-2 text-2xl sm:text-3xl font-bold tabular-nums" data-testid={testid ? `${testid}-value` : undefined}>{num(value)}</div>
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="hidden min-[400px]:flex h-9 w-9 sm:h-11 sm:w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </button>
  );
}

// Posisi Stok per BARANG dari ringkasan canonical backend (stock_summary = Master Barang = Dashboard).
// Frontend tidak menghitung status/summary; barang aktif tanpa catatan stok tetap tampil (Stok Habis, "Belum ada stok").
export default function Inventory() {
  const rootRef = useRef(null);
  const [ledger, setLedger] = useState([]);
  const [items, setItems] = useState([]);
  const [ledgerSort, setLedgerSort] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState(ALL);
  const [warehouseFilter, setWarehouseFilter] = useState(ALL);
  const [sp, setSp] = useSearchParams();
  const STATUS_OK = ["Out of Stock", "Low Stock", "Overstock", "Normal", "No Stock", "Without Stock"];
  const [statusFilter, setStatusFilter] = useState(STATUS_OK.includes(sp.get("stock_status")) ? sp.get("stock_status") : ALL);
  const divisionId = sp.get("division_id") || ""; // drill-down Dashboard (filter Divisi yang sama)
  const list = useServerList("/inventory/item-stock", {
    division_id: divisionId,
    category_id: categoryFilter === ALL ? "" : categoryFilter,
    warehouse_id: warehouseFilter === ALL ? "" : warehouseFilter,
    stock_status: statusFilter === ALL ? "" : statusFilter,
  });
  const data = list.data || {};
  const rows = list.rows;
  const visibleWarehouses = data.warehouses || [];
  const filters = data.filters || {};
  const summary = data.summary || { total: 0, out_of_stock: 0, low_stock: 0, overstock: 0 };
  const q = list.q;

  useEffect(() => {
    Promise.all([api.get("/inventory/ledger"), api.get("/lookup/items")])
      .then(([l, i]) => { setLedger(l.data || []); setItems(i.data || []); })
      .catch(() => {});
  }, []);

  const itemMap = useMemo(() => Object.fromEntries(items.map((x) => [x.id, x])), [items]);

  const filteredLedger = useMemo(() => ledger.filter((l) => {
    if (warehouseFilter !== ALL && l.warehouse_id !== warehouseFilter) return false;
    if (categoryFilter !== ALL && (itemMap[l.item_id] || {}).category_id !== categoryFilter) return false;
    if (!q) return true;
    return `${l.item_code || ""} ${l.item_name || ""} ${l.warehouse_name || ""} ${l.doc_no || ""}`.toLowerCase().includes(q.toLowerCase());
  }), [ledger, warehouseFilter, categoryFilter, q, itemMap]);

  // Kartu stok dimuat sekaligus di frontend -> urutan dihitung lokal (angka naik/turun, teks A→Z/Z→A,
  // nilai kosong selalu di akhir).
  const sortedLedger = useMemo(() => {
    if (!ledgerSort?.key) return filteredLedger;
    const { key, dir } = ledgerSort;
    const sign = dir === "desc" ? -1 : 1;
    const empty = (v) => v === null || v === undefined || v === "";
    return [...filteredLedger].sort((a, b) => {
      const av = a[key], bv = b[key];
      if (empty(av) && empty(bv)) return 0;
      if (empty(av)) return 1;
      if (empty(bv)) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * sign;
      return String(av).localeCompare(String(bv), "id", { numeric: true, sensitivity: "base" }) * sign;
    });
  }, [filteredLedger, ledgerSort]);

  const onPositionSort = sortToggle(list.setSort);
  const onLedgerSort = (k) => setLedgerSort((cur) => nextSort(cur, k));
  const positionSortOptions = useMemo(() => [
    { value: "code", label: "Kode" }, { value: "name", label: "Barang" }, { value: "category_label", label: "Kategori" },
    { value: "unit_label", label: "Satuan" },
    ...(data.warehouses || []).map((w) => ({ value: whSortKey(w.id), label: `Stok ${w.name}` })),
    { value: "total_stock", label: "Total Stok" }, { value: "stock_status", label: "Status" },
  ], [data.warehouses]);
  const tableMaxHeight = useTableFillHeight(rootRef, `${rows.length}:${visibleWarehouses.length}:${statusFilter}:${list.sort?.key || ""}`);

  const clearDivision = () => { const n = new URLSearchParams(sp); n.delete("division_id"); setSp(n, { replace: true }); };
  const resetFilters = () => {
    list.setQ("");
    list.setSort(null);
    setLedgerSort(null);
    if (divisionId) clearDivision();
    setCategoryFilter(ALL);
    setWarehouseFilter(ALL);
    setStatusFilter(ALL);
  };
  const toggle = (st) => setStatusFilter(statusFilter === st ? ALL : st);

  return (
    <div ref={rootRef}>
      <PageHeader title="Inventory / Stock" subtitle="Posisi stok & kartu stok per gudang" />
      <Tabs defaultValue="position">
        <TabsList><TabsTrigger value="position" data-testid="inv-tab-position">Posisi Stok</TabsTrigger><TabsTrigger value="ledger" data-testid="inv-tab-ledger">Kartu Stok (Ledger)</TabsTrigger></TabsList>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-5">
          <SummaryCard testid="inv-summary-total" title="Jumlah Item" value={summary.total} subtitle="Barang aktif pada filter" icon={Package} active={statusFilter === ALL} onClick={() => setStatusFilter(ALL)} />
          <SummaryCard testid="inv-summary-out" title="Stok Habis" value={summary.out_of_stock} subtitle={summary.no_stock ? `Total stok = 0 · ${num(summary.no_stock)} belum ada stok` : "Total stok = 0"} icon={PackageX} active={statusFilter === "Out of Stock"} onClick={() => toggle("Out of Stock")} />
          <SummaryCard testid="inv-summary-low" title="Stok Menipis" value={summary.low_stock} subtitle="Sudah mencapai batas minimum" icon={TriangleAlert} active={statusFilter === "Low Stock"} onClick={() => toggle("Low Stock")} />
          <SummaryCard testid="inv-summary-over" title="Overstock" value={summary.overstock} subtitle="Melebihi batas maksimum" icon={TrendingUp} active={statusFilter === "Overstock"} onClick={() => toggle("Overstock")} />
          <SummaryCard testid="inv-summary-without" title="Tanpa Stok" value={summary.without_stock || 0} subtitle="Jasa / sewa / perizinan" icon={CircleOff} active={statusFilter === "Without Stock"} onClick={() => toggle("Without Stock")} />
        </div>

        <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative min-w-0 flex-1 lg:max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => list.setQ(e.target.value)} placeholder="Cari kode / nama barang..." className="pl-9" data-testid="inventory-search" />
          </div>
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="w-full lg:w-[220px]" data-testid="inventory-category-filter"><SelectValue placeholder="Semua kategori" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Semua Kategori</SelectItem>
              {(filters.categories || []).map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={warehouseFilter} onValueChange={setWarehouseFilter}>
            <SelectTrigger className="w-full lg:w-[220px]" data-testid="inventory-warehouse-filter"><SelectValue placeholder="Semua gudang" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Semua Gudang</SelectItem>
              {(filters.warehouses || []).map((w) => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}
            </SelectContent>
          </Select>
          {divisionId && <span className="inline-flex items-center gap-2 rounded-full border bg-muted/50 px-3 py-1 text-xs" data-testid="inventory-division-chip">
            Divisi: {(filters.divisions || []).find((d) => d.id === divisionId)?.name || "-"}
            <button type="button" onClick={clearDivision} className="font-semibold text-muted-foreground hover:text-foreground" aria-label="Hapus filter divisi" data-testid="inventory-division-clear">×</button>
          </span>}
          <Button variant="outline" onClick={resetFilters} data-testid="inventory-reset"><RotateCcw className="mr-2 h-4 w-4" />Reset</Button>
        </div>

        <TabsContent value="position" className="mt-4">
          <SortControl sort={list.sort} onChange={list.setSort} options={positionSortOptions} testid="inventory-sort-mobile" />
          <div className="mt-3 sm:mt-0 border rounded-xl overflow-auto bg-card shadow-sm" data-table-wrap="1" style={{ maxHeight: tableMaxHeight || undefined }} data-testid="inventory-position-table-wrap">
            <table className="m-stack w-full text-sm zebra min-w-[820px]">
              <thead className="bg-muted">
                <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <SortTh sticky label="Kode" k="code" sort={list.sort} onSort={onPositionSort} testidPrefix="inventory-sort" />
                  <SortTh sticky label="Barang" k="name" sort={list.sort} onSort={onPositionSort} className="min-w-[220px]" testidPrefix="inventory-sort" />
                  <SortTh sticky label="Kategori" k="category_label" sort={list.sort} onSort={onPositionSort} className="min-w-[150px]" testidPrefix="inventory-sort" />
                  <SortTh sticky label="Satuan" k="unit_label" sort={list.sort} onSort={onPositionSort} className="w-20" testidPrefix="inventory-sort" />
                  {visibleWarehouses.map((w) => <SortTh key={w.id} sticky label={w.name} k={whSortKey(w.id)} sort={list.sort} onSort={onPositionSort} align="right" className="min-w-[120px]" testidPrefix="inventory-sort" />)}
                  {visibleWarehouses.length > 1 && <SortTh sticky label="Total Stok" k="total_stock" sort={list.sort} onSort={onPositionSort} align="right" className="min-w-[110px]" testidPrefix="inventory-sort" />}
                  <SortTh sticky label="Status" k="stock_status" sort={list.sort} onSort={onPositionSort} className="min-w-[120px]" testidPrefix="inventory-sort" />
                </tr>
              </thead>
              <tbody>
                {list.loading && rows.length === 0 && [0, 1, 2].map((i) => <tr key={i} className="border-t"><td colSpan={6 + visibleWarehouses.length} className="p-3"><Skeleton className="h-5 w-full" /></td></tr>)}
                {list.error && <tr><td colSpan={6 + visibleWarehouses.length} className="p-8 text-center text-muted-foreground" data-testid="inventory-error">Gagal memuat posisi stok. <Button variant="link" className="h-auto p-0" onClick={list.reload}>Coba lagi</Button></td></tr>}
                {!list.loading && !list.error && rows.length === 0 && <tr><td colSpan={6 + visibleWarehouses.length} className="p-8 text-center text-muted-foreground" data-testid="inventory-empty">Tidak ada data stok sesuai filter</td></tr>}
                {rows.map((g) => (
                  <tr key={g.id} className="border-t" data-testid={`inventory-row-${g.code}`}>
                    <td data-label="Kode" className="p-3 font-mono text-xs font-semibold">{g.code}</td>
                    <td data-label="Barang" className="p-3 font-medium m-full">{g.name}</td>
                    <td data-label="Kategori" className="p-3">{g.category_label || "Tanpa Kategori"}</td>
                    <td data-label="Satuan" className="p-3">{g.unit_label || "-"}</td>
                    {visibleWarehouses.map((w) => {
                      const c = g.stock?.[w.id];
                      return (
                        <td key={w.id} data-label={w.name} className="p-3 text-right">
                          <div className="font-semibold tabular-nums">{num(c?.qty || 0)}</div>
                          <div className="mt-0.5 text-[10px] text-muted-foreground">{c ? statusLabel(c.status) : "Belum ada stok"}</div>
                        </td>
                      );
                    })}
                    {visibleWarehouses.length > 1 && <td data-label="Total Stok" className="p-3 text-right font-bold tabular-nums">{num(g.total_stock)}</td>}
                    <td data-label="Status" className="p-3"><StatusBadge status={g.stock_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ListPager total={list.total} page={list.page} pageSize={list.pageSize} setPage={list.setPage} setPageSize={list.setPageSize} testid="inventory" unit="barang" />
          <p className="mt-2 text-xs text-muted-foreground">Hanya barang aktif. "Belum ada stok" = barang belum memiliki catatan stok di gudang tersebut (dihitung Stok Habis). "Tanpa Stok" = barang jasa/sewa/perizinan yang ditandai di master barang (tidak dihitung Stok Habis/Menipis/Overstock). Min/Max tetap dipakai sistem untuk menentukan status stok, tetapi disembunyikan dari tabel agar tampilan lebih ringkas.</p>
        </TabsContent>

        <TabsContent value="ledger" className="mt-4">
          <SortControl sort={ledgerSort} onChange={setLedgerSort} testid="inventory-ledger-sort-mobile"
            options={[{ value: "at", label: "Waktu" }, { value: "doc_no", label: "Dokumen" }, { value: "item_name", label: "Barang" },
              { value: "warehouse_name", label: "Gudang" }, { value: "qty_in", label: "Masuk" }, { value: "qty_out", label: "Keluar" },
              { value: "running_balance", label: "Saldo" }]} />
          <div className="mt-3 sm:mt-0 border rounded-xl overflow-auto bg-card shadow-sm" data-table-wrap="1" style={{ maxHeight: tableMaxHeight || undefined }} data-testid="inventory-ledger-table-wrap"><table className="m-stack w-full text-sm zebra">
            <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
              <SortTh sticky label="Waktu" k="at" sort={ledgerSort} onSort={onLedgerSort} testidPrefix="inventory-ledger-sort" />
              <SortTh sticky label="Dokumen" k="doc_no" sort={ledgerSort} onSort={onLedgerSort} testidPrefix="inventory-ledger-sort" />
              <SortTh sticky label="Barang" k="item_name" sort={ledgerSort} onSort={onLedgerSort} testidPrefix="inventory-ledger-sort" />
              <SortTh sticky label="Gudang" k="warehouse_name" sort={ledgerSort} onSort={onLedgerSort} testidPrefix="inventory-ledger-sort" />
              <SortTh sticky label="Masuk" k="qty_in" sort={ledgerSort} onSort={onLedgerSort} align="right" testidPrefix="inventory-ledger-sort" />
              <SortTh sticky label="Keluar" k="qty_out" sort={ledgerSort} onSort={onLedgerSort} align="right" testidPrefix="inventory-ledger-sort" />
              <SortTh sticky label="Saldo" k="running_balance" sort={ledgerSort} onSort={onLedgerSort} align="right" testidPrefix="inventory-ledger-sort" />
            </tr></thead>
            <tbody>{sortedLedger.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">Belum ada pergerakan stok sesuai filter</td></tr>}
              {sortedLedger.map((l) => (<tr key={l.id} className="border-t"><td data-label="Waktu" className="m-full p-3 text-xs">{fmtDateTime(l.at)}</td><td data-label="Dokumen" className="p-3"><span className="font-mono text-xs">{l.doc_type}</span> · {l.doc_no}</td><td data-label="Barang" className="p-3">{l.item_code} — {l.item_name}</td><td data-label="Gudang" className="p-3">{l.warehouse_name}</td><td data-label="Masuk" className="p-3 text-right tabular-nums text-emerald-600">{l.qty_in ? "+" + num(l.qty_in) : "-"}</td><td data-label="Keluar" className="p-3 text-right tabular-nums text-destructive">{l.qty_out ? "-" + num(l.qty_out) : "-"}</td><td data-label="Saldo" className="p-3 text-right tabular-nums font-semibold">{num(l.running_balance)}</td></tr>))}</tbody></table></div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
