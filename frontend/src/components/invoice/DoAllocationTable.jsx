import { useMemo, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Combobox } from "@/components/Combobox";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { rupiah, toNum } from "@/lib/format";
import { fmtD, round2 } from "@/lib/invoice";

// Pilih DO (supplier yang sama) + nilai alokasi per DO. Alokasi tidak boleh melebihi sisa belum ditagihkan.
const SORTS = [
  { value: "do_asc", label: "No DO A–Z", k: "do_no", d: 1 }, { value: "do_desc", label: "No DO Z–A", k: "do_no", d: -1 },
  { value: "date_desc", label: "Tanggal DO terbaru", k: "date", d: -1 }, { value: "date_asc", label: "Tanggal DO terlama", k: "date", d: 1 },
  { value: "po_asc", label: "No PO A–Z", k: "po_nos", d: 1 }, { value: "mro_asc", label: "No MRO A–Z", k: "mro_nos", d: 1 },
];
const SEARCH_KEYS = ["mro_nos", "ro_nos", "po_nos", "do_no", "project", "spk", "division"];

export function DoAllocationTable({ rows: allRows, alloc, setAlloc, loading }) {
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState("date_desc");
  const rows = useMemo(() => {
    const n = q.trim().toLowerCase();
    const st = SORTS.find((x) => x.value === sortKey) || SORTS[0];
    return allRows.filter((r) => !n || SEARCH_KEYS.some((k) => String(r[k] || "").toLowerCase().includes(n)))
      .sort((a, b) => String(a[st.k] || "").localeCompare(String(b[st.k] || ""), "id", { numeric: true }) * st.d);
  }, [allRows, q, sortKey]);
  const toggle = (r, on) => setAlloc((cur) => { const n = { ...cur }; if (on) n[r.do_id] = round2(r.remaining); else delete n[r.do_id]; return n; });
  const head = ["", "No MRO", "No RO", "No PO", "No DO", "Tgl DO", "Proyek", "Divisi", "SPK", "Nilai DO", "Sudah Ditagihkan", "Sisa", "Alokasi Invoice"];
  return (
    <div className="space-y-2">
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative w-full max-w-sm"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari No MRO, RO, PO, DO, Proyek, SPK..." className="h-9 pl-9" data-testid="invoice-do-search" /></div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">Urutkan<div className="w-52"><Combobox dense options={SORTS} value={sortKey} onChange={setSortKey} testid="invoice-do-sort" /></div></div>
      <span className="ml-auto text-xs text-muted-foreground" data-testid="invoice-do-count">{rows.length} DO</span>
    </div>
    <div className="overflow-x-auto rounded-xl border bg-card" data-testid="invoice-do-table">
      <table className="w-full min-w-[1450px] text-sm">
        <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {head.map((h, i) => <th key={i} className={`p-2.5 ${i >= 9 ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
        <tbody>
          {loading && <tr><td colSpan={head.length} className="p-6 text-center text-muted-foreground">Memuat DO...</td></tr>}
          {!loading && rows.length === 0 && <tr><td colSpan={head.length} className="p-6 text-center text-muted-foreground" data-testid="invoice-do-empty">Tidak ada DO dengan sisa nilai yang belum ditagihkan untuk supplier ini</td></tr>}
          {!loading && rows.map((r) => {
            const on = alloc[r.do_id] !== undefined;
            const over = on && toNum(alloc[r.do_id]) > toNum(r.remaining) + 0.005;
            return (
              <tr key={r.do_id} className={`border-t transition-colors ${on ? "bg-primary/5" : ""}`} data-testid={`invoice-do-row-${r.do_no}`}>
                <td className="p-2.5"><Checkbox checked={on} onCheckedChange={(v) => toggle(r, !!v)} data-testid={`invoice-do-check-${r.do_no}`} aria-label={`Pilih ${r.do_no}`} /></td>
                <td className="p-2.5 font-mono text-[11px]">{r.mro_nos || "-"}</td>
                <td className="p-2.5 font-mono text-[11px]">{r.ro_nos || "-"}</td>
                <td className="p-2.5 font-mono text-[11px]">{r.po_nos || "-"}</td>
                <td className="p-2.5 font-mono text-xs font-semibold">{r.do_no}</td>
                <td className="p-2.5 text-xs">{fmtD(r.date)}</td>
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
    </div>
  );
}
