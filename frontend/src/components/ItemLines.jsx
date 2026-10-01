import { useEffect, useRef } from "react";
import { Combobox } from "@/components/Combobox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Plus, Trash2 } from "lucide-react";
import { rupiah, num } from "@/lib/format";
import { computePriceStatus, StatusBadgePrice } from "@/components/PoPriceControl";

export function ItemLines({ lines, onChange, masters, fields = {}, showPrice = false, defaults = {}, taxInclusive = false, allocationColumn = null, priceAccessory = null, poControl = null }) {
  const items = masters.map("items");
  const uoms = masters.map("uoms");
  const taxes = masters.map("taxes");
  const prev = useRef({ warehouse_id: "", project_id: "", unit_id: "" });
  const linesRef = useRef(lines);
  const onChangeRef = useRef(onChange);
  linesRef.current = lines;
  onChangeRef.current = onChange;

  useEffect(() => {
    const lines = linesRef.current;
    const onChange = onChangeRef.current;
    const now = { warehouse_id: defaults.warehouse_id || "", project_id: defaults.project_id || "", unit_id: defaults.unit_id || "" };
    const old = prev.current;
    const keys = Object.keys(now).filter((k) => now[k] !== old[k]);
    if (keys.length && lines.length) {
      let dirty = false;
      const next = lines.map((l) => {
        const x = { ...l };
        keys.forEach((k) => {
          const flag = k === "warehouse_id" ? "_warehouseOverride" : k === "project_id" ? "_projectOverride" : "_unitOverride";
          const cur = x[k] || "";
          if (!x[flag] && (!cur || cur === (old[k] || ""))) {
            if (cur !== now[k]) dirty = true;
            x[k] = now[k];
          }
        });
        return x;
      });
      if (dirty) onChange(next);
    }
    prev.current = now;
  }, [defaults.warehouse_id, defaults.project_id, defaults.unit_id]);

  const itemOpts = (masters.data.items || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.brand ? ` · ${d.brand}` : ""}${d.part_number ? ` · PN ${d.part_number}` : ""}`, selectedLabel: d.name }));
  const whOpts = (masters.data.warehouses || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.location ? ` · ${d.location}` : ""}`, selectedLabel: d.name }));
  const projOpts = (masters.data.projects || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.pic ? ` · PIC ${d.pic}` : ""}`, selectedLabel: d.name }));
  const unitOpts = (masters.data.units || []).map((d) => ({ value: d.id, label: `${d.code ? d.code + " — " : ""}${d.name}${d.plate_no ? ` (${d.plate_no})` : ""}${d.asset_no ? ` · Asset ${d.asset_no}` : ""}`, selectedLabel: d.plate_no || d.name }));
  const taxOpts = [{ value: "", label: "Tanpa Pajak", selectedLabel: "Tanpa Pajak" }, ...(masters.data.taxes || []).map((d) => ({ value: d.id, label: `${d.name} (${num(d.rate)}%)`, selectedLabel: d.name }))];
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
  const patchSources = (l, baseQty) => {
    if (!(l.sources || []).length) return l.sources;
    const total = l.sources.reduce((s, x) => s + Number(x.base_qty ?? x.qty ?? 0), 0);
    return l.sources.map((x) => ({ ...x, base_qty: l.sources.length === 1 ? baseQty : (total > 0 ? baseQty * Number(x.base_qty ?? x.qty ?? 0) / total : baseQty / l.sources.length) }));
  };
  const update = (i, patch) => {
    const next = [...lines]; const cur = { ...next[i] };
    if (patch.item_id) {
      const it = items[patch.item_id]; const base = it?.base_uom_id || "";
      next[i] = { ...cur, ...patch, uom_id: base, conversion_factor: 1, unit: base ? uomLabel(base) : (it?.unit || "") };
    } else if (patch.uom_id !== undefined) {
      const pick = itemUoms(cur.item_id).find((x) => x.value === patch.uom_id); const oldF = Number(cur.conversion_factor) || 1; const newF = Number(pick?.factor) || 1;
      const preserve = cur._locked || (cur.sources || []).length || cur.mro_line_id || cur.po_line_id; const oldQ = Number(cur.qty) || 0; const qty = preserve ? oldQ * oldF / newF : oldQ;
      next[i] = { ...cur, uom_id: patch.uom_id, conversion_factor: newF, unit: pick?.unit || cur.unit, qty, sources: patchSources(cur, qty * newF) };
    } else if (patch.tax_id !== undefined) {
      const t = patch.tax_id ? taxes[patch.tax_id] : null;
      next[i] = { ...cur, tax_id: patch.tax_id || "", tax: Number(t?.rate) || 0, tax_name: t?.name || null };
    } else {
      const x = { ...cur, ...patch };
      if (patch.warehouse_id !== undefined) x._warehouseOverride = true;
      if (patch.project_id !== undefined) x._projectOverride = true;
      if (patch.unit_id !== undefined) x._unitOverride = true;
      if (patch.qty !== undefined) x.sources = patchSources(x, (Number(patch.qty) || 0) * (Number(x.conversion_factor) || 1));
      next[i] = x;
    }
    onChange(next);
  };
  const addRow = () => onChange([...lines, { _key: (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `tmp-${Date.now()}-${Math.random().toString(36).slice(2)}`), item_id: "", qty: 1, uom_id: "", conversion_factor: 1, unit: "", warehouse_id: defaults.warehouse_id || "", project_id: defaults.project_id || "", unit_id: defaults.unit_id || "", _warehouseOverride: false, _projectOverride: false, _unitOverride: false, notes: "", price: 0, discount: 0, tax_id: "", tax: 0 }]);
  const total = (l) => { const base = (Number(l.qty) || 0) * (Number(l.price) || 0) - (Number(l.discount) || 0); return taxInclusive ? Math.max(0, base) : base + base * (Number(l.tax) || 0) / 100; };
  const grand = lines.reduce((s, l) => s + total(l), 0);
  const stockInfo = (l) => { const it = items[l.item_id]; if (!it) return ""; const base = it.base_uom_id ? uomLabel(it.base_uom_id) : it.unit; return base ? `${num((Number(l.qty) || 0) * (Number(l.conversion_factor) || 1))} ${base}` : ""; };
  const Uom = ({ l, i }) => <div><Combobox options={itemUoms(l.item_id)} value={l.uom_id || items[l.item_id]?.base_uom_id || ""} onChange={(v) => update(i, { uom_id: v })} placeholder="Satuan" disabled={!l.item_id || itemUoms(l.item_id).length <= 1} />{l.item_id && <div className="mt-1 text-[10px] text-muted-foreground">Terhitung stok: {stockInfo(l)}</div>}</div>;

  // Total rendered columns (keeps empty-row / grand-total colSpans correct).
  const colCount = 4 + (allocationColumn ? 1 : 0) + (fields.warehouse ? 1 : 0) + (fields.project ? 1 : 0) + (fields.unit ? 1 : 0) + (showPrice ? 4 : 0) + 1;

  // ---- PO two-row block layout (CP5A PO Item UX). PO-only; other docs keep the table below. ----
  if (poControl) {
    const fmtPct = (p) => `${p >= 0 ? "+" : ""}${Number(p).toFixed(2).replace(".", ",")}%`;
    const fmtRp = (v) => `${v >= 0 ? "+" : "-"}${rupiah(Math.abs(v))}`;
    return <div className="space-y-3">
      <div className="overflow-x-auto rounded-md border bg-card shadow-sm">
        <div className="min-w-[1540px]">
          <div className="flex items-stretch gap-2 border-b bg-muted px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <div className="w-[240px]">Barang &amp; Keterangan</div><div className="w-[120px]">Qty / Sat</div><div className="w-[140px]">Harga Kontrak</div><div className="w-[185px]">Harga Satuan</div><div className="w-[180px]">Selisih</div><div className="w-[160px] text-right">Total</div><div className="w-[130px]">Status</div><div className="w-[44px]"></div>
          </div>
          {lines.length === 0 && <div className="p-6 text-center text-sm text-muted-foreground">Belum ada item</div>}
          {lines.map((l, i) => {
            const c = poControl.contractOf(i);
            const hasC = !!(c && c.found && Number(c.contract_price) > 0);
            const priceNum = Number(l.price) || 0;
            const r = computePriceStatus(c, priceNum);
            const showVar = hasC && priceNum > 0;
            let status = r.status;
            if (hasC && !(priceNum > 0)) status = "Belum dihitung";
            const priceDiff = hasC && priceNum > 0 && Math.abs(priceNum - Number(c.contract_price)) > 0.5;
            return <div key={i} className="border-b px-3 py-2.5 last:border-b-0" data-testid={`po-item-block-${i}`}>
              <div className="flex items-start gap-2">
                <div className="w-[240px]">{l._sourceLabel && <div className="mb-1 text-[10px] font-mono text-muted-foreground">{l._sourceLabel}</div>}<Combobox options={itemOpts} value={l.item_id} onChange={(v) => update(i, { item_id: v })} placeholder="Pilih barang" disabled={l._locked} /><Input value={l.notes || ""} onChange={(e) => update(i, { notes: e.target.value })} className="mt-1 h-8 text-xs" placeholder="Keterangan" /></div>
                <div className="w-[120px]"><Input type="number" step="any" value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} className="h-9 text-right" /><div className="mt-1"><Uom l={l} i={i} /></div></div>
                <div className="w-[140px] pt-2 text-sm">{hasC ? <span className="font-semibold tabular-nums" title={`Kontrak ${c.contract_number || ""}${c.tolerance_pct != null ? ` · toleransi ${c.tolerance_pct}%` : ""}${c.effective_start ? ` · ${c.effective_start}${c.effective_end ? "–" + c.effective_end : ""}` : ""}`}>{rupiah(Number(c.contract_price))}</span> : <span className="text-xs text-muted-foreground">Tidak ada kontrak</span>}</div>
                <div className="w-[185px]"><Input type="number" value={l.price || 0} onChange={(e) => update(i, { price: e.target.value, _priceTouched: true, _priceAuto: false })} className="h-9 text-right" data-testid={`po-price-input-${i}`} />{poControl.history && <div className="mt-0.5">{poControl.history(l, i)}</div>}</div>
                <div className="w-[180px] pt-2 text-xs tabular-nums" data-testid={`po-variance-${i}`}>{showVar ? <span className={r.varRp > 0 ? "text-amber-700" : r.varRp < 0 ? "text-emerald-700" : "text-muted-foreground"}>{fmtRp(r.varRp)} / {fmtPct(r.varPct)}</span> : <span className="text-muted-foreground">—</span>}</div>
                <div className="w-[160px] pt-2 text-right text-sm font-medium tabular-nums">{rupiah(total(l))}</div>
                <div className="w-[130px] pt-1.5">{status === "Belum dihitung" ? <span data-testid={`po-status-${i}`} className="inline-flex items-center rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">Belum dihitung</span> : <StatusBadgePrice status={status} testid={`po-status-${i}`} />}</div>
                <div className="w-[44px] pt-1"><Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => onChange(lines.filter((_, x) => x !== i))}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>
              </div>
              <div className="mt-2 flex items-start gap-2 text-xs">
                <div className="w-[200px] pt-1.5 font-mono text-[11px] text-muted-foreground" data-testid={`po-source-${i}`}>{poControl.sourceText && poControl.sourceText(l) ? poControl.sourceText(l) : <span className="italic">—</span>}</div>
                <div className="w-[300px]">{allocationColumn ? allocationColumn.render(l, i) : null}</div>
                <div className="w-[150px]"><Combobox options={whOpts} value={l.warehouse_id || ""} onChange={(v) => update(i, { warehouse_id: v })} placeholder="Gudang" /></div>
                <div className="w-[150px]"><Combobox options={projOpts} value={l.project_id || ""} onChange={(v) => update(i, { project_id: v })} placeholder="Proyek" /></div>
                <div className="w-[150px]"><Combobox options={unitOpts} value={l.unit_id || ""} onChange={(v) => update(i, { unit_id: v })} placeholder="Unit/Aset" /></div>
                <div className="w-[150px]"><Combobox options={taxOpts} value={l.tax_id || ""} onChange={(v) => update(i, { tax_id: v })} /></div>
              </div>
              {priceDiff && <div className="mt-2 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/70 px-2 py-1.5"><span className="whitespace-nowrap text-[11px] font-semibold text-amber-800">Alasan Perubahan Harga *</span><Input value={l.price_change_reason || ""} onChange={(e) => update(i, { price_change_reason: e.target.value })} className="h-8 text-xs" placeholder="mis. kenaikan supplier / quotation terbaru / urgent delivery / kondisi pasar" data-testid={`po-price-reason-${i}`} /></div>}
            </div>;
          })}
        </div>
      </div>
      {lines.length > 0 && <div className="flex items-center justify-end px-1 text-sm"><span className="font-semibold text-muted-foreground">Grand Total:</span><span className="ml-2 font-bold tabular-nums">{rupiah(grand)}</span></div>}
      <Button variant="outline" size="sm" onClick={addRow}><Plus className="h-4 w-4 mr-2" />Tambah Baris</Button>
    </div>;
  }

  return <div className="space-y-3">
    <div className="border rounded-md overflow-x-auto bg-card shadow-sm">
      <table className="w-full text-sm min-w-[980px]">
        <thead className="bg-muted"><tr className="text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <th className="p-2 min-w-[210px]">Barang</th><th className="p-2 min-w-[150px]">Keterangan</th><th className="p-2 w-24">Qty</th><th className="p-2 min-w-[145px]">Satuan</th>
          {allocationColumn && <th className="p-2 min-w-[160px]">{allocationColumn.header || "Alokasi SPK"}</th>}
          {fields.warehouse && <th className="p-2 min-w-[140px]">Gudang</th>}{fields.project && <th className="p-2 min-w-[140px]">Proyek</th>}{fields.unit && <th className="p-2 min-w-[140px]">Unit/Aset</th>}
          {showPrice && <><th className="p-2 w-32">Harga / Satuan</th><th className="p-2 w-24">Diskon</th><th className="p-2 min-w-[150px]">Pajak</th><th className="p-2 w-32 text-right">Total</th></>}
          <th className="p-2 w-10"></th>
        </tr></thead>
        <tbody>{lines.length === 0 && <tr><td colSpan={colCount} className="p-6 text-center text-muted-foreground">Belum ada item</td></tr>}
          {lines.map((l, i) => <tr key={i} className="border-t align-top">
            <td className="p-1.5">{l._sourceLabel && <div className="mb-1 text-[10px] font-mono text-muted-foreground">{l._sourceLabel}</div>}<Combobox options={itemOpts} value={l.item_id} onChange={(v) => update(i, { item_id: v })} placeholder="Pilih barang" disabled={l._locked} /></td>
            <td className="p-1.5"><Input value={l.notes || ""} onChange={(e) => update(i, { notes: e.target.value })} className="h-9" placeholder="Keterangan item" /></td>
            <td className="p-1.5"><Input type="number" step="any" value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} className="h-9 text-right" /></td>
            <td className="p-1.5"><Uom l={l} i={i} /></td>
            {allocationColumn && <td className="p-1.5 align-middle">{allocationColumn.render(l, i)}</td>}
            {fields.warehouse && <td className="p-1.5"><Combobox options={whOpts} value={l.warehouse_id || ""} onChange={(v) => update(i, { warehouse_id: v })} placeholder="Gudang" /></td>}
            {fields.project && <td className="p-1.5"><Combobox options={projOpts} value={l.project_id || ""} onChange={(v) => update(i, { project_id: v })} placeholder="Proyek" /></td>}
            {fields.unit && <td className="p-1.5"><Combobox options={unitOpts} value={l.unit_id || ""} onChange={(v) => update(i, { unit_id: v })} placeholder="Unit" /></td>}
            {showPrice && <><td className="p-1.5"><Input type="number" value={l.price || 0} onChange={(e) => update(i, { price: e.target.value })} className="h-9 text-right" />{priceAccessory && priceAccessory(l, i)}</td><td className="p-1.5"><Input type="number" value={l.discount || 0} onChange={(e) => update(i, { discount: e.target.value })} className="h-9 text-right" /></td><td className="p-1.5"><Combobox options={taxOpts} value={l.tax_id || ""} onChange={(v) => update(i, { tax_id: v })} /></td><td className="p-2 text-right tabular-nums">{rupiah(total(l))}</td></>}
            <td className="p-1.5"><Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => onChange(lines.filter((_, x) => x !== i))}><Trash2 className="h-4 w-4 text-destructive" /></Button></td>
          </tr>)}</tbody>
        {showPrice && lines.length > 0 && <tfoot><tr className="border-t bg-muted/50 font-semibold"><td colSpan={colCount - 2} className="p-2 text-right">Grand Total</td><td className="p-2 text-right tabular-nums">{rupiah(grand)}</td><td></td></tr></tfoot>}
      </table>
    </div>
    <Button variant="outline" size="sm" onClick={addRow}><Plus className="h-4 w-4 mr-2" />Tambah Baris</Button>
  </div>;
}
