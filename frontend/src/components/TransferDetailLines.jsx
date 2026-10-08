import { ArrowRight, Info } from "lucide-react";
import { num, fmtDate } from "@/lib/format";

// Detail Transfer: pergerakan barang dibaca PER BARIS (gudang asal/tujuan, project, unit/aset).
// Header hanya ditampilkan sebagai default dokumen. Transaksi lama (tanpa gudang per baris) dibaca via fallback header.
export function TransferDetailLines({ doc }) {
  if (!doc) return null;
  const lines = doc.lines || [];
  const legacy = !!doc.legacy_header_warehouse;
  const meta = [
    ["Tanggal", doc.date ? fmtDate(doc.date) : "-"], ["Divisi", doc.division_name || "-"],
    ["Project Default", doc.project_name || "-"], ["Gudang Asal Default", doc.from_name || "-"], ["Gudang Tujuan Default", doc.to_name || "-"],
    ["Keterangan", doc.notes || "-"],
  ];
  return (
    <div className="space-y-3" data-testid="trf-detail">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-3 lg:grid-cols-6" data-testid="trf-detail-header">
        {meta.map(([k, v]) => <div key={k} className="min-w-0"><div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{k}</div><div className="truncate" title={v}>{v}</div></div>)}
      </div>
      {legacy && <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-800" data-testid="trf-detail-legacy"><Info className="h-3.5 w-3.5" />Transaksi lama: gudang per baris dibaca dari gudang header (data asli tidak diubah).</div>}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[960px] text-sm" data-testid="trf-detail-lines">
          <thead className="bg-muted"><tr className="text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <th className="p-2">#</th><th className="p-2">Barang</th><th className="p-2">Keterangan</th><th className="p-2 text-right">Qty</th><th className="p-2">Satuan</th>
            <th className="p-2">Gudang Asal</th><th className="p-2"></th><th className="p-2">Gudang Tujuan</th><th className="p-2">Project</th><th className="p-2">Unit/Aset</th>
          </tr></thead>
          <tbody>
            {lines.length === 0 && <tr><td colSpan={10} className="p-4 text-center text-muted-foreground">Tidak ada baris</td></tr>}
            {lines.map((l, i) => (
              <tr key={l.id || i} className="border-t" data-testid={`trf-detail-line-${i}`}>
                <td className="p-2 text-muted-foreground">{i + 1}</td>
                <td className="p-2"><div className="font-medium">{l.item_name || "-"}</div>{l.item_code && <div className="font-mono text-[11px] text-muted-foreground">{l.item_code}</div>}</td>
                <td className="p-2 text-muted-foreground">{l.notes || "-"}</td>
                <td className="p-2 text-right tabular-nums">{num(l.qty)}</td>
                <td className="p-2">{l.display_unit || l.unit || "-"}</td>
                <td className="p-2" data-testid={`trf-detail-from-${i}`}>{l.from_name || "-"}</td>
                <td className="p-2 text-muted-foreground"><ArrowRight className="h-3.5 w-3.5" /></td>
                <td className="p-2" data-testid={`trf-detail-to-${i}`}>{l.to_name || "-"}</td>
                <td className="p-2" data-testid={`trf-detail-project-${i}`}>{l.project_name || "-"}</td>
                <td className="p-2" data-testid={`trf-detail-unit-${i}`}>{l.unit_name || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
