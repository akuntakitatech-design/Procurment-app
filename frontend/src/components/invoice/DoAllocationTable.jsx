import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { rupiah, toNum } from "@/lib/format";
import { fmtD, round2 } from "@/lib/invoice";

// Pilih DO (supplier yang sama) + nilai alokasi per DO. Alokasi tidak boleh melebihi sisa belum ditagihkan.
export function DoAllocationTable({ rows, alloc, setAlloc, loading }) {
  const toggle = (r, on) => setAlloc((cur) => { const n = { ...cur }; if (on) n[r.do_id] = round2(r.remaining); else delete n[r.do_id]; return n; });
  const head = ["", "No DO", "Tgl DO", "No PO", "Proyek", "Divisi", "SPK", "Nilai DO", "Sudah Ditagihkan", "Sisa", "Alokasi Invoice"];
  return (
    <div className="overflow-x-auto rounded-xl border bg-card" data-testid="invoice-do-table">
      <table className="w-full min-w-[1250px] text-sm">
        <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {head.map((h, i) => <th key={i} className={`p-2.5 ${i >= 7 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
        <tbody>
          {loading && <tr><td colSpan={head.length} className="p-6 text-center text-muted-foreground">Memuat DO...</td></tr>}
          {!loading && rows.length === 0 && <tr><td colSpan={head.length} className="p-6 text-center text-muted-foreground" data-testid="invoice-do-empty">Tidak ada DO dengan sisa nilai yang belum ditagihkan untuk supplier ini</td></tr>}
          {!loading && rows.map((r) => {
            const on = alloc[r.do_id] !== undefined;
            const over = on && toNum(alloc[r.do_id]) > toNum(r.remaining) + 0.005;
            return (
              <tr key={r.do_id} className={`border-t transition-colors ${on ? "bg-primary/5" : ""}`} data-testid={`invoice-do-row-${r.do_no}`}>
                <td className="p-2.5"><Checkbox checked={on} onCheckedChange={(v) => toggle(r, !!v)} data-testid={`invoice-do-check-${r.do_no}`} aria-label={`Pilih ${r.do_no}`} /></td>
                <td className="p-2.5 font-mono text-xs font-semibold">{r.do_no}</td>
                <td className="p-2.5 text-xs">{fmtD(r.date)}</td>
                <td className="p-2.5 text-xs">{r.po_nos || "-"}</td>
                <td className="p-2.5 text-xs">{r.project || "-"}</td>
                <td className="p-2.5 text-xs">{r.division || "-"}</td>
                <td className="p-2.5 text-xs">{r.spk || "-"}</td>
                <td className="p-2.5 text-right tabular-nums">{rupiah(r.do_value)}</td>
                <td className="p-2.5 text-right tabular-nums">{rupiah(r.billed)}</td>
                <td className="p-2.5 text-right tabular-nums font-medium">{rupiah(r.remaining)}<div className="mt-1"><StatusBadge status={r.billing_status} /></div></td>
                <td className="p-2.5 text-right">
                  <Input type="number" step="0.01" min="0" disabled={!on} value={on ? alloc[r.do_id] : ""}
                    onChange={(e) => setAlloc((c) => ({ ...c, [r.do_id]: e.target.value }))}
                    className={`ml-auto h-8 w-40 text-right tabular-nums ${over ? "border-destructive text-destructive" : ""}`} data-testid={`invoice-do-alloc-${r.do_no}`} />
                  {over && <div className="mt-1 text-[11px] text-destructive">Melebihi sisa belum ditagihkan</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
