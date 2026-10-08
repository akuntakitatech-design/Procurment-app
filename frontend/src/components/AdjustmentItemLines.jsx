import { useEffect, useRef } from "react";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox, MasterUnitCombobox } from "@/components/MasterRefCombobox";
import { inlinePrefill } from "@/lib/masterInline";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { QtyStock } from "@/components/StockInfo";
import { ItemPicker } from "@/components/ItemPicker";
import { Plus, Trash2, ArrowRight } from "lucide-react";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";
import { adjustmentSelectedUnitLabel } from "@/lib/txnValidation";
import { adjIssueMessages, baseDelta, isManual, newAdjLine, propagateDefaults, setLineField } from "@/lib/adjustmentLines";

// Detail Penyesuaian Stok: setiap baris punya Gudang, Project & Unit/Aset sendiri (sumber stok/ledger/valuasi).
// Khusus Penyesuaian Stok — komponen ItemLines bersama dan komponen Transfer/Pinjam tidak diubah.
function SourceTag({ manual, testid }) {
  return (
    <span data-testid={testid} title={manual ? "Diubah manual pada baris ini — tidak ikut berubah saat default header diganti" : "Mengikuti default header"}
      className={cn("rounded px-1.5 py-px text-[10px] font-medium normal-case tracking-normal", manual ? "bg-amber-100 text-amber-800" : "bg-muted text-muted-foreground")}>
      {manual ? "Manual" : "Default"}
    </span>
  );
}

function LineField({ label, tag, children }) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}{tag}</div>
      {children}
    </div>
  );
}

const nameOpts = (rows, extra = () => "") => (rows || []).map((d) => ({ value: d.id, label: `${d.name}${extra(d)}`, selectedLabel: d.name }));

