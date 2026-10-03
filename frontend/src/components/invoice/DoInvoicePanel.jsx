import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { rupiah } from "@/lib/format";
import { fmtD } from "@/lib/invoice";
import { Receipt } from "lucide-react";

// Ringkasan penagihan DO: invoice yang memakai DO ini, nilai sudah ditagihkan dan sisa.
export function DoInvoicePanel({ doId }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/vendor-invoices/do/${doId}`).then((r) => setD(r.data)).catch(() => setD(false)); }, [doId]);
  if (!d) return null;
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm" data-testid="do-invoice-panel">
      <div className="mb-3 flex flex-wrap items-center gap-3"><Receipt className="h-4 w-4 text-muted-foreground" /><h3 className="font-head text-sm font-semibold">Invoice Vendor</h3><StatusBadge status={d.billing_status} />
        <span className="ml-auto text-xs text-muted-foreground" data-testid="do-invoice-summary">Nilai DO {rupiah(d.do_value)} · Sudah Ditagihkan {rupiah(d.billed)} · Sisa Belum Ditagihkan {rupiah(d.remaining)}</span></div>
      {d.invoices.length === 0 ? <div className="text-sm text-muted-foreground">Belum ada invoice untuk DO ini</div> :
        <table className="w-full text-sm"><thead><tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground"><th className="p-2">No Invoice</th><th className="p-2">Tgl Invoice</th><th className="p-2 text-right">Nilai Ditagihkan</th><th className="p-2">Status Pembayaran</th></tr></thead>
          <tbody>{d.invoices.map((i) => <tr key={i.invoice_id} className="border-t" data-testid={`do-invoice-row-${i.invoice_no}`}>
            <td className="p-2 font-mono text-xs font-semibold"><Link to={`/invoice/${i.invoice_id}`} className="text-primary hover:underline">{i.invoice_no}</Link></td>
            <td className="p-2">{fmtD(i.invoice_date)}</td><td className="p-2 text-right tabular-nums">{rupiah(i.amount)}</td><td className="p-2"><StatusBadge status={i.payment_status} /></td></tr>)}</tbody></table>}
    </div>
  );
}
