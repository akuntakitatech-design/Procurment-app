import { useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { num } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Combobox } from "@/components/Combobox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { ListTree, Search, Users } from "lucide-react";
import { toast } from "sonner";

const EPS = 1e-6;
const n = (v) => Number(v) || 0;
const sum = (arr, k) => (arr || []).reduce((a, x) => a + n(x[k]), 0);
const MANUAL = "__manual__";

/** Bagi Qty PO (satuan dasar) ke sumber RO secara FIFO (urutan sumber dari server), dibatasi sisa. */
export function proposeSources(sources, baseQty) {
  let rem = Math.max(0, n(baseQty));
  return (sources || []).map((s) => { const take = Math.min(n(s.sisa), rem); rem -= take; return { ...s, qty: +take.toFixed(6) }; });
}

const factorOf = (l) => n(l.conversion_factor) || 1;
export const baseQtyOf = (l) => +(n(l.qty) * factorOf(l)).toFixed(6);

/** Baris hasil Tarik RO -> baris PO. Qty dalam satuan dasar barang (normalisasi UOM existing). */
export function fromPulledRow(r, qty, defaults = {}, extra = {}) {
  const sources = proposeSources((r.sources || []).map((s) => ({ ...s, ro_id: r.ro_id, ro_no: r.ro_no, line_id: r.line_id })), qty);
  return {
    item_id: r.item_id, qty: +n(qty).toFixed(6), unit: r.base_unit || r.unit, uom_id: r.base_uom_id || r.uom_id, conversion_factor: 1,
    warehouse_id: r.warehouse_id || defaults.warehouse_id, project_id: r.project_id || defaults.project_id, unit_id: r.unit_id || defaults.unit_id,
    _warehouseOverride: !!r.warehouse_id, _projectOverride: !!r.project_id, _unitOverride: !!r.unit_id,
    price: 0, discount: 0, notes: r.notes || "", _locked: true, _sourceHeader: r.source_header || null,
    _sourceLabel: `RO: ${r.ro_no}${(r.mro_nos || []).length ? " • MRO: " + r.mro_nos.join(", ") : ""}`,
    _roSources: sources, _roDivisionId: r.division_id, ...extra,
  };
}

/** Baris PO tersimpan (GET /po/:id) -> state form; rincian sumber tersimpan dimuat ulang. */
export function fromSavedPoLine(l) {
  const src = l.ro_sources || [];
  return src.length ? { ...l, _roSources: src.map((s) => ({ ...s, qty: n(s.qty) })) } : l;
}

/** Qty PO berubah dari tabel item -> rincian diusulkan ulang (FIFO) agar tetap seimbang. */
export function rebalance(l) {
  if (!(l._roSources || []).length) return l;
  const base = baseQtyOf(l);
  if (Math.abs(sum(l._roSources, "qty") - base) <= EPS) return l;
  return { ...l, _roSources: proposeSources(l._roSources, base) };
}

export const roLineValid = (l) => {
  const s = l._roSources || [];
  if (!s.length) return true;
  return baseQtyOf(l) > EPS && Math.abs(sum(s, "qty") - baseQtyOf(l)) <= 1e-4 && s.every((x) => n(x.qty) <= n(x.sisa) + EPS);
};

export const roPayloadSources = (l) => (l._roSources || []).filter((s) => n(s.qty) > EPS).map((s) => ({
  ro_id: s.ro_id, line_id: s.line_id, qty: n(s.qty), base_qty: n(s.qty), ...(s.ro_alloc_id ? { ro_alloc_id: s.ro_alloc_id } : {}),
}));

const spkText = (l) => [...new Set((l._roSources || []).filter((s) => n(s.qty) > EPS).flatMap((s) => String(s.spk_label || "Non-SPK").split(", ")))].join(", ") || "-";

/** Sel ringkas sumber (Alokasi SPK + tombol Lihat Rincian) untuk tabel item PO. */
export function PoSourceCell({ line, index, onDetail, children }) {
  const ok = roLineValid(line);
  return (
    <div className="flex items-center gap-1.5">
      <div className="min-w-0 flex-1">{children || <span className="block truncate text-xs text-muted-foreground" title={`Diwarisi dari sumber RO/MRO saat simpan: ${spkText(line)}`} data-testid={`po-alloc-inherit-${index}`}>{spkText(line)}</span>}</div>
      <Button type="button" variant={ok ? "ghost" : "destructive"} size="sm" className="h-8 shrink-0 px-2" onClick={onDetail} data-testid={`po-line-source-detail-${index}`} title={ok ? "Lihat Rincian sumber RO" : "Rincian belum seimbang dengan Qty PO"}>
        <ListTree className="mr-1 h-3.5 w-3.5" />Rincian
      </Button>
    </div>
  );
}

