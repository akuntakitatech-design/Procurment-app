import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { num, fmtDateTime } from "@/lib/format";
import { Search, Package, PackageX, TriangleAlert, TrendingUp, RotateCcw } from "lucide-react";

const ALL = "__all__";

function stockStatus(total, minTotal, maxTotal) {
  if (total <= 0) return "Out of Stock";
  if (minTotal > 0 && total <= minTotal) return "Low Stock";
  if (maxTotal > 0 && total > maxTotal) return "Overstock";
  return "Normal";
}

function statusLabel(status) {
  if (status === "Out of Stock") return "Habis";
  if (status === "Low Stock") return "Menipis";
  if (status === "Overstock") return "Overstock";
  return "Normal";
}

function SummaryCard({ title, value, subtitle, icon: Icon, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-2xl border bg-card p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md ${active ? "border-primary ring-2 ring-primary/10" : "hover:border-primary/30"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
          <div className="mt-2 text-3xl font-bold tabular-nums">{num(value)}</div>
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </button>
  );
}

export default function Inventory() {
  const [pos, setPos] = useState([]);
  const [ledger, setLedger] = useState([]);
  const [items, setItems] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [categories, setCategories] = useState([]);
  const [q, setQ] = useState("");
  const [categoryFilter, setCategoryFilter] = useState(ALL);
  const [warehouseFilter, setWarehouseFilter] = useState(ALL);
  const [statusFilter, setStatusFilter] = useState(ALL);

  useEffect(() => {
    Promise.all([
      api.get("/inventory/position"),
      api.get("/inventory/ledger"),
      api.get("/master/items?active_only=true"),
      api.get("/master/warehouses?active_only=true"),
      api.get("/master/item_categories?active_only=true").catch(() => ({ data: [] })),
    ]).then(([p, l, i, w, c]) => {
      setPos(p.data || []);
      setLedger(l.data || []);
      setItems(i.data || []);
      setWarehouses(w.data || []);
      setCategories(c.data || []);
    });
  }, []);

  const itemMap = useMemo(() => Object.fromEntries(items.map((x) => [x.id, x])), [items]);
  const categoryMap = useMemo(() => Object.fromEntries(categories.map((x) => [x.id, x])), [categories]);

  const categoryName = useCallback((item) => {
    if (!item) return "Tanpa Kategori";
    return categoryMap[item.category_id]?.name || item.category || "Tanpa Kategori";
  }, [categoryMap]);

  const categoryOptions = useMemo(() => {
    const names = new Set();
    items.forEach((item) => names.add(categoryMap[item.category_id]?.name || item.category || "Tanpa Kategori"));
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [items, categoryMap]);

  const visibleWarehouses = useMemo(() => {
    if (warehouseFilter !== ALL) return warehouses.filter((w) => w.id === warehouseFilter);
    const used = new Set(pos.map((p) => p.warehouse_id));
    return warehouses.filter((w) => used.has(w.id));
  }, [warehouses, pos, warehouseFilter]);

  const grouped = useMemo(() => {
    const map = new Map();
    const scoped = pos.filter((p) => warehouseFilter === ALL || p.warehouse_id === warehouseFilter);

    for (const p of scoped) {
      const item = itemMap[p.item_id] || {};
      const cat = categoryName(item);
      if (categoryFilter !== ALL && cat !== categoryFilter) continue;

      if (!map.has(p.item_id)) {
        map.set(p.item_id, {
          item_id: p.item_id,
          item_code: p.item_code,
          item_name: p.item_name,
          unit: item.unit || p.unit || "-",
          category: cat,
          warehouses: {},
          on_hand: 0,
          min_total: 0,
          max_total: 0,
        });
      }
      const g = map.get(p.item_id);
      g.warehouses[p.warehouse_id] = p;
      g.on_hand += Number(p.on_hand || 0);
      g.min_total += Number(p.min_stock || 0);
      g.max_total += Number(p.max_stock || 0);
    }

    return [...map.values()].map((g) => ({
      ...g,
      status: stockStatus(g.on_hand, g.min_total, g.max_total),
    }));
  }, [pos, itemMap, categoryFilter, warehouseFilter, categoryName]);

  const summary = useMemo(() => ({
    total: grouped.length,
    out: grouped.filter((x) => x.status === "Out of Stock").length,
    low: grouped.filter((x) => x.status === "Low Stock").length,
    over: grouped.filter((x) => x.status === "Overstock").length,
  }), [grouped]);

  const filtered = useMemo(() => grouped.filter((g) => {
    if (statusFilter !== ALL && g.status !== statusFilter) return false;
    if (!q) return true;
    const hay = `${g.item_code || ""} ${g.item_name || ""} ${g.category || ""}`.toLowerCase();
    return hay.includes(q.toLowerCase());
  }), [grouped, q, statusFilter]);

  const filteredLedger = useMemo(() => ledger.filter((l) => {
    if (warehouseFilter !== ALL && l.warehouse_id !== warehouseFilter) return false;
    const item = itemMap[l.item_id] || {};
    if (categoryFilter !== ALL && categoryName(item) !== categoryFilter) return false;
    if (!q) return true;
    return `${l.item_code || ""} ${l.item_name || ""} ${l.warehouse_name || ""} ${l.doc_no || ""}`.toLowerCase().includes(q.toLowerCase());
  }), [ledger, warehouseFilter, categoryFilter, q, itemMap, categoryName]);

  const resetFilters = () => {
    setQ("");
    setCategoryFilter(ALL);
    setWarehouseFilter(ALL);
    setStatusFilter(ALL);
  };

  return (
    <div>
      <PageHeader title="Inventory / Stock" subtitle="Posisi stok & kartu stok per gudang" />
      <Tabs defaultValue="position">
        <TabsList><TabsTrigger value="position" data-testid="inv-tab-position">Posisi Stok</TabsTrigger><TabsTrigger value="ledger" data-testid="inv-tab-ledger">Kartu Stok (Ledger)</TabsTrigger></TabsList>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard title="Jumlah Item" value={summary.total} subtitle="Item pada filter aktif" icon={Package} active={statusFilter === ALL} onClick={() => setStatusFilter(ALL)} />
          <SummaryCard title="Stok Habis" value={summary.out} subtitle="Total stok = 0" icon={PackageX} active={statusFilter === "Out of Stock"} onClick={() => setStatusFilter(statusFilter === "Out of Stock" ? ALL : "Out of Stock")} />
          <SummaryCard title="Stok Menipis" value={summary.low} subtitle="Sudah mencapai batas minimum" icon={TriangleAlert} active={statusFilter === "Low Stock"} onClick={() => setStatusFilter(statusFilter === "Low Stock" ? ALL : "Low Stock")} />
          <SummaryCard title="Overstock" value={summary.over} subtitle="Melebihi batas maksimum" icon={TrendingUp} active={statusFilter === "Overstock"} onClick={() => setStatusFilter(statusFilter === "Overstock" ? ALL : "Overstock")} />
        </div>

        <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative min-w-0 flex-1 lg:max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode / nama barang..." className="pl-9" />
          </div>
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger className="w-full lg:w-[220px]" data-testid="inventory-category-filter"><SelectValue placeholder="Semua kategori" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Semua Kategori</SelectItem>
              {categoryOptions.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={warehouseFilter} onValueChange={setWarehouseFilter}>
            <SelectTrigger className="w-full lg:w-[220px]" data-testid="inventory-warehouse-filter"><SelectValue placeholder="Semua gudang" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Semua Gudang</SelectItem>
              {warehouses.map((w) => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={resetFilters}><RotateCcw className="mr-2 h-4 w-4" />Reset</Button>
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
                {filtered.length === 0 && <tr><td colSpan={6 + visibleWarehouses.length} className="p-8 text-center text-muted-foreground">Tidak ada data stok sesuai filter</td></tr>}
                {filtered.map((g) => (
                  <tr key={g.item_id} className="border-t">
                    <td className="p-3 font-mono text-xs font-semibold">{g.item_code}</td>
                    <td className="p-3 font-medium">{g.item_name}</td>
                    <td className="p-3">{g.category}</td>
                    <td className="p-3">{g.unit}</td>
                    {visibleWarehouses.map((w) => {
                      const p = g.warehouses[w.id];
                      return (
                        <td key={w.id} className="p-3 text-right">
                          <div className="font-semibold tabular-nums">{num(p?.on_hand || 0)}</div>
                          <div className="mt-0.5 text-[10px] text-muted-foreground">{p ? statusLabel(p.status) : "Belum ada stok"}</div>
                        </td>
                      );
                    })}
                    {visibleWarehouses.length > 1 && <td className="p-3 text-right font-bold tabular-nums">{num(g.on_hand)}</td>}
                    <td className="p-3"><StatusBadge status={g.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Min/Max tetap dipakai sistem untuk menentukan status stok, tetapi disembunyikan dari tabel agar tampilan lebih ringkas.</p>
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
