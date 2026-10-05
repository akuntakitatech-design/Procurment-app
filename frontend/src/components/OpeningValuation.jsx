import { useEffect, useState, useMemo } from "react";
import api, { apiError } from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { useAuth } from "@/context/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Combobox } from "@/components/Combobox";
import { DatePicker, Field } from "@/components/DatePicker";
import { NumericInput } from "@/components/NumericInput";
import { Warehouse, Save, Search, Info } from "lucide-react";
import { num, rupiah, todayISO } from "@/lib/format";
import { toast } from "sonner";

// Opening Inventory Valuation: establishes the opening moving-average cost for EXISTING
// physical stock as of a cut-off date. It does NOT add or change physical quantity.
export function OpeningValuation() {
  const masters = useMasters(); const { can } = useAuth();
  const canPrice = can("view_purchase_price");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState(""); const [wh, setWh] = useState(""); const [status, setStatus] = useState("all");
  const [cutoff, setCutoff] = useState(todayISO());
  const [costs, setCosts] = useState({}); const [savingKey, setSavingKey] = useState(null);

  const whOpts = useMemo(() => [{ value: "", label: "Semua Gudang" }, ...masters.opts("warehouses")], [masters]);

  const load = () => {
    setLoading(true);
    const params = {};
    if (q) params.q = q;
    if (wh) params.warehouse_id = wh;
    if (status !== "all") params.status = status;
    api.get("/valuation/opening-candidates", { params })
      .then((r) => {
        const list = r.data?.rows || [];
        setRows(list);
        // Harga Beli dari Import Saldo Awal menjadi nilai awal input (masih Belum Dinilai sampai Tetapkan).
        setCosts((c) => {
          const next = { ...c };
          list.forEach((x) => {
            const k = `${x.item_id}::${x.warehouse_id}`;
            if (x.status !== "valued" && x.opening_cost_candidate > 0 && (next[k] === undefined || next[k] === "")) next[k] = String(x.opening_cost_candidate);
          });
          return next;
        });
      })
      .catch((e) => toast.error(apiError(e.response?.data?.detail)))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wh, status]);

  const keyOf = (r) => `${r.item_id}::${r.warehouse_id}`;
  const post = async (r) => {
    const k = keyOf(r);
    const cost = Number(costs[k]);
    if (!cost || cost <= 0) return toast.error("Opening Average Cost wajib diisi (> 0)");
    try {
      setSavingKey(k);
      await api.post("/valuation/opening", {
        item_id: r.item_id, warehouse_id: r.warehouse_id,
        opening_avg_cost: cost, cutoff_date: cutoff,
      });
      toast.success(`Nilai awal ${r.item_code} ditetapkan pada ${String(cutoff).slice(0, 10)}`);
      setCosts((c) => { const n = { ...c }; delete n[k]; return n; });
      load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); }
    finally { setSavingKey(null); }
  };

  if (!canPrice) return <Card><CardContent className="pt-6 text-sm text-muted-foreground">Anda tidak memiliki izin melihat/menetapkan nilai persediaan.</CardContent></Card>;

  return <div className="space-y-4">
    <div className="flex items-start gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/8 text-primary"><Warehouse className="h-4.5 w-4.5" /></div>
      <div><div className="font-head font-semibold">Opening Inventory Valuation</div>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">Menetapkan nilai awal persediaan (rata-rata) untuk stok fisik yang sudah ada per tanggal cut-off.</p></div>
    </div>

    <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-400" data-testid="opening-cutoff-note">
      <Info className="mt-0.5 h-4 w-4 shrink-0" />
      <span>Saldo fisik tidak ditambah. Proses ini hanya menetapkan nilai awal persediaan pada tanggal cut-off.</span>
    </div>

    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
      <Field label="Tanggal Cut-off"><DatePicker value={cutoff} onChange={setCutoff} /></Field>
      <Field label="Gudang"><Combobox options={whOpts} value={wh} onChange={setWh} /></Field>
      <Field label="Status">
        <Combobox options={[{ value: "all", label: "Semua" }, { value: "unvalued", label: "Belum Dinilai" }, { value: "valued", label: "Sudah Dinilai" }]} value={status} onChange={setStatus} />
      </Field>
      <Field label="Cari Barang">
        <div className="flex gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} placeholder="Kode / nama barang" data-testid="opening-search" />
          <Button variant="outline" size="icon" onClick={load}><Search className="h-4 w-4" /></Button>
        </div>
      </Field>
    </div>

    <div className="border rounded-md overflow-x-auto bg-card">
      <table className="w-full text-sm min-w-[920px]">
        <thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
          <th className="p-2 min-w-[220px]">Barang</th><th className="p-2">Gudang</th>
          <th className="p-2 text-right">Qty Existing</th><th className="p-2">Satuan Dasar</th>
          <th className="p-2 w-44">Opening Average Cost</th><th className="p-2 text-right">Opening Inventory Value</th>
          <th className="p-2">Status</th><th className="p-2 w-24"></th>
        </tr></thead>
        <tbody>
          {loading && <tr><td colSpan={8} className="p-6 text-center text-muted-foreground">Memuat…</td></tr>}
          {!loading && rows.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-muted-foreground">Tidak ada stok fisik yang perlu dinilai</td></tr>}
          {!loading && rows.map((r) => {
            const k = keyOf(r);
            const valued = r.status === "valued";
            const blocked = !valued && !!r.opening_blocked_reason;
            const liveCost = valued ? r.avg_cost : Number(costs[k] || 0);
            const liveVal = valued ? r.inventory_value : (r.opening_import_qty ?? r.qty_existing) * (Number(costs[k]) || 0);
            return <tr key={k} className="border-t" data-testid={`opening-row-${k}`}>
              <td className="p-2"><div className="font-medium">{r.item_name}</div><div className="font-mono text-[11px] text-muted-foreground">{r.item_code}</div></td>
              <td className="p-2">{r.warehouse_name}</td>
              <td className="p-2 text-right tabular-nums font-semibold">{num(r.qty_existing)}{r.opening_import_qty != null && r.opening_import_qty !== r.qty_existing && <div className="text-[11px] font-normal text-muted-foreground" data-testid={`opening-import-qty-${k}`}>Saldo awal: {num(r.opening_import_qty)}</div>}</td>
              <td className="p-2">{r.base_uom_name || "-"}</td>
              <td className="p-1.5">{valued
                ? <span className="tabular-nums">{rupiah(r.avg_cost)}</span>
                : <div>
                  <NumericInput mode="money" value={costs[k] ?? ""} onChange={(v) => setCosts((c) => ({ ...c, [k]: v }))} className="h-9 text-right" placeholder="0" data-testid={`opening-cost-${k}`} />
                  {r.opening_cost_candidate > 0 && <div className="mt-0.5 text-[11px] text-muted-foreground" data-testid={`opening-cost-source-${k}`}>
                    {Number(costs[k]) === Number(r.opening_cost_candidate) ? "Dari Harga Beli Saldo Awal" : `Saldo Awal: ${rupiah(r.opening_cost_candidate)}`}
                  </div>}
                </div>}</td>
              <td className="p-2 text-right tabular-nums font-semibold" data-testid={`opening-value-${k}`}>{rupiah(liveVal)}</td>
              <td className="p-2">{valued
                ? <Badge className="bg-emerald-500/12 text-emerald-700 dark:text-emerald-400 border-0">Sudah Dinilai</Badge>
                : <div><Badge variant="outline" className="text-amber-600 border-amber-500/40">Belum Dinilai</Badge>
                  {blocked && <div className="mt-1 max-w-[260px] text-[11px] leading-4 text-destructive" data-testid={`opening-blocked-${k}`}>{r.opening_blocked_reason}</div>}</div>}</td>
              <td className="p-1.5 text-right">{!valued && <Button size="sm" onClick={() => post(r)} disabled={blocked || savingKey === k || !(Number(costs[k]) > 0)} data-testid={`opening-save-${k}`}><Save className="h-3.5 w-3.5 mr-1" />{savingKey === k ? "…" : "Tetapkan"}</Button>}</td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  </div>;
}
