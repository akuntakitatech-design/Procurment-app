import { useEffect, useRef } from "react";
import { Combobox } from "@/components/Combobox";
import { MasterProjectCombobox, MasterUnitCombobox } from "@/components/MasterRefCombobox";
import { inlinePrefill } from "@/lib/masterInline";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { NumericInput } from "@/components/NumericInput";
import { QtyStock } from "@/components/StockInfo";
import { ItemPicker } from "@/components/ItemPicker";
import { Plus, Trash2 } from "lucide-react";
import { num } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isManual, loanIssueMessages as issueMessages, nameOnlyOptions, newLoanLine, propagateDefaults, setLineField } from "@/lib/loanLines";

// Detail Pinjam Barang: setiap baris punya Project, Gudang Pemberi, Gudang Peminjam & Unit/Aset sendiri.
// Khusus Pinjam Barang — komponen ItemLines bersama dan komponen Transfer tidak diubah.
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

export function LoanItemLines({ lines, onChange, masters, defaults, issues = [], stockOf = () => null, division = null, testidPrefix = "loan" }) {
  const items = masters.map("items");
  const uoms = masters.map("uoms");
  const linesRef = useRef(lines);
  const onChangeRef = useRef(onChange);
  const prev = useRef(defaults);
  linesRef.current = lines;
  onChangeRef.current = onChange;

  // Default header berubah -> hanya field berstatus "Default" yang ikut; field "Manual" dipertahankan.
  useEffect(() => {
    const { next, dirty } = propagateDefaults(linesRef.current, prev.current, defaults);
    if (dirty) onChangeRef.current(next);
    prev.current = defaults;
  }, [defaults.project_id, defaults.from_warehouse_id, defaults.to_warehouse_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const whOpts = nameOnlyOptions(masters.data.warehouses, (d) => (d.location ? ` · ${d.location}` : ""));
  const projOpts = nameOnlyOptions(masters.data.projects, (d) => (d.pic ? ` · PIC ${d.pic}` : ""));
  const unitOpts = (masters.data.units || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.plate_no ? ` (${d.plate_no})` : ""}`, selectedLabel: d.plate_no || d.name }));
  const whName = (id) => (masters.data.warehouses || []).find((w) => w.id === id)?.name || "";
  const uomLabel = (id) => { const u = uoms[id]; return u ? (u.symbol || u.name || u.code) : ""; };
  const itemUoms = (id) => {
    const it = items[id]; if (!it) return [];
    if (!it.base_uom_id) return it.unit ? [{ value: `legacy:${it.unit}`, label: it.unit, selectedLabel: it.unit, factor: 1, unit: it.unit }] : [];
    const rows = [{ uom_id: it.base_uom_id, factor: 1, is_base: true }, ...(it.uoms || []).filter((x) => x.uom_id !== it.base_uom_id)];
    const seen = new Set();
    return rows.filter((r) => r.uom_id && !seen.has(r.uom_id) && seen.add(r.uom_id)).map((r) => {
      const u = uoms[r.uom_id] || {}; const short = u.symbol || u.name || u.code || "Satuan";
      return { value: r.uom_id, label: `${u.name || u.code || "Satuan"}${u.symbol ? ` (${u.symbol})` : ""}${r.is_base ? " — Dasar" : ` — 1 = ${num(r.factor)} ${uomLabel(it.base_uom_id)}`}`, selectedLabel: short, factor: Number(r.factor) || 1, unit: short };
    });
  };
  const baseUnit = (id) => { const it = items[id]; return it ? (it.base_uom_id ? uomLabel(it.base_uom_id) : it.unit || "") : ""; };

  const update = (i, patch) => {
    const next = [...lines]; let cur = { ...next[i] };
    if (patch.item_id !== undefined) {
      const it = items[patch.item_id]; const base = it?.base_uom_id || "";
      cur = { ...cur, item_id: patch.item_id, uom_id: base, conversion_factor: 1, unit: base ? uomLabel(base) : (it?.unit || "") };
    } else if (patch.uom_id !== undefined) {
      const pick = itemUoms(cur.item_id).find((x) => x.value === patch.uom_id);
      cur = { ...cur, uom_id: patch.uom_id, conversion_factor: Number(pick?.factor) || 1, unit: pick?.unit || cur.unit };
    } else {
      Object.entries(patch).forEach(([k, v]) => { cur = setLineField(cur, k, v); });
    }
    next[i] = cur;
    onChange(next);
  };
  const addRow = () => onChange([...lines, newLoanLine(defaults)]);
  const unitPrefill = () => inlinePrefill("units", { division_id: division });

  return (
    <div className="space-y-3" data-testid={`${testidPrefix}-lines`}>
      <div className="flex items-center justify-between">
        <div className="font-head text-sm font-semibold">Detail Barang <span className="ml-1 text-xs font-normal text-muted-foreground">({lines.length} baris)</span></div>
      </div>
      {lines.length === 0 && (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground" data-testid={`${testidPrefix}-lines-empty`}>
          Belum ada barang. Klik <b>Tambah Baris</b> — baris baru otomatis memakai Project, Gudang Pemberi & Gudang Peminjam Default.
        </div>
      )}
      {lines.map((l, i) => {
        const iss = issues[i] || null; const msgs = issueMessages(iss);
        const avail = stockOf(l.item_id, l.from_warehouse_id);
        const unit = baseUnit(l.item_id);
        return (
          <div key={l._key || l.id || i} className={cn("rounded-lg border bg-card p-3 shadow-sm", msgs.length && "border-destructive/40")} data-testid={`${testidPrefix}-line-${i}`}>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-12">
              <div className="md:col-span-4"><LineField label={<><span className="mr-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded bg-primary/10 px-1 text-[10px] text-primary">{i + 1}</span>Barang</>}>
                <ItemPicker items={masters.data.items || []} lookup={masters.status?.("items")} uoms={uoms} value={l.item_id} onChange={(v) => update(i, { item_id: v })} warehouseId={l.from_warehouse_id} testid={`${testidPrefix}-item-${i}`} fallbackLabel={l.item_name || ""} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Keterangan"><Input value={l.notes || ""} onChange={(e) => update(i, { notes: e.target.value })} className="h-9" placeholder="Keterangan item" data-testid={`${testidPrefix}-notes-${i}`} /></LineField></div>
              <div className="md:col-span-2"><LineField label="Qty">
                <QtyStock itemId={l.item_id} warehouseId={l.from_warehouse_id} itemName={items[l.item_id]?.name} value={avail ?? undefined} testid={`${testidPrefix}-stock-${i}`}>
                  <NumericInput mode="quantity" value={l.qty} onChange={(v) => update(i, { qty: v })} className={cn("h-9 text-right", (iss?.qty || iss?.stock) && "border-destructive ring-1 ring-destructive")} data-testid={`${testidPrefix}-qty-${i}`} aria-invalid={!!(iss?.qty || iss?.stock) || undefined} />
                </QtyStock>
              </LineField></div>
              <div className="md:col-span-2"><LineField label="Satuan">
                <Combobox dense testid={`${testidPrefix}-uom-${i}`} options={itemUoms(l.item_id)} lookup={masters.status?.("uoms")} value={l.uom_id || items[l.item_id]?.base_uom_id || ""} onChange={(v) => update(i, { uom_id: v })} placeholder="Satuan" disabled={!l.item_id || itemUoms(l.item_id).length <= 1} />
              </LineField></div>
              <div className="flex items-end justify-end md:col-span-1">
                <Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => onChange(lines.filter((_, x) => x !== i))} aria-label={`Hapus baris ${i + 1}`} data-testid={`${testidPrefix}-remove-${i}`}><Trash2 className="h-4 w-4 text-destructive" /></Button>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-3 rounded-md bg-muted/40 p-2.5 md:grid-cols-12">
              <div className="md:col-span-3"><LineField label="Gudang Pemberi" tag={<SourceTag manual={isManual(l, "from_warehouse_id")} testid={`${testidPrefix}-from-state-${i}`} />}>
                <Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={l.from_warehouse_id || ""} onChange={(v) => update(i, { from_warehouse_id: v })} placeholder="Pilih gudang pemberi" invalid={!!(iss?.from || iss?.same || iss?.stock)} testid={`${testidPrefix}-from-${i}`} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Gudang Peminjam" tag={<SourceTag manual={isManual(l, "to_warehouse_id")} testid={`${testidPrefix}-to-state-${i}`} />}>
                <Combobox options={whOpts} lookup={masters.status?.("warehouses")} value={l.to_warehouse_id || ""} onChange={(v) => update(i, { to_warehouse_id: v })} placeholder="Pilih gudang peminjam" invalid={!!(iss?.to || iss?.same)} testid={`${testidPrefix}-to-${i}`} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Project" tag={<SourceTag manual={isManual(l, "project_id")} testid={`${testidPrefix}-project-state-${i}`} />}>
                <MasterProjectCombobox masters={masters} options={projOpts} value={l.project_id || ""} onChange={(v) => update(i, { project_id: v })} placeholder="Pilih project" testid={`${testidPrefix}-project-${i}`} />
              </LineField></div>
              <div className="md:col-span-3"><LineField label="Unit/Aset">
                <MasterUnitCombobox masters={masters} options={unitOpts} value={l.unit_id || ""} onChange={(v) => update(i, { unit_id: v })} placeholder="Opsional" prefill={unitPrefill} testid={`${testidPrefix}-unit-${i}`} />
              </LineField></div>
              <div className="text-xs text-muted-foreground md:col-span-12" data-testid={`${testidPrefix}-available-${i}`}>
                {!l.item_id || !l.from_warehouse_id ? "Pilih barang & gudang pemberi untuk melihat stok tersedia."
                  : avail == null ? `Memuat stok di ${whName(l.from_warehouse_id) || "gudang pemberi"}...`
                  : <>Stok tersedia di <b className="text-foreground">{whName(l.from_warehouse_id)}</b>: <b className={cn("tabular-nums", avail > 0 ? "text-emerald-700" : "text-destructive")}>{num(avail)}</b> {unit}</>}
              </div>
            </div>
            {msgs.length > 0 && <div role="alert" className="mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1 text-xs font-medium text-destructive" data-testid={`${testidPrefix}-line-error-${i}`}>Baris {i + 1}: {msgs.join(" · ")}</div>}
          </div>
        );
      })}
      <Button variant="outline" size="sm" onClick={addRow} data-testid={`${testidPrefix}-add-line`}><Plus className="mr-2 h-4 w-4" />Tambah Baris</Button>
    </div>
  );
}
