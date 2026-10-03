import { Combobox } from "@/components/Combobox";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { NumericInput } from "@/components/NumericInput";
import { num } from "@/lib/format";
import { Trash2, AlertTriangle } from "lucide-react";

const EPS = 1e-9;
export const sisaOf = (l) => Math.max((Number(l.qty_po) || 0) - (Number(l.received_before) || 0), 0);
export const overOf = (l) => { const o = (Number(l.qty) || 0) - sisaOf(l); return l.qty_po == null ? 0 : (o > EPS ? o : 0); };
const CONDITIONS = [{ value: "Baik", label: "Baik" }, { value: "Rusak", label: "Rusak" }, { value: "Kurang", label: "Kurang" }, { value: "Lebih", label: "Lebih" }];
const EXC_LABEL = { Rusak: "Qty Rusak", Kurang: "Qty Kurang", Lebih: "Qty Lebih" };

// Column widths shared by header + rows (min-width layout, horizontal scroll).
export const DO_COLS = [["w-[200px]", "Barang"], ["w-[160px]", "Keterangan"], ["w-[130px]", "Gudang"], ["w-[130px]", "Proyek"], ["w-[120px]", "Unit/Aset"], ["w-[80px]", "Qty PO", 1], ["w-[100px]", "Sudah Diterima", 1], ["w-[80px]", "Sisa", 1], ["w-[110px]", "Qty Terima", 1], ["w-[90px]", "Satuan"], ["w-[110px]", "Kondisi"], ["w-[120px]", "Qty Selisih", 1], ["w-[44px]", ""]];

function SourceInfo({ l, i, allocCell }) {
  const g = l.lineage || {};
  const part = (label, v, tid) => <span data-testid={`do-src-${tid}-${i}`}><span className="font-semibold uppercase tracking-wide">{label}</span> {v || "-"}</span>;
  return (
    <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground" data-testid={`do-source-info-${i}`}>
      {part("MRO", g.mro, "mro")}<span>|</span>{part("RO", g.ro, "ro")}<span>|</span>{part("PO", g.po || l.po_no, "po")}<span>|</span>
      <span className="font-semibold uppercase tracking-wide">Alokasi SPK</span>{allocCell}
    </div>
  );
}

function Selisih({ l, i, editable, upd }) {
  const over = overOf(l);
  if (over > 0) return <div className="text-right" data-testid={`do-selisih-${i}`}><div className="font-semibold tabular-nums text-orange-700">+{num(over)}</div><div className="inline-flex items-center gap-0.5 rounded bg-orange-100 px-1 text-[10px] font-semibold text-orange-800" data-testid={`do-over-badge-${i}`}><AlertTriangle className="h-3 w-3" />Melebihi PO</div></div>;
  const cond = l.condition || "Baik";
  if (cond !== "Baik" && editable) return <div><NumericInput mode="quantity" value={l.exception_qty} onChange={(v) => upd(i, { exception_qty: v })} className="h-9 text-right" data-testid={`do-exception-${i}`} /><div className="mt-0.5 text-[10px] text-muted-foreground">{EXC_LABEL[cond]}</div></div>;
  if (cond !== "Baik" && Number(l.exception_qty) > 0) return <div className="text-right text-sm" data-testid={`do-selisih-${i}`}><div className="tabular-nums">{num(l.exception_qty)}</div><div className="text-[10px] text-muted-foreground">{EXC_LABEL[cond]}</div></div>;
  return <div className="text-right text-sm tabular-nums" data-testid={`do-selisih-${i}`}>0</div>;
}

export function DoItemRow({ l, i, editable, upd, remove, names, allocCell }) {
  const RO = ({ v, tid }) => <div className="truncate text-sm text-muted-foreground" title={v || ""} data-testid={tid}>{v || "-"}</div>;
  const over = overOf(l);
  return (
    <div className={`border-b px-3 py-2.5 last:border-b-0 ${over > 0 ? "bg-orange-50/40" : ""}`} data-testid={`do-item-block-${i}`}>
      <SourceInfo l={l} i={i} allocCell={allocCell} />
      <div className="flex items-center gap-1.5">
        <div className="w-[200px] shrink-0 text-sm font-medium" data-testid={`do-item-${i}`}>{l.item_name || l.item_code || "-"}</div>
        <div className="w-[160px] shrink-0"><RO v={l.notes} tid={`do-notes-${i}`} /></div>
        <div className="w-[130px] shrink-0"><RO v={names.wh(l)} tid={`do-wh-${i}`} /></div>
        <div className="w-[130px] shrink-0"><RO v={names.project(l)} tid={`do-project-${i}`} /></div>
        <div className="w-[120px] shrink-0"><RO v={names.unit(l)} tid={`do-unit-${i}`} /></div>
        <div className="w-[80px] shrink-0 text-right text-sm tabular-nums" data-testid={`do-qty-po-${i}`}>{l.qty_po == null ? "-" : num(l.qty_po)}</div>
        <div className="w-[100px] shrink-0 text-right text-sm tabular-nums" data-testid={`do-received-${i}`}>{l.qty_po == null ? "-" : num(l.received_before)}</div>
        <div className="w-[80px] shrink-0 text-right text-sm font-medium tabular-nums" data-testid={`do-sisa-${i}`}>{l.qty_po == null ? "-" : num(sisaOf(l))}</div>
        <div className="w-[110px] shrink-0">{editable ? <NumericInput mode="quantity" value={l.qty} onChange={(v) => upd(i, { qty: v })} className={`h-9 text-right ${over > 0 ? "border-orange-400" : ""}`} data-testid={`do-qty-${i}`} /> : <div className="text-right text-sm tabular-nums">{num(l.display_qty ?? l.qty)}</div>}</div>
        <div className="w-[90px] shrink-0 truncate text-sm" data-testid={`do-uom-${i}`}>{l.display_unit || l.unit || "-"}</div>
        <div className="w-[110px] shrink-0">{editable ? <Combobox dense options={CONDITIONS} value={l.condition || "Baik"} onChange={(v) => upd(i, { condition: v })} testid={`do-condition-${i}`} /> : <span className="text-sm">{l.condition || "Baik"}</span>}</div>
        <div className="w-[120px] shrink-0"><Selisih l={l} i={i} editable={editable} upd={upd} /></div>
        <div className="w-[44px] shrink-0">{editable && <Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => remove(i)} data-testid={`do-remove-${i}`}><Trash2 className="h-4 w-4 text-destructive" /></Button>}</div>
      </div>
      {over > 0 && <div className="mt-2 flex items-center gap-2 pl-[200px]" data-testid={`do-over-row-${i}`}>
        <span className="shrink-0 text-xs font-semibold text-orange-800">Penerimaan Berlebih +{num(over)} {l.display_unit || l.unit || ""} · Alasan Penerimaan Berlebih *</span>
        {editable ? <Input value={l.over_receipt_reason || ""} onChange={(e) => upd(i, { over_receipt_reason: e.target.value })} placeholder="Wajib diisi sebelum posting" className={`h-8 max-w-md text-sm ${String(l.over_receipt_reason || "").trim() ? "" : "border-destructive"}`} data-testid={`do-over-reason-${i}`} /> : <span className="text-xs">{l.over_receipt_reason || "-"}</span>}
      </div>}
    </div>
  );
}
