import { AlertTriangle, ArrowRight, Boxes, CircleSlash, Layers, PackageMinus, PackagePlus, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { asOfLabel, compactRupiah, inventoryCards, inventoryLink } from "@/lib/dashboard";
import { rupiah } from "@/lib/format";
import { Panel } from "./Panel";
import { RingKpi } from "./RingKpi";

const ICONS = { total: Layers, out_of_stock: CircleSlash, low_stock: PackageMinus, overstock: PackagePlus };

/** Layer 2 — Persediaan saat ini. Angka & semantics existing: jumlah/stok = snapshot hari ini (barang aktif, ikut filter
 *  Divisi); Nilai Persediaan = engine valuation/MWA per tanggal posisi. Tidak ada perhitungan baru di frontend. */
export function InventoryPanel({ inv, f, nav, onUnvalued, delay = 0 }) {
  const cards = inventoryCards(inv);
  return <Panel title="Persediaan saat ini" subtitle="snapshot hari ini · barang aktif · ikut filter Divisi" icon={Boxes} testid="dash-inventory" delay={delay} className="h-full"
    action={<Button variant="ghost" size="sm" onClick={() => nav(inventoryLink("total", f))} className="h-8 shrink-0 rounded-lg text-[#3D5A80]" data-testid="dash-inventory-detail">Lihat Detail<ArrowRight className="ml-1 h-3.5 w-3.5" /></Button>}>
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2" data-testid="dash-inventory-current">
      {inv.inventory_value != null && <div className="sm:col-span-2" data-testid="dash-inventory-valuation">
        <RingKpi label="Nilai Persediaan" icon={Wallet} tone="blue" testid="dash-inventory-value" delay={delay}
          title={`${rupiah(inv.inventory_value)} — engine valuation/MWA, termasuk barang nonaktif yang masih bersaldo`}
          value={<span data-testid="dash-inventory-value-amount">{compactRupiah(inv.inventory_value)}</span>}
          sub={<>per <span className="font-medium text-slate-500" data-testid="dash-inventory-value-asof">{asOfLabel(inv.inventory_value_as_of)}</span> · engine valuation</>} />
      </div>}
      {cards.map((c, i) => <RingKpi key={c.key} label={c.label} icon={ICONS[c.key]} tone={c.tone} value={c.value} pct={c.pct} sub={c.sub}
        delay={delay + (i + 1) * 40} onClick={() => nav(inventoryLink(c.key, f))} testid={`dash-inventory-${c.key}`} />)}
    </div>
    {(inv.unvalued_items > 0 || inv.unreconstructable_pools > 0) && <div className="mt-3 flex flex-wrap gap-1.5">
      {inv.unvalued_items > 0 && <button type="button" onClick={onUnvalued} className="rounded-full bg-[#9A6A22]/10 px-2 py-0.5 text-[11px] text-[#9A6A22] underline-offset-2 transition-colors hover:bg-[#9A6A22]/20 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#9A6A22]/40" data-testid="dash-inventory-unvalued">
        {inv.unvalued_items} barang punya stok tetapi belum bernilai</button>}
      {inv.unreconstructable_pools > 0 && <span className="flex items-center gap-1 rounded-full bg-[#9A6A22]/10 px-2 py-0.5 text-[11px] text-[#9A6A22]" data-testid="dash-inventory-unreconstructable"
        title={`${inv.unreconstructable_items} barang punya stok lama tanpa saldo awal / riwayat valuation sebelum tanggal ini. Nilainya tidak diasumsikan (tidak memakai nilai saat ini), sehingga angka historis belum lengkap.`}>
        <AlertTriangle className="h-3 w-3" />{inv.unreconstructable_pools} pool persediaan historis belum dapat direkonstruksi</span>}
    </div>}
  </Panel>;
}
