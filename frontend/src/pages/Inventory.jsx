import { useEffect, useMemo, useState } from "react";
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
import { Search, Package, PackageX, TriangleAlert, TrendingUp, RotateCcw } from "lucide-react";

const ALL = "__all__";

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
      className={`rounded-2xl border bg-card p-4 text-left shadow-sm transition-transform hover:-translate-y-0.5 hover:shadow-md ${active ? "border-primary ring-2 ring-primary/10" : "hover:border-primary/30"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
          <div className="mt-2 text-3xl font-bold tabular-nums" data-testid={testid ? `${testid}-value` : undefined}>{num(value)}</div>
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </button>
  );
}

// Posisi Stok per BARANG dari ringkasan canonical backend (stock_summary = Master Barang = Dashboard).
// Frontend tidak menghitung status/summary; barang aktif tanpa catatan stok tetap tampil (Stok Habis, "Belum ada stok").
export default function Inventory() {
  const [ledger, setLedger] = useState([]);
  const [items, setItems] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState(ALL);
  const [warehouseFilter, setWarehouseFilter] = useState(ALL);
  const [sp, setSp] = useSearchParams();
  const STATUS_OK = ["Out of Stock", "Low Stock", "Overstock", "Normal", "No Stock"];
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

  const clearDivision = () => { const n = new URLSearchParams(sp); n.delete("division_id"); setSp(n, { replace: true }); };
  const resetFilters = () => {
    list.setQ("");
    if (divisionId) clearDivision();
    setCategoryFilter(ALL);
    setWarehouseFilter(ALL);
    setStatusFilter(ALL);
  };
  const toggle = (st) => setStatusFilter(statusFilter === st ? ALL : st);

  return (
    <div>
      <PageHeader title="Inventory / Stock" subtitle="Posisi stok & kartu stok per gudang" />
      <Tabs defaultValue="position">
        <TabsList><TabsTrigger value="position" data-testid="inv-tab-position">Posisi Stok</TabsTrigger><TabsTrigger value="ledger" data-testid="inv-tab-ledger">Kartu Stok (Ledger)</TabsTrigger></TabsList>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard testid="inv-summary-total" title="Jumlah Item" value={summary.total} subtitle="Barang aktif pada filter" icon={Package} active={statusFilter === ALL} onClick={() => setStatusFilter(ALL)} />
          <SummaryCard testid="inv-summary-out" title="Stok Habis" value={summary.out_of_stock} subtitle={summary.no_stock ? `Total stok = 0 · ${num(summary.no_stock)} belum ada stok` : "Total stok = 0"} icon={PackageX} active={statusFilter === "Out of Stock"} onClick={() => toggle("Out of Stock")} />
          <SummaryCard testid="inv-summary-low" title="Stok Menipis" value={summary.low_stock} subtitle="Sudah mencapai batas minimum" icon={TriangleAlert} active={statusFilter === "Low Stock"} onClick={() => toggle("Low Stock")} />
          <SummaryCard testid="inv-summary-over" title="Overstock" value={summary.overstock} subtitle="Melebihi batas maksimum" icon={TrendingUp} active={statusFilter === "Overstock"} onClick={() => toggle("Overstock")} />
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
          <div className="border rounded-xl overflow-x-auto bg-card shadow-sm">
            <table className="w-full text-sm zebra min-w-[820px]">
              <thead className="bg-muted">
                <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="p-3 whitespace-nowrap">Kode</th>
                  <th className="p-3 min-w-[220px]">Barang</th>
                  <th className="p-3 min-w-[150px]">Kategori</th>
                  <th className="p-3 w-20">Satuan</th>
                  {visibleWarehouses.map((w) => <th key={w.id} className="p-3 text-right min-w-[120px] whitespace-nowrap">{w.name}</th>)}
                  {visibleWarehouses.length > 1 && <th className="p-3 text-right min-w-[110px]">Total Stok</th>}
                  <th className="p-3 min-w-[120px]">Status</th>
                </tr>
              </thead>
              <tbody>
                {list.loading && rows.length === 0 && [0, 1, 2].map((i) => <tr key={i} className="border-t"><td colSpan={6 + visibleWarehouses.length} className="p-3"><Skeleton className="h-5 w-full" /></td></tr>)}
                {list.error && <tr><td colSpan={6 + visibleWarehouses.length} className="p-8 text-center text-muted-foreground" data-testid="inventory-error">Gagal memuat posisi stok. <Button variant="link" className="h-auto p-0" onClick={list.reload}>Coba lagi</Button></td></tr>}
                {!list.loading && !list.error && rows.length === 0 && <tr><td colSpan={6 + visibleWarehouses.length} className="p-8 text-center text-muted-foreground" data-testid="inventory-empty">Tidak ada data stok sesuai filter</td></tr>}
                {rows.map((g) => (
                  <tr key={g.id} className="border-t" data-testid={`inventory-row-${g.code}`}>
                    <td className="p-3 font-mono text-xs font-semibold">{g.code}</td>
                    <td className="p-3 font-medium">{g.name}</td>
                    <td className="p-3">{g.category_label || "Tanpa Kategori"}</td>
                    <td className="p-3">{g.unit_label || "-"}</td>
                    {visibleWarehouses.map((w) => {
                      const c = g.stock?.[w.id];
                      return (
                        <td key={w.id} className="p-3 text-right">
                          <div className="font-semibold tabular-nums">{num(c?.qty || 0)}</div>
                          <div className="mt-0.5 text-[10px] text-muted-foreground">{c ? statusLabel(c.status) : "Belum ada stok"}</div>
                        </td>
                      );
                    })}
                    {visibleWarehouses.length > 1 && <td className="p-3 text-right font-bold tabular-nums">{num(g.total_stock)}</td>}
                    <td className="p-3"><StatusBadge status={g.stock_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ListPager total={list.total} page={list.page} pageSize={list.pageSize} setPage={list.setPage} setPageSize={list.setPageSize} testid="inventory" unit="barang" />
          <p className="mt-2 text-xs text-muted-foreground">Hanya barang aktif. "Belum ada stok" = barang belum memiliki catatan stok di gudang tersebut (dihitung Stok Habis). Min/Max tetap dipakai sistem untuk menentukan status stok, tetapi disembunyikan dari tabel agar tampilan lebih ringkas.</p>
        </TabsContent>

        <TabsContent value="ledger" className="mt-4">
          <div className="border rounded-xl overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">Waktu</th><th className="p-3">Dokumen</th><th className="p-3">Barang</th><th className="p-3">Gudang</th><th className="p-3 text-right">Masuk</th><th className="p-3 text-right">Keluar</th><th className="p-3 text-right">Saldo</th></tr></thead>
            <tbody>{filteredLedger.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-muted-foreground">Belum ada pergerakan stok sesuai filter</td></tr>}
              {filteredLedger.map((l) => (<tr key={l.id} className="border-t"><td className="p-3 text-xs">{fmtDateTime(l.at)}</td><td className="p-3"><span className="font-mono text-xs">{l.doc_type}</span> · {l.doc_no}</td><td className="p-3">{l.item_code} — {l.item_name}</td><td className="p-3">{l.warehouse_name}</td><td className="p-3 text-right tabular-nums text-emerald-600">{l.qty_in ? "+" + num(l.qty_in) : "-"}</td><td className="p-3 text-right tabular-nums text-destructive">{l.qty_out ? "-" + num(l.qty_out) : "-"}</td><td className="p-3 text-right tabular-nums font-semibold">{num(l.running_balance)}</td></tr>))}</tbody></table></div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