export function AdjustmentItemLines({ lines, onChange, masters, defaults, issues = [], stockOf = () => null, canPrice = false, division = null, testidPrefix = "adj" }) {
  const items = masters.map("items");
  const uoms = masters.map("uoms");
  const linesRef = useRef(lines); const onChangeRef = useRef(onChange); const prev = useRef(defaults);
  linesRef.current = lines; onChangeRef.current = onChange;

  // Default header berubah -> hanya field berstatus "Default" yang ikut; field "Manual" dipertahankan.
  useEffect(() => {
    const { next, dirty } = propagateDefaults(linesRef.current, prev.current, defaults);
    if (dirty) onChangeRef.current(next);
    prev.current = defaults;
  }, [defaults.warehouse_id, defaults.project_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const whOpts = nameOpts(masters.data.warehouses, (d) => (d.location ? ` · ${d.location}` : ""));
  const projOpts = nameOpts(masters.data.projects, (d) => (d.pic ? ` · PIC ${d.pic}` : ""));
  const unitOpts = (masters.data.units || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.plate_no ? ` (${d.plate_no})` : ""}`, selectedLabel: d.plate_no || d.name }));
  const whName = (id) => (masters.data.warehouses || []).find((w) => w.id === id)?.name || "";
  const uomLabel = (id) => { const u = uoms[id]; return u ? (u.symbol || u.name || u.code) : ""; };
  const itemUoms = (id) => {
    const it = items[id]; if (!it) return [];
    if (!it.base_uom_id) return it.unit ? [{ value: `legacy:${it.unit}`, label: it.unit, selectedLabel: it.unit, factor: 1 }] : [];
    const seen = new Set();
    return [{ uom_id: it.base_uom_id, factor: 1, is_base: true }, ...(it.uoms || [])].filter((r) => r.uom_id && !seen.has(r.uom_id) && seen.add(r.uom_id)).map((r) => {
      const u = uoms[r.uom_id] || {};
      // Label dropdown: kode · nama + konversi (cari via kode/nama); terpilih: nama saja (perilaku existing).
      return { value: r.uom_id, factor: Number(r.factor) || 1, selectedLabel: adjustmentSelectedUnitLabel(u) || "Satuan", label: `${u.code && u.name && u.code !== u.name ? `${u.code} · ` : ""}${u.name || u.code || "Satuan"}${u.symbol ? ` (${u.symbol})` : ""}${r.is_base ? " — Dasar" : ` — 1 = ${num(r.factor)} ${uomLabel(it.base_uom_id)}`}` };
    });
  };
  const baseUnit = (id) => { const it = items[id]; return it ? (it.base_uom_id ? uomLabel(it.base_uom_id) : it.unit || "") : ""; };

  const update = (i, patch) => {
    const next = [...lines]; let cur = { ...next[i] };
    if (patch.item_id !== undefined) cur = { ...cur, item_id: patch.item_id, uom_id: items[patch.item_id]?.base_uom_id || "", conversion_factor: 1 };
    else if (patch.uom_id !== undefined) { const pick = itemUoms(cur.item_id).find((x) => x.value === patch.uom_id); cur = { ...cur, uom_id: patch.uom_id, conversion_factor: Number(pick?.factor) || 1 }; }
    else Object.entries(patch).forEach(([k, v]) => { cur = setLineField(cur, k, v); });
    next[i] = cur; onChange(next);
  };
  const unitPrefill = () => inlinePrefill("units", { division_id: division });

  return (
    <div className="space-y-3" data-testid={`${testidPrefix}-lines`}>
      <div className="font-head text-sm font-semibold">Detail Barang <span className="ml-1 text-xs font-normal text-muted-foreground">({lines.length} baris)</span></div>
      {lines.length === 0 && <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground" data-testid={`${testidPrefix}-lines-empty`}>Belum ada barang. Klik <b>Tambah Baris</b> — baris baru otomatis memakai Gudang & Project Default.</div>}
      {lines.map((l, i) => {
        const iss = issues[i] || null; const msgs = adjIssueMessages(iss);
        const avail = stockOf(l.item_id, l.warehouse_id); const unit = baseUnit(l.item_id); const d = baseDelta(l);
        return (
          <div key={l._key || i} className={cn("rounded-lg border bg-card p-3 shadow-sm", msgs.length && "border-destructive/40")} data-testid={`${testidPrefix}-line-${i}`}>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-12">
              <div className="md:col-span-4"><LineField label={<><span className="mr-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded bg-primary/10 px-1 text-[10px] text-primary">{i + 1}</span>Barang</>}>
                <ItemPicker items={masters.data.items || []} lookup={masters.status?.("items")} uoms={uoms} value={l.item_id} onChange={(v) => update(i, { item_id: v })} warehouseId={l.warehouse_id} testid={`${testidPrefix}-item-${i}`} />
              </LineField></div>
              <div className="md:col-span-2"><LineField label="Qty (+/−)">
                <QtyStock itemId={l.item_id} warehouseId={l.warehouse_id} itemName={items[l.item_id]?.name} value={avail ?? undefined} testid={`${testidPrefix}-stock-${i}`} badgeClass="right-6">
                  <Input type="number" step="any" value={l.adjustment} onChange={(e) => update(i, { adjustment: e.target.value })} className={cn("h-9 text-right", (iss?.qty || iss?.stock) && "border-destructive ring-1 ring-destructive")} data-testid={`${testidPrefix}-qty-${i}`} aria-invalid={!!(iss?.qty || iss?.stock) || undefined} title="Positif = tambah stok, negatif = kurangi stok" />
                </QtyStock>
              </LineField></div>
              <div className="md:col-span-2"><LineField label="Satuan">
                <Combobox dense testid={`${testidPrefix}-uom-${i}`} options={itemUoms(l.item_id)} value={l.uom_id || items[l.item_id]?.base_uom_id || ""} onChange={(v) => update(i, { uom_id: v })} placeholder="Satuan" disabled={!l.item_id || itemUoms(l.item_id).length <= 1} />
              </LineField></div>
              {canPrice ? <div className="md:col-span-2"><LineField label="Biaya Satuan (Masuk)">
                {d > 0 ? <Input type="number" step="any" min="0" value={l.approved_unit_cost} onChange={(e) => update(i, { approved_unit_cost: e.target.value })} className="h-9 text-right" placeholder="rata-rata" data-testid={`${testidPrefix}-cost-${i}`} title="Kosongkan = pakai rata-rata gudang baris. Beda nilai wajib alasan." /> : <div className="flex h-9 items-center text-xs text-muted-foreground">— (hanya qty +)</div>}
              </LineField></div> : <div className="hidden md:col-span-2 md:block" />}
              <div className="flex items-end justify-end md:col-span-2">
                <Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => onChange(lines.filter((_, x) => x !== i))} aria-label={`Hapus baris ${i + 1}`} data-testid={`${testidPrefix}-remove-${i}`}><Trash2 className="h-4 w-4 text-destructive" /></Button>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-3 rounded-md bg-muted/40 p-2.5 md:grid-cols-12">
              <div className="md:col-span-3"><LineField label="Gudang" tag={<SourceTag manual={isManual(l, "warehouse_id")} testid={`${testidPrefix}-warehouse-state-${i}`} />}>
                <Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={l.warehouse_id || ""} onChange={(v) => update(i, { warehouse_id: v })} placeholder="Pilih gudang" invalid={!!(iss?.warehouse || iss?.stock)} testid={`${testidPrefix}-warehouse-${i}`} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Project" tag={<SourceTag manual={isManual(l, "project_id")} testid={`${testidPrefix}-project-state-${i}`} />}>
                <MasterProjectCombobox masters={masters} options={projOpts} value={l.project_id || ""} onChange={(v) => update(i, { project_id: v })} placeholder="Opsional" testid={`${testidPrefix}-project-${i}`} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Unit/Aset">
                <MasterUnitCombobox masters={masters} options={unitOpts} value={l.unit_id || ""} onChange={(v) => update(i, { unit_id: v })} placeholder="Opsional" prefill={unitPrefill} testid={`${testidPrefix}-unit-${i}`} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Alasan"><Input value={l.reason || ""} onChange={(e) => update(i, { reason: e.target.value })} className="h-9" placeholder="Alasan per barang" data-testid={`${testidPrefix}-reason-${i}`} /></LineField></div>
              <div className="text-xs text-muted-foreground md:col-span-12" data-testid={`${testidPrefix}-before-after-${i}`}>
                {!l.item_id || !l.warehouse_id ? "Pilih barang & gudang untuk melihat stok sebelum/sesudah."
                  : iss?.before == null ? `Memuat stok di ${whName(l.warehouse_id) || "gudang"}...`
                  : <>Stok di <b className="text-foreground">{whName(l.warehouse_id)}</b>: <b className="tabular-nums text-foreground">{num(iss.before)}</b> <ArrowRight className="inline h-3 w-3" /> <b className={cn("tabular-nums", iss.after < 0 ? "text-destructive" : "text-emerald-700")}>{num(iss.after)}</b> {unit}</>}
              </div>
            </div>
            {msgs.length > 0 && <div role="alert" className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs font-medium text-destructive" data-testid={`${testidPrefix}-line-error-${i}`}>Baris {i + 1}: {msgs.join(" · ")}</div>}
          </div>
        );
      })}
      <Button variant="outline" size="sm" onClick={() => onChange([...lines, newAdjLine(defaults)])} data-testid={`${testidPrefix}-add-line`}><Plus className="mr-2 h-4 w-4" />Tambah Baris</Button>
    </div>
  );
}
