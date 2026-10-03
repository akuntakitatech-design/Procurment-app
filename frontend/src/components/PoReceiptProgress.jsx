import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import { num, fmtDate } from "@/lib/format";

export function PoReceiptProgress({ doc }) {
  const lines = doc.lines || [], hist = doc.receipt_history || [];
  return (
    <Card data-testid="po-receipt-progress"><CardContent className="pt-6 space-y-5">
      <div className="flex flex-wrap items-center gap-3"><h3 className="font-head text-sm font-semibold">Progres Penerimaan</h3><StatusBadge status={doc.receipt_status} /></div>
      <div className="overflow-x-auto rounded-md border"><table className="w-full text-sm zebra">
        <thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">Barang</th><th className="p-2">Satuan</th><th className="p-2 text-right">Qty PO</th><th className="p-2 text-right">Sudah Diterima</th><th className="p-2 text-right">Sisa</th><th className="p-2 text-right">Qty Berlebih</th><th className="p-2">Status Penerimaan</th></tr></thead>
        <tbody>{lines.map((l, i) => { const r = l.receipt || {}; return (
          <tr key={l.id || i} className="border-t" data-testid={`po-receipt-line-${i}`}>
            <td className="p-2">{l.item_code} — {l.item_name}</td><td className="p-2">{l.display_unit || l.unit || "-"}</td>
            <td className="p-2 text-right tabular-nums">{num(r.qty_po)}</td><td className="p-2 text-right tabular-nums">{num(r.received)}</td>
            <td className="p-2 text-right tabular-nums">{num(r.remaining)}</td>
            <td className={`p-2 text-right tabular-nums ${r.over > 0 ? "font-semibold text-orange-700" : ""}`}>{r.over > 0 ? `+${num(r.over)}` : "0"}</td>
            <td className="p-2"><StatusBadge status={r.status} /></td>
          </tr>); })}</tbody>
      </table></div>
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Riwayat Penerimaan</h4>
        {hist.length === 0 ? <p className="text-sm text-muted-foreground">Belum ada penerimaan.</p> : (
          <div className="overflow-x-auto rounded-md border"><table className="w-full text-sm">
            <thead className="bg-muted"><tr className="text-left text-xs uppercase text-muted-foreground"><th className="p-2">No. DO</th><th className="p-2">Tanggal</th><th className="p-2">Barang</th><th className="p-2 text-right">Qty Diterima</th><th className="p-2 text-right">Qty Berlebih</th><th className="p-2">Alasan Penerimaan Berlebih</th></tr></thead>
            <tbody>{hist.map((h, i) => (
              <tr key={i} className="border-t" data-testid={`po-receipt-history-${i}`}>
                <td className="p-2 font-mono text-xs font-semibold">{h.do_no}</td><td className="p-2">{fmtDate(h.date)}</td><td className="p-2">{h.item}</td>
                <td className="p-2 text-right tabular-nums">{num(h.qty)} {h.unit || ""}</td>
                <td className={`p-2 text-right tabular-nums ${h.over_qty > 0 ? "font-semibold text-orange-700" : ""}`}>{h.over_qty > 0 ? `+${num(h.over_qty)}` : "0"}</td>
                <td className="p-2 text-xs">{h.reason || "-"}{h.reason && h.user ? <span className="text-muted-foreground"> · {h.user}</span> : null}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </div>
    </CardContent></Card>
  );
}
