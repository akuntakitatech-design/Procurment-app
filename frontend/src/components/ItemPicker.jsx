import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChevronsUpDown, Plus, Search } from "lucide-react";

// Pemilih Barang global: tabel Kode | Nama | Part Number | Merk | Satuan | Stok Tersedia (gudang aktif).
const whCache = new Map();
function loadWarehouseStock(wid) {
  const hit = whCache.get(wid);
  if (hit && Date.now() - hit.at < 20000) return hit.p;
  const p = api.get(`/stock/warehouse/${wid}`).then((r) => r.data || {}).catch(() => null);
  whCache.set(wid, { at: Date.now(), p });
  return p;
}
const COLS = [["code", "Kode Barang"], ["name", "Nama Barang"], ["part_number", "Part Number"], ["brand", "Merk"]];
const LIMIT = 100;

export function ItemPicker({ items, uoms = {}, value, onChange, warehouseId, disabled, testid, onCreate, placeholder = "Pilih barang" }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState({ key: "code", dir: 1 });
  const [stock, setStock] = useState(null);
  useEffect(() => { if (open && warehouseId) loadWarehouseStock(warehouseId).then(setStock); else setStock(null); }, [open, warehouseId]);
  const unitOf = (it) => { const u = uoms[it.base_uom_id]; return (u && (u.symbol || u.name || u.code)) || it.unit || "-"; };
  const rows = useMemo(() => {
    const n = q.trim().toLowerCase();
    const f = (items || []).filter((it) => !n || COLS.some(([k]) => String(it[k] || "").toLowerCase().includes(n)));
    return f.sort((a, b) => String(a[sort.key] || "").localeCompare(String(b[sort.key] || ""), "id", { numeric: true }) * sort.dir);
  }, [items, q, sort]);
  const selected = (items || []).find((it) => it.id === value);
  const pick = (id) => { onChange(id); setOpen(false); setQ(""); };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" disabled={disabled} data-testid={testid} className="h-9 w-full justify-between text-sm font-normal">
          <span className={cn("truncate", !selected && "text-muted-foreground")}>{selected ? `${selected.code ? selected.code + " — " : ""}${selected.name}` : placeholder}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="z-50 w-[min(860px,calc(100vw-2rem))] p-0" data-testid={`${testid || "item-picker"}-panel`}>
        <div className="relative border-b p-2"><Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode, nama, part number, merk..." className="h-9 pl-8" data-testid={`${testid || "item-picker"}-search`} /></div>
        <div className="max-h-[340px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {COLS.map(([k, l]) => <th key={k} className="p-2"><button type="button" onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? -s.dir : 1 }))} className="uppercase hover:text-foreground" data-testid={`${testid || "item-picker"}-sort-${k}`}>{l}{sort.key === k ? (sort.dir === 1 ? " ↑" : " ↓") : ""}</button></th>)}
              <th className="p-2">Satuan</th><th className="p-2 text-right">Stok Tersedia</th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-muted-foreground">Barang tidak ditemukan</td></tr>}
              {rows.slice(0, LIMIT).map((it) => <tr key={it.id} onClick={() => pick(it.id)} className={cn("cursor-pointer border-t transition-colors hover:bg-accent", it.id === value && "bg-primary/5 font-medium")} data-testid={`${testid || "item-picker"}-row-${it.code || it.id}`}>
                <td className="p-2 font-mono text-xs">{it.code || "-"}</td><td className="p-2">{it.name}</td><td className="p-2 text-xs">{it.part_number || "-"}</td>
                <td className="p-2 text-xs">{it.brand || "-"}</td><td className="p-2 text-xs">{unitOf(it)}</td>
                <td className="p-2 text-right tabular-nums">{!warehouseId || !stock ? "-" : num(stock[it.id] || 0)}</td></tr>)}
            </tbody>
          </table>
          {rows.length > LIMIT && <div className="p-2 text-center text-[11px] text-muted-foreground">Menampilkan {LIMIT} dari {rows.length} barang — persempit pencarian</div>}
        </div>
        {onCreate && <div className="border-t p-1"><button type="button" onClick={() => { setOpen(false); onCreate.onClick(); }} data-testid={onCreate.testid} className="flex w-full items-center gap-2 rounded-sm px-2 py-2 text-sm font-medium text-primary hover:bg-accent"><Plus className="h-4 w-4" />Tambah Barang</button></div>}
      </PopoverContent>
    </Popover>
  );
}
