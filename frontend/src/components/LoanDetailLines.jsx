import { ArrowRight, Info } from "lucide-react";
import { num, fmtDate } from "@/lib/format";

// Detail Pinjam Barang: gudang pemberi/peminjam, project & unit dibaca PER BARIS (sumber posting/return).
// Header hanya default dokumen. Pinjaman lama (tanpa gudang per baris) dibaca via fallback header.
const factor = (l) => Number(l.conversion_factor) || 1;
const ownQty = (l) => num(l.display_qty ?? ((Number(l.qty) || 0) / factor(l)));
const convQty = (l, v) => num((Number(v) || 0) / factor(l));

export function LoanDetailLines({ doc }) {
  if (!doc) return null;
  const lines = doc.lines || [];
  const legacy = !!doc.legacy_header_warehouse;
  const meta = [
    ["Tanggal", doc.date ? fmtDate(doc.date) : "-"], ["Divisi", doc.division_name || "-"],
    ["Project Default", doc.project_name || "-"], ["Gudang Pemberi Default", doc.from_name || "-"], ["Gudang Peminjam Default", doc.to_name || "-"],
    ["Target Pengembalian", doc.due_date ? fmtDate(doc.due_date) : "-"], ["Pemohon", doc.requester || "-"], ["Keterangan", doc.notes || "-"],
  ];
  return (
    <div className="space-y-3" data-testid="loan-detail">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-4" data-testid="loan-detail-header">
        {meta.map(([k, v]) => <div key={k} className="min-w-0"><div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{k}</div><div className="truncate" title={v}>{v}</div></div>)}
      </div>
      {legacy && <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-800" data-testid="loan-detail-legacy"><Info className="h-3.5 w-3.5" />Pinjaman lama: gudang per baris dibaca dari gudang header (data asli tidak diubah).</div>}
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[1100px] text-sm" data-testid="loan-detail-lines">
          <thead className="bg-muted"><tr className="text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <th className="p-2">#</th><th className="p-2">Barang</th><th className="p-2 text-right">Qty Pinjam</th><th className="p-2">Satuan</th>
            <th className="p-2">Gudang Pemberi</th><th className="p-2"></th><th className="p-2">Gudang Peminjam</th><th className="p-2">Project</th><th className="p-2">Unit/Aset</th>
            <th className="p-2 text-right">Kembali</th><th className="p-2 text-right">Outstanding</th>
          </tr></thead>
          <tbody>
            {lines.length === 0 && <tr><td colSpan={11} className="p-4 text-center text-muted-foreground">Tidak ada baris</td></tr>}
            {lines.map((l, i) => (
              <tr key={l.id || i} className="border-t" data-testid={`loan-detail-line-${i}`}>
                <td className="p-2 text-muted-foreground">{i + 1}</td>
                <td className="p-2"><div className="font-medium">{l.item_name || "-"}</div>{l.item_code && <div className="font-mono text-[11px] text-muted-foreground">{l.item_code}</div>}{l.notes && <div className="text-[11px] text-muted-foreground">{l.notes}</div>}</td>
                <td className="p-2 text-right tabular-nums" data-testid={`loan-detail-qty-${i}`}>{ownQty(l)}</td>
                <td className="p-2">{l.display_unit || l.unit || "-"}</td>
                <td className="p-2" data-testid={`loan-detail-from-${i}`}>{l.from_name || "-"}</td>
                <td className="p-2 text-muted-foreground"><ArrowRight className="h-3.5 w-3.5" /></td>
                <td className="p-2" data-testid={`loan-detail-to-${i}`}>{l.to_name || "-"}</td>
                <td className="p-2" data-testid={`loan-detail-project-${i}`}>{l.project_name || "-"}</td>
                <td className="p-2" data-testid={`loan-detail-unit-${i}`}>{l.unit_name || "-"}</td>
                <td className="p-2 text-right tabular-nums" data-testid={`loan-detail-returned-${i}`}>{convQty(l, l.returned)}</td>
                <td className="p-2 text-right font-semibold tabular-nums" data-testid={`loan-detail-outstanding-${i}`}>{convQty(l, l.outstanding)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
