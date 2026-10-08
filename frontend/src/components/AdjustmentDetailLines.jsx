import { Info } from "lucide-react";
import { num, fmtDate } from "@/lib/format";

// Detail Penyesuaian Stok: gudang, project & unit dibaca PER BARIS (sumber stok/ledger/valuasi).
// Header hanya default dokumen. Dokumen lama (tanpa gudang per baris) dibaca via fallback header.
export function AdjustmentDetailLines({ doc, canPrice = false }) {
  if (!doc) return null;
  const lines = doc.lines || [];
  const meta = [
    ["Tanggal", doc.date ? fmtDate(doc.date) : "-"], ["Divisi", doc.division_name || "-"], ["Gudang Default", doc.warehouse_name || "-"],
    ["Project Default", doc.project_name || "-"], ["Jenis", doc.adj_type || "-"], ["Alasan", doc.reason || "-"], ["Catatan", doc.notes || "-"],
  ];
  const sign = (v) => `${Number(v) > 0 ? "+" : ""}${num(v)}`;
  return (
    <div className="space-y-3" data-testid="adj-detail">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-4" data-testid="adj-detail-header">
        {meta.map(([k, v]) => <div key={k} className="min-w-0"><div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{k}</div><div className="truncate" title={v}>{v}</div></div>)}
      </div>
      {doc.legacy_header_warehouse && <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-800" data-testid="adj-detail-legacy"><Info className="h-3.5 w-3.5" />Penyesuaian lama: gudang per baris yang kosong dibaca dari gudang header (data asli tidak diubah).</div>}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[1100px] text-sm" data-testid="adj-detail-lines">
          <thead className="bg-muted"><tr className="text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <th className="p-2">#</th><th className="p-2">Barang</th><th className="p-2">Gudang</th><th className="p-2">Project</th><th className="p-2">Unit/Aset</th><th className="p-2">Satuan</th>
            <th className="p-2 text-right">Stok Sebelum</th><th className="p-2 text-right">Penyesuaian</th><th className="p-2 text-right">Stok Sesudah</th>
            {canPrice && <th className="p-2 text-right">Biaya Satuan</th>}<th className="p-2">Alasan</th>
          </tr></thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={l.id || i} className="border-t" data-testid={`adj-detail-line-${i}`}>
                <td className="p-2 text-xs text-muted-foreground">{i + 1}</td>
                <td className="p-2"><span className="font-mono text-xs text-muted-foreground">{l.item_code}</span> {l.item_name}</td>
                <td className="p-2" data-testid={`adj-detail-warehouse-${i}`}>{l.warehouse_name || "-"}{l.legacy_header_warehouse && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">header</span>}</td>
                <td className="p-2" data-testid={`adj-detail-project-${i}`}>{l.project_name || "-"}</td>
                <td className="p-2" data-testid={`adj-detail-unit-${i}`}>{l.unit_name || "-"}</td>
                <td className="p-2 text-xs" data-testid={`adj-detail-uom-${i}`}>{l.uom_label || "-"}</td>
                <td className="p-2 text-right tabular-nums">{l.before == null ? "-" : num(l.before)}</td>
                <td className={`p-2 text-right font-semibold tabular-nums ${Number(l.adjustment) < 0 ? "text-destructive" : "text-emerald-700"}`} data-testid={`adj-detail-qty-${i}`}>{sign(l.adjustment)}</td>
                <td className="p-2 text-right tabular-nums">{l.after == null ? "-" : num(l.after)}</td>
                {canPrice && <td className="p-2 text-right tabular-nums">{Number(l.adjustment) > 0 && l.approved_unit_cost != null ? num(l.approved_unit_cost) : "-"}</td>}
                <td className="p-2 text-xs">{l.reason || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
