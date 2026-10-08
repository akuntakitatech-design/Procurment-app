import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { AlertCircle, ChevronsUpDown, Loader2, Lock, Plus, RotateCw, Search } from "lucide-react";
import { LOOKUP_MESSAGES } from "@/lib/lookupCore";

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

/** Label barang untuk dokumen pembelian: Nama · Merk · Part Number (tanpa kode). */
export const itemDisplayName = (it, fallback = "") => (it ? [it.name, it.brand, it.part_number].filter((x) => String(x || "").trim()).join(" · ") : fallback);

export function ItemPicker({ items, uoms = {}, value, onChange, warehouseId, disabled, testid, onCreate, placeholder = "Pilih barang", formatLabel = null, fallbackLabel = "", lookup = null }) {
  const [open, setOpen] = useState(false);
  // Status data referensi Barang (loading/error/izin) — jangan tampil sebagai "Barang tidak ditemukan".
  const lkState = lookup?.state || "ready";
  const lkFailed = lkState === "error" || lkState === "auth" || lkState === "denied";
  const lkLoading = lkState === "loading" && !(items || []).length;
  const [q, setQ] = useState("");
  const [sort, setSort] = useState({ key: "code", dir: 1 });
  const [stock, setStock] = useState(null);
  useEffect(() => { if (open && warehouseId) loadWarehouseStock(warehouseId).then(setStock); else setStock(null); }, [open, warehouseId]);
  const unitOf = (it) => { const u = uoms[it.base_uom_id]; return (u && (u.symbol || u.name || u.code)) || it.unit || "-"; };
  const rows = useMemo(() => {
    if (!open) return [];   // daftar barang hanya diproses saat picker dibuka (hemat render per baris)
    const n = q.trim().toLowerCase();
    const f = (items || []).filter((it) => !n || COLS.some(([k]) => String(it[k] || "").toLowerCase().includes(n)));
    return f.sort((a, b) => String(a[sort.key] || "").localeCompare(String(b[sort.key] || ""), "id", { numeric: true }) * sort.dir);
  }, [items, q, sort, open]);
  const selected = useMemo(() => (value ? (items || []).find((it) => it.id === value) : null), [items, value]);
  const text = selected ? (formatLabel ? formatLabel(selected) : `${selected.code ? selected.code + " — " : ""}${selected.name}`) : (value && fallbackLabel) || "";
  const pick = (id) => { onChange(id); setOpen(false); setQ(""); };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" role="combobox" disabled={disabled} data-testid={testid} title={text || undefined}
          aria-invalid={(lkFailed && !text) || undefined} data-lookup-state={lookup ? lkState : undefined}
          className={cn("w-full justify-between text-sm font-normal", lkFailed && !text && "border-destructive ring-1 ring-destructive", formatLabel ? "h-auto min-h-9 py-1.5 text-left disabled:cursor-default disabled:bg-muted/40 disabled:opacity-100" : "h-9")}>
          <span className={cn(formatLabel ? "line-clamp-2 whitespace-normal break-words leading-snug" : "truncate", !text && "text-muted-foreground", !text && lkFailed && "text-destructive")} data-testid={testid ? `${testid}-label` : undefined}>{text || (lkLoading ? LOOKUP_MESSAGES.loading : lkFailed && !(items || []).length ? (lkState === "denied" ? "Tidak ada izin" : "Gagal memuat data") : placeholder)}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="z-50 w-[min(860px,calc(100vw-2rem))] p-0" data-testid={`${testid || "item-picker"}-panel`}>
        {lkFailed && <div role="alert" className="flex items-start justify-between gap-2 border-b px-3 py-2.5 text-sm text-destructive" data-testid={`${testid || "item-picker"}-lookup-error`}><span className="flex items-start gap-2">{lkState === "denied" ? <Lock className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}{lookup?.message || LOOKUP_MESSAGES.error}</span>{lkState !== "denied" && lookup?.retry && <button type="button" onClick={() => lookup.retry()} data-testid={`${testid || "item-picker"}-lookup-retry`} className="flex shrink-0 items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><RotateCw className="h-3.5 w-3.5" />Muat ulang</button>}</div>}
        <div className="relative border-b p-2"><Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode, nama, part number, merk..." className="h-9 pl-8" data-testid={`${testid || "item-picker"}-search`} /></div>
        <div className="max-h-[340px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {COLS.map(([k, l]) => <th key={k} className="p-2"><button type="button" onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? -s.dir : 1 }))} className="uppercase hover:text-foreground" data-testid={`${testid || "item-picker"}-sort-${k}`}>{l}{sort.key === k ? (sort.dir === 1 ? " ↑" : " ↓") : ""}</button></th>)}
              <th className="p-2">Satuan</th><th className="p-2 text-right">Stok Tersedia</th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-muted-foreground" data-testid={`${testid || "item-picker"}-empty`}>{lkLoading ? <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />{LOOKUP_MESSAGES.loading}</span> : lkFailed && !(items || []).length ? "Data barang belum dapat dimuat." : !(items || []).length ? LOOKUP_MESSAGES.empty : "Barang tidak ditemukan"}</td></tr>}
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