/** Rincian sumber per item PO: RO | MRO | SPK | Proyek | Unit/Aset | Qty RO Source | Sudah PO | Sisa | Qty ke PO. */
export function PoSourceDetailDialog({ line, onClose, onChange, readOnly, itemLabel }) {
  if (!line) return null;
  const s = line._roSources || [];
  const total = sum(s, "qty"), base = baseQtyOf(line), balanced = Math.abs(total - base) <= 1e-4;
  const setQty = (i, v) => {
    const next = s.map((x, k) => (k === i ? { ...x, qty: Math.max(0, n(v)) } : x));
    const t = +sum(next, "qty").toFixed(6);
    onChange({ ...line, _roSources: next, qty: +(t / factorOf(line)).toFixed(6) });
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto" data-testid="po-source-detail">
        <DialogHeader><DialogTitle className="font-head">Rincian Sumber RO — {itemLabel || line.item_code || ""}</DialogTitle></DialogHeader>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="p-2">RO</th><th className="p-2">MRO</th><th className="p-2">SPK</th><th className="p-2">Proyek</th><th className="p-2">Unit/Aset</th>
            <th className="p-2 text-right">Qty RO Source</th><th className="p-2 text-right">Sudah PO</th><th className="p-2 text-right">Sisa</th><th className="p-2 text-right w-36">Qty ke PO</th>
          </tr></thead><tbody>
            {s.map((x, i) => { const over = n(x.qty) > n(x.sisa) + EPS; return (
              <tr key={`${x.line_id}-${x.ro_alloc_id || i}`} className="border-t" data-testid={`po-source-detail-row-${i}`}>
                <td className="p-2 font-mono text-xs font-semibold">{x.ro_no || "-"}</td>
                <td className="p-2 font-mono text-xs">{x.mro_no || "-"}</td>
                <td className="p-2 text-xs">{x.spk_label || "Non-SPK"}</td><td className="p-2">{x.project_name || "-"}</td><td className="p-2">{x.unit_name || "-"}</td>
                <td className="p-2 text-right tabular-nums">{num(x.ro_source_qty)}</td><td className="p-2 text-right tabular-nums">{num(x.sudah_po)}</td><td className="p-2 text-right tabular-nums">{num(x.sisa)}</td>
                <td className="p-1.5 text-right">{readOnly ? <span className="font-semibold tabular-nums">{num(x.qty)}</span> : <><Input type="number" min="0" step="any" value={x.qty} onChange={(e) => setQty(i, e.target.value)} className={`h-8 text-right ${over ? "border-destructive ring-1 ring-destructive/40" : ""}`} aria-invalid={over || undefined} data-testid={`po-source-qty-${i}`} />{over && <div className="mt-0.5 text-[11px] text-destructive">Melebihi sisa</div>}</>}</td>
              </tr>); })}
          </tbody><tfoot><tr className="border-t bg-muted/40 font-semibold"><td className="p-2" colSpan={8}>Total Rincian {balanced ? "" : `(Qty PO ${num(base)})`}</td><td className={`p-2 text-right ${balanced ? "" : "text-destructive"}`} data-testid="po-source-detail-total">{num(total)} {line.base_unit || line.unit || ""}</td></tr></tfoot></table>
        </div>
        <p className="text-xs text-muted-foreground">Qty PO = total rincian sumber (satuan dasar). Mengubah Qty ke PO di sini ikut mengubah Qty PO. Sisa tiap sumber dihitung ulang server saat simpan.</p>
        <DialogFooter><Button onClick={onClose} data-testid="po-source-detail-close">Selesai</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const recKey = (r) => r.recommended_supplier?.supplier_id || MANUAL;
const searchText = (r) => [r.ro_no, r.item_code, r.item_name, r.division_name, r.primary_supplier_name, ...(r.mro_nos || []), r.spk_label,
  ...(r.contract_suppliers || []).map((c) => `${c.supplier_name} ${c.contract_number || ""}`)].join(" ").toLowerCase();

/** Tarik RO — kebutuhan RO dikelompokkan per rekomendasi supplier (Kontrak Aktif -> Supplier Utama -> Pilih Manual). */
export function PoRoPickerDialog({ open, onClose, divisionId, supplierId, onConfirm }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [sel, setSel] = useState({}); // line_id -> qty
  const [div, setDiv] = useState("");
  const [pickSupplier, setPickSupplier] = useState("");
  const load = () => { setLoading(true); setError(null); api.get("/pull/ro-for-po").then((r) => setRows(r.data || [])).catch((e) => setError(apiError(e.response?.data?.detail))).finally(() => setLoading(false)); };
  useEffect(() => { if (open) { setSel({}); setQ(""); setGroup(""); setDiv(divisionId || ""); setPickSupplier(""); load(); } }, [open, divisionId]); // eslint-disable-line react-hooks/exhaustive-deps
  const lockedDiv = divisionId || div;
  const shown = useMemo(() => rows.filter((r) => (!q || searchText(r).includes(q.toLowerCase())) && (!group || recKey(r) === group)), [rows, q, group]);
  const groups = useMemo(() => {
    const m = new Map();
    for (const r of shown) {
      const k = recKey(r);
      if (!m.has(k)) m.set(k, { key: k, name: r.recommended_supplier?.supplier_name || "Belum ada rekomendasi — Pilih Manual", source: r.recommended_supplier?.source || "Pilih Manual", rows: [] });
      m.get(k).rows.push(r);
    }
    return [...m.values()].sort((a, b) => (a.key === MANUAL) - (b.key === MANUAL) || a.name.localeCompare(b.name));
  }, [shown]);
  const groupOpts = useMemo(() => { const m = new Map(); rows.forEach((r) => m.set(recKey(r), r.recommended_supplier?.supplier_name || "Pilih Manual")); return [{ value: "", label: "Semua rekomendasi supplier" }, ...[...m].map(([value, label]) => ({ value, label }))]; }, [rows]);
  const blocked = (r) => lockedDiv && r.division_id !== lockedDiv;
  const toggle = (r) => {
    if (blocked(r)) return;
    if (!lockedDiv) setDiv(r.division_id || "");
    setSel((c) => { const x = { ...c }; if (x[r.line_id] != null) delete x[r.line_id]; else x[r.line_id] = n(r.outstanding_base); return x; });
  };
  const pickGroup = (g) => {
    const eligible = g.rows.filter((r) => !lockedDiv || r.division_id === lockedDiv);
    const d = lockedDiv || eligible[0]?.division_id || "";
    const x = {};
    eligible.filter((r) => r.division_id === d).forEach((r) => { x[r.line_id] = n(r.outstanding_base); });
    if (!Object.keys(x).length) return;
    setDiv(d); setSel(x);
    if (g.key !== MANUAL) setPickSupplier(g.key);
  };
  const picked = rows.filter((r) => sel[r.line_id] != null);
  const invalid = picked.some((r) => n(sel[r.line_id]) <= EPS || n(sel[r.line_id]) > n(r.outstanding_base) + EPS);
  const supName = (id) => rows.find((r) => recKey(r) === id)?.recommended_supplier?.supplier_name;
  const confirm = () => {
    if (!picked.length) return;
    if (invalid) { toast.error("Qty ke PO harus > 0 dan tidak melebihi Sisa PO."); return; }
    onConfirm(picked.map((r) => ({ ...r, _qty: n(sel[r.line_id]) })), pickSupplier || null);
    onClose();
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-[min(96vw,1500px)] max-h-[92vh] overflow-y-auto" data-testid="po-ro-picker">
        <DialogHeader><DialogTitle className="font-head">Tarik RO — Kebutuhan per Rekomendasi Supplier</DialogTitle></DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[280px] flex-1"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari No RO, barang, divisi, supplier utama, MRO, SPK…" className="pl-8" data-testid="po-ro-search" /></div>
          <div className="w-[280px]"><Combobox options={groupOpts} value={group} onChange={setGroup} placeholder="Filter rekomendasi supplier" testid="po-ro-group-filter" /></div>
        </div>
        <p className="text-xs text-muted-foreground">1 PO = 1 Divisi + 1 Supplier. Rekomendasi: Supplier Kontrak Aktif → Supplier Utama → Pilih Manual (bukan penguncian; supplier PO tetap bisa diganti).{lockedDiv ? ` Divisi PO: ${rows.find((r) => r.division_id === lockedDiv)?.division_name || "terpilih"}.` : ""}</p>
        {loading ? <div className="space-y-2" data-testid="po-ro-loading">{[0, 1, 2].map((i) => <div key={i} className="h-9 animate-pulse rounded bg-muted" />)}</div>
          : error ? <div className="rounded-md border border-destructive/40 p-4 text-sm" data-testid="po-ro-error">{error} <Button size="sm" variant="outline" className="ml-2" onClick={load}>Coba lagi</Button></div>
          : !groups.length ? <div className="rounded-md border p-6 text-center text-sm text-muted-foreground" data-testid="po-ro-empty">Tidak ada kebutuhan RO yang masih bisa di-PO-kan.</div>
          : groups.map((g) => (
            <section key={g.key} className="rounded-lg border" data-testid={`po-ro-group-${g.key === MANUAL ? "manual" : g.key}`}>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/40 px-3 py-2">
                <div className="flex items-center gap-2"><Users className="h-4 w-4 text-muted-foreground" /><span className="font-semibold">{g.name}</span><Badge variant="outline" className="text-[11px]">{g.source}</Badge><span className="text-xs text-muted-foreground">{g.rows.length} barang</span></div>
                <Button type="button" size="sm" variant="outline" onClick={() => pickGroup(g)} data-testid={`po-ro-group-pick-${g.key === MANUAL ? "manual" : g.key}`}>{g.key === MANUAL ? "Pilih semua di grup ini" : "Pilih grup & jadikan Supplier PO"}</Button>
              </div>
              <div className="overflow-x-auto"><table className="w-full min-w-[1350px] text-sm"><thead><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="w-10 p-2" /><th className="p-2">No RO</th><th className="p-2">Divisi</th><th className="p-2">Barang</th><th className="p-2 text-right">Qty RO</th><th className="p-2 text-right">Sudah PO</th><th className="p-2 text-right">Sisa PO</th><th className="p-2">Satuan</th><th className="p-2">Supplier Utama</th><th className="p-2">Supplier Kontrak</th><th className="p-2">MRO Sumber</th><th className="p-2">Alokasi SPK</th><th className="w-32 p-2 text-right">Qty ke PO</th>
              </tr></thead><tbody>
                {g.rows.map((r) => { const on = sel[r.line_id] != null; const dis = blocked(r); const v = sel[r.line_id]; const over = on && (n(v) > n(r.outstanding_base) + EPS || n(v) <= EPS); return (
                  <tr key={r.line_id} className={`border-t ${on ? "bg-primary/5" : ""} ${dis ? "opacity-50" : ""}`} data-testid={`po-ro-row-${r.ro_no}-${r.item_code}`}>
                    <td className="p-2"><Checkbox checked={on} disabled={dis} onCheckedChange={() => toggle(r)} aria-label={`Pilih ${r.item_name}`} data-testid={`po-ro-select-${r.ro_no}-${r.item_code}`} /></td>
                    <td className="p-2 font-mono text-xs font-semibold">{r.ro_no}</td><td className="p-2">{r.division_name || "-"}</td>
                    <td className="p-2"><div className="font-medium">{r.item_name}</div><div className="font-mono text-xs text-muted-foreground">{r.item_code}</div></td>
                    <td className="p-2 text-right tabular-nums">{num(r.qty_ro_base)}</td><td className="p-2 text-right tabular-nums">{num(r.ordered_base)}</td><td className="p-2 text-right font-semibold tabular-nums">{num(r.outstanding_base)}</td>
                    <td className="p-2">{r.base_unit}</td><td className="p-2">{r.primary_supplier_name || "-"}</td>
                    <td className="p-2 text-xs">{(r.contract_suppliers || []).map((c) => <div key={c.supplier_id}>{c.supplier_name}{c.contract_number ? ` · ${c.contract_number}` : ""}</div>)}{!(r.contract_suppliers || []).length && "-"}</td>
                    <td className="p-2 font-mono text-xs">{(r.mro_nos || []).join(", ") || "-"}</td><td className="p-2 text-xs">{r.spk_label || "-"}</td>
                    <td className="p-1.5 text-right">{on ? <Input type="number" min="0" step="any" value={v} onChange={(e) => setSel((c) => ({ ...c, [r.line_id]: e.target.value }))} className={`h-8 text-right ${over ? "border-destructive ring-1 ring-destructive/40" : ""}`} aria-invalid={over || undefined} data-testid={`po-ro-qty-${r.ro_no}-${r.item_code}`} /> : <span className="text-xs text-muted-foreground">{dis ? "Divisi lain" : "-"}</span>}</td>
                  </tr>); })}
              </tbody></table></div>
            </section>
          ))}
        <DialogFooter className="flex-wrap items-center gap-2 sm:justify-between">
          <span className="text-sm text-muted-foreground" data-testid="po-ro-picked-summary">{picked.length} barang dipilih{pickSupplier ? ` · Supplier PO: ${supName(pickSupplier)}` : supplierId ? " · Supplier PO tetap" : ""}</span>
          <div className="flex gap-2"><Button variant="outline" onClick={onClose}>Batal</Button><Button onClick={confirm} disabled={!picked.length || invalid} data-testid="po-ro-confirm">Tambahkan ke PO</Button></div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
