import { useEffect, useRef, useState } from "react";
import { Combobox } from "@/components/Combobox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Plus, Trash2, ChevronRight, ChevronDown, Info } from "lucide-react";
import { rupiah, num } from "@/lib/format";
import { computePriceStatus, StatusBadgePrice } from "@/components/PoPriceControl";
import { NumericInput } from "@/components/NumericInput";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function ItemLines({ lines, onChange, masters, fields = {}, showPrice = false, defaults = {}, taxInclusive = false, allocationColumn = null, priceAccessory = null, poControl = null }) {
  const items = masters.map("items");
  const uoms = masters.map("uoms");
  const taxes = masters.map("taxes");
  const prev = useRef({ warehouse_id: "", project_id: "", unit_id: "" });
  const linesRef = useRef(lines);
  const onChangeRef = useRef(onChange);
  linesRef.current = lines;
  onChangeRef.current = onChange;
  const [expandedRows, setExpandedRows] = useState({});

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
    // Keep item discount amount in sync (supports % / Rp; percent recomputes on qty/price change).
    const row = next[i];
    const dt = row.discount_type || "amount";
    const dv = Number(row.discount_value != null ? row.discount_value : row.discount) || 0;
    row.discount_type = dt; row.discount_value = dv;
    row.discount = dt === "percent" ? (Number(row.qty) || 0) * (Number(row.price) || 0) * dv / 100 : dv;
    onChange(next);
  };
  const addRow = () => onChange([...lines, { _key: (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `tmp-${Date.now()}-${Math.random().toString(36).slice(2)}`), item_id: "", qty: 1, uom_id: "", conversion_factor: 1, unit: "", warehouse_id: defaults.warehouse_id || "", project_id: defaults.project_id || "", unit_id: defaults.unit_id || "", _warehouseOverride: false, _projectOverride: false, _unitOverride: false, notes: "", price: 0, discount: 0, tax_id: "", tax: 0 }]);
  const discType = (l) => l.discount_type || "amount";
  const discVal = (l) => Number(l.discount_value != null ? l.discount_value : l.discount) || 0;
  const discAmt = (l) => discType(l) === "percent" ? (Number(l.qty) || 0) * (Number(l.price) || 0) * discVal(l) / 100 : discVal(l);
  const total = (l) => { const base = (Number(l.qty) || 0) * (Number(l.price) || 0) - discAmt(l); return taxInclusive ? Math.max(0, base) : base + base * (Number(l.tax) || 0) / 100; };
  const grand = lines.reduce((s, l) => s + total(l), 0);
  const stockInfo = (l) => { const it = items[l.item_id]; if (!it) return ""; const base = it.base_uom_id ? uomLabel(it.base_uom_id) : it.unit; return base ? `${num((Number(l.qty) || 0) * (Number(l.conversion_factor) || 1))} ${base}` : ""; };
  const Uom = ({ l, i }) => <div className="flex items-center gap-1"><div className="min-w-0 flex-1"><Combobox dense options={itemUoms(l.item_id)} value={l.uom_id || items[l.item_id]?.base_uom_id || ""} onChange={(v) => update(i, { uom_id: v })} placeholder="Satuan" disabled={!l.item_id || itemUoms(l.item_id).length <= 1} /></div>{l.item_id && <Popover><PopoverTrigger asChild><button type="button" className="shrink-0 text-muted-foreground transition-colors hover:text-primary" title="Konversi Stok" data-testid={`po-uom-info-${i}`}><Info className="h-4 w-4" /></button></PopoverTrigger><PopoverContent align="end" className="w-60 text-xs"><div className="space-y-1"><div className="font-semibold">Konversi Stok</div><div className="flex justify-between gap-3"><span className="text-muted-foreground">Satuan transaksi</span><span className="font-medium">{num(l.qty)} {l.unit || ""}</span></div>{(Number(l.conversion_factor) || 1) !== 1 && <div className="flex justify-between gap-3"><span className="text-muted-foreground">Konversi</span><span>1 {l.unit || ""} = {num(l.conversion_factor)} {items[l.item_id]?.unit || ""}</span></div>}<div className="flex justify-between gap-3 border-t pt-1"><span className="text-muted-foreground">Terhitung stok</span><span className="font-semibold">{stockInfo(l)}</span></div></div></PopoverContent></Popover>}</div>;

  // Total rendered columns (keeps empty-row / grand-total colSpans correct).
  const colCount = 4 + (allocationColumn ? 1 : 0) + (fields.warehouse ? 1 : 0) + (fields.project ? 1 : 0) + (fields.unit ? 1 : 0) + (showPrice ? 4 : 0) + 1;

  // ---- PO item block: Primary Row + Secondary Row + Expandable Detail (CP5A PO Item UX). ----
  if (poControl) {
    const fmtPct = (p) => `${p >= 0 ? "+" : ""}${Number(p).toFixed(2).replace(".", ",")}%`;
    const fmtRp = (v) => `${v >= 0 ? "+" : "-"}${rupiah(Math.abs(v))}`;
    const head = [["w-[36px]", ""], ["w-[180px]", "Barang"], ["w-[170px]", "Keterangan"], ["w-[80px]", "Qty"], ["w-[110px]", "Satuan"], ["w-[130px]", "Harga Kontrak"], ["w-[170px]", "Harga Satuan"], ["w-[175px]", "Diskon Item"], ["w-[115px]", "Selisih"], ["w-[140px]", "Total"], ["w-[105px]", "Status"], ["w-[40px]", "Aksi"]];
    const lbl = "mb-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground";
    return <div className="space-y-3">
      <div className="overflow-x-auto rounded-md border bg-card shadow-sm">
        <div className="min-w-[1545px]">
          <div className="flex items-stretch gap-1.5 border-b bg-muted px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {head.map(([w, t], k) => <div key={k} className={w + " shrink-0"}>{t}</div>)}
          </div>
          {lines.length === 0 && <div className="p-6 text-center text-sm text-muted-foreground">Belum ada item</div>}
          {lines.map((l, i) => {
            const c = poControl.contractOf(i);
            const hasC = !!(c && c.found && Number(c.contract_price) > 0);
            const priceNum = Number(l.price) || 0;
            const qtyNum = Number(l.qty) || 0;
            const effNum = qtyNum > 0 ? (qtyNum * priceNum - discAmt(l)) / qtyNum : priceNum;
            const r = computePriceStatus(c, effNum);
            const showVar = hasC && priceNum > 0;
            let status = r.status;
            if (hasC && !(priceNum > 0)) status = "Belum dihitung";
            const reasonMissing = hasC && priceNum > 0 && r.status === "Price Override" && !String(l.price_change_reason || "").trim();
            const expanded = expandedRows[i] !== undefined ? expandedRows[i] : reasonMissing;
            const toggle = () => setExpandedRows((s) => ({ ...s, [i]: !(s[i] !== undefined ? s[i] : reasonMissing) }));
            return <div key={i} className="border-b px-3 py-2.5 last:border-b-0" data-testid={`po-item-block-${i}`}>
              {/* PRIMARY ROW — Transaction & Price */}
              <div className="flex items-center gap-1.5">
                <div className="w-[36px] shrink-0"><button type="button" onClick={toggle} className="flex h-7 w-7 items-center justify-center rounded hover:bg-accent" data-testid={`po-expand-${i}`} title="Detail">{expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button></div>
                <div className="w-[180px] shrink-0"><Combobox options={itemOpts} value={l.item_id} onChange={(v) => update(i, { item_id: v })} placeholder="Pilih barang" disabled={l._locked} /></div>
                <div className="w-[170px] shrink-0"><Input value={l.notes || ""} onChange={(e) => update(i, { notes: e.target.value })} className="h-9 text-sm" placeholder="Keterangan" data-testid={`po-notes-${i}`} /></div>
                <div className="w-[80px] shrink-0"><NumericInput mode="quantity" value={l.qty} onChange={(v) => update(i, { qty: v })} className="h-9 text-right" data-testid={`po-qty-${i}`} /></div>
                <div className="w-[110px] shrink-0"><Uom l={l} i={i} /></div>
                <div className="w-[130px] shrink-0 text-sm">{hasC ? <span className="font-semibold tabular-nums">{rupiah(Number(c.contract_price))}</span> : (c && c.out_of_period ? <span className="text-[11px] font-medium text-amber-700" data-testid={`po-contract-period-warn-${i}`}>Kontrak {c.contract_number || ""} di luar periode</span> : <span className="text-xs text-muted-foreground">Tidak ada kontrak</span>)}</div>
                <div className="w-[170px] shrink-0"><div className="flex items-center gap-1"><div className="min-w-0 flex-1"><NumericInput mode="money" value={l.price} onChange={(v) => update(i, { price: v, _priceTouched: true, _priceAuto: false })} className="h-9 text-right" data-testid={`po-price-input-${i}`} /></div>{poControl.history && <div className="shrink-0">{poControl.history(l, i)}</div>}</div></div>
                <div className="w-[175px] shrink-0"><div className="flex items-center gap-1"><button type="button" onClick={() => update(i, { discount_type: discType(l) === "percent" ? "amount" : "percent", discount_value: discVal(l) })} className="h-9 w-10 shrink-0 rounded border text-xs font-semibold hover:bg-accent" data-testid={`po-discount-type-${i}`} title="Ubah metode diskon (% / Rp)">{discType(l) === "percent" ? "%" : "Rp"}</button><div className="min-w-0 flex-1"><NumericInput mode={discType(l) === "percent" ? "quantity" : "money"} value={discVal(l)} onChange={(v) => update(i, { discount_value: v, discount_type: discType(l) })} className="h-9 text-right" data-testid={`po-discount-${i}`} /></div></div></div>
                <div className="w-[115px] shrink-0 text-xs tabular-nums" data-testid={`po-variance-${i}`}>{showVar ? <span className={r.varRp > 0 ? "text-amber-700" : r.varRp < 0 ? "text-emerald-700" : "text-muted-foreground"}>{fmtRp(r.varRp)}<br />{fmtPct(r.varPct)}</span> : <span className="text-muted-foreground">—</span>}</div>
                <div className="w-[140px] shrink-0 text-right text-sm font-semibold tabular-nums" data-testid={`po-total-${i}`}>{rupiah(total(l))}</div>
                <div className="w-[105px] shrink-0">{status === "Belum dihitung" ? <span data-testid={`po-status-${i}`} className="inline-flex items-center rounded-full border border-slate-300 bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">Belum dihitung</span> : <StatusBadgePrice status={status} testid={`po-status-${i}`} />}{reasonMissing && <div className="mt-0.5 text-[10px] font-semibold text-amber-700" data-testid={`po-reason-required-${i}`}>Alasan diperlukan</div>}</div>
                <div className="w-[40px] shrink-0"><Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => onChange(lines.filter((_, x) => x !== i))}><Trash2 className="h-4 w-4 text-destructive" /></Button></div>
              </div>
              {/* SECONDARY ROW — Reference & Operational (labelled) */}
              <div className="mt-2 flex items-end gap-2 pl-[44px]">
                <div className="w-[220px]"><div className={lbl}>MRO / RO</div><div className="flex h-9 items-center truncate font-mono text-[11px] text-muted-foreground" data-testid={`po-source-${i}`}>{poControl.sourceText && poControl.sourceText(l) ? poControl.sourceText(l) : <span className="italic">—</span>}</div></div>
                <div className="w-[260px]"><div className={lbl}>Alokasi SPK</div><div data-testid={`po-alloc-${i}`}>{allocationColumn ? allocationColumn.render(l, i) : null}</div></div>
                <div className="w-[150px]"><div className={lbl}>Gudang</div><Combobox options={whOpts} value={l.warehouse_id || ""} onChange={(v) => update(i, { warehouse_id: v })} placeholder="Gudang" /></div>
                <div className="w-[150px]"><div className={lbl}>Proyek</div><Combobox options={projOpts} value={l.project_id || ""} onChange={(v) => update(i, { project_id: v })} placeholder="Proyek" /></div>
                <div className="w-[150px]"><div className={lbl}>Unit / Aset</div><Combobox options={unitOpts} value={l.unit_id || ""} onChange={(v) => update(i, { unit_id: v })} placeholder="Unit/Aset" /></div>
                <div className="w-[160px]"><div className={lbl}>Pajak</div><Combobox dense options={taxOpts} value={l.tax_id || ""} onChange={(v) => update(i, { tax_id: v })} /></div>
              </div>
              {/* EXPANDED DETAIL */}
              {expanded && <div className="mt-2 rounded-md border bg-muted/30 px-3 py-2 pl-[44px] text-xs" data-testid={`po-detail-${i}`}>
                {hasC ? <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground"><span>No. Kontrak: <b className="text-foreground">{c.contract_number || "-"}</b></span><span>Periode: <b className="text-foreground">{c.effective_start || "-"}{c.effective_end ? ` – ${c.effective_end}` : ""}</b></span><span>Toleransi: <b className="text-foreground">{c.tolerance_pct != null ? `${c.tolerance_pct}%` : "-"}</b></span>{c.min_qty != null && <span>Min Qty Tier: <b className="text-foreground">{num(c.min_qty)}</b></span>}</div> : (c && c.out_of_period ? <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/70 px-2 py-1.5 text-amber-800" data-testid={`po-period-detail-${i}`}><span className="text-[11px] font-semibold">Peringatan Periode Kontrak</span><span className="text-[11px]">Kontrak <b>{c.contract_number || "-"}</b> berlaku {c.effective_start || "-"}{c.effective_end ? ` – ${c.effective_end}` : ""}, namun Tanggal PO di luar periode. Harga kontrak tidak diterapkan (item dianggap tanpa kontrak). Submit tetap diperbolehkan.</span></div> : <div className="text-muted-foreground">Tidak ada kontrak vendor yang berlaku untuk item ini.</div>)}
                {hasC && priceNum > 0 && r.status === "Price Override" && <div className="mt-2 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/70 px-2 py-1.5"><span className="whitespace-nowrap text-[11px] font-semibold text-amber-800">Alasan Perubahan Harga *</span><Input value={l.price_change_reason || ""} onChange={(e) => update(i, { price_change_reason: e.target.value })} className="h-8 text-xs" placeholder="mis. kenaikan supplier / quotation terbaru / urgent delivery / kondisi pasar" data-testid={`po-price-reason-${i}`} /></div>}
              </div>}
            </div>;
          })}
        </div>
      </div>
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
            <td className="p-1.5"><NumericInput mode="quantity" value={l.qty} onChange={(v) => update(i, { qty: v })} className="h-9 text-right" /></td>
            <td className="p-1.5"><Uom l={l} i={i} /></td>
            {allocationColumn && <td className="p-1.5 align-middle">{allocationColumn.render(l, i)}</td>}
            {fields.warehouse && <td className="p-1.5"><Combobox options={whOpts} value={l.warehouse_id || ""} onChange={(v) => update(i, { warehouse_id: v })} placeholder="Gudang" /></td>}
            {fields.project && <td className="p-1.5"><Combobox options={projOpts} value={l.project_id || ""} onChange={(v) => update(i, { project_id: v })} placeholder="Proyek" /></td>}
            {fields.unit && <td className="p-1.5"><Combobox options={unitOpts} value={l.unit_id || ""} onChange={(v) => update(i, { unit_id: v })} placeholder="Unit" /></td>}
            {showPrice && <><td className="p-1.5"><NumericInput mode="money" value={l.price} onChange={(v) => update(i, { price: v })} className="h-9 text-right" />{priceAccessory && priceAccessory(l, i)}</td><td className="p-1.5"><NumericInput mode="money" value={l.discount} onChange={(v) => update(i, { discount: v })} className="h-9 text-right" /></td><td className="p-1.5"><Combobox options={taxOpts} value={l.tax_id || ""} onChange={(v) => update(i, { tax_id: v })} /></td><td className="p-2 text-right tabular-nums">{rupiah(total(l))}</td></>}
            <td className="p-1.5"><Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => onChange(lines.filter((_, x) => x !== i))}><Trash2 className="h-4 w-4 text-destructive" /></Button></td>
          </tr>)}</tbody>
        {showPrice && lines.length > 0 && <tfoot><tr className="border-t bg-muted/50 font-semibold"><td colSpan={colCount - 2} className="p-2 text-right">Grand Total</td><td className="p-2 text-right tabular-nums">{rupiah(grand)}</td><td></td></tr></tfoot>}
      </table>
    </div>
    <Button variant="outline" size="sm" onClick={addRow}><Plus className="h-4 w-4 mr-2" />Tambah Baris</Button>
  </div>;
}
