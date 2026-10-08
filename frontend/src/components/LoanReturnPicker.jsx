import { useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { DatePicker, Field } from "@/components/DatePicker";
import { num, todayISO } from "@/lib/format";
import { returnIssues } from "@/lib/loanLines";
import { AlertTriangle, ArrowRight, Undo2, X } from "lucide-react";
import { toast } from "sonner";

/**
 * Return Pinjaman (khusus Pinjam Barang) — inline, per loan_line_id.
 * Arah return selalu dari baris pinjaman asli: Gudang Peminjam baris -> Gudang Pemberi baris (tidak dipilih user).
 * Validasi qty <= outstanding di frontend (peringatan jelas); backend tetap hard-block.
 */
export function LoanReturnPicker({ open, loanId, onClose, onPosted }) {
  const [rows, setRows] = useState([]);
  const [sel, setSel] = useState({}); // loan_line_id -> qty (string)
  const [date, setDate] = useState(todayISO());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || !loanId) return;
    setSel({}); setError(""); setDate(todayISO()); setLoading(true);
    api.get(`/loans/${loanId}/returnable`)
      .then((r) => setRows(Array.isArray(r.data) ? r.data : []))
      .catch((e) => { setRows([]); setError(apiError(e.response?.data?.detail)); })
      .finally(() => setLoading(false));
  }, [open, loanId]);

  if (!open) return null;

  const issues = returnIssues(rows, sel);
  const picked = Object.keys(sel);
  const blocked = picked.length === 0 || Object.values(issues).some(Boolean);
  const toggle = (r) => setSel((s) => { const n = { ...s }; if (r.loan_line_id in n) delete n[r.loan_line_id]; else n[r.loan_line_id] = String(r.outstanding); return n; });

  const submit = async () => {
    if (blocked) { toast.error(Object.values(issues).find(Boolean) || "Pilih minimal satu baris"); return; }
    setSaving(true); setError("");
    try {
      await api.post(`/loans/${loanId}/return`, { date, lines: picked.map((id) => ({ loan_line_id: id, qty: Number(sel[id]) })) });
      toast.success("Pengembalian diposting");
      onPosted?.();
    } catch (e) {
      const msg = apiError(e.response?.data?.detail); setError(msg); toast.error(msg); // panel tetap terbuka, input tidak hilang
    } finally { setSaving(false); }
  };

  return (
    <section className="rounded-xl border bg-card shadow-sm" data-testid="loan-return-picker">
      <div className="flex items-start justify-between gap-3 border-b p-4">
        <div>
          <div className="font-head text-sm font-semibold">Return Pinjaman</div>
          <div className="text-xs text-muted-foreground" data-testid="loan-return-picker-hint">Arah return mengikuti baris pinjaman asli (Gudang Peminjam → Gudang Pemberi). Gudang tidak dipilih ulang.</div>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Tutup form return" data-testid="loan-return-picker-close"><X className="h-4 w-4" /></Button>
      </div>
      <div className="space-y-3 p-4">
        <div className="max-w-xs"><Field label="Tanggal Return"><DatePicker value={date} onChange={setDate} testid="loan-return-date" /></Field></div>
        {error && <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" data-testid="loan-return-error"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
        {loading && <div className="rounded-lg border p-5 text-center text-sm text-muted-foreground">Memuat baris pinjaman...</div>}
        {!loading && !error && rows.length === 0 && <div className="rounded-lg border p-5 text-center text-sm text-muted-foreground" data-testid="loan-return-empty">Semua baris sudah dikembalikan.</div>}
        <div className="space-y-2">
          {rows.map((r, i) => {
            const id = r.loan_line_id; const checked = id in sel; const issue = issues[id];
            return (
              <div key={id} className={`grid grid-cols-1 gap-3 rounded-lg border p-3 transition-colors md:grid-cols-[auto_1fr_auto] md:items-center ${checked ? "border-primary/40 bg-primary/5" : "bg-background"} ${issue ? "border-destructive/60" : ""}`} data-testid={`loan-return-row-${i}`}>
                <Checkbox checked={checked} onCheckedChange={() => toggle(r)} aria-label={`Pilih ${r.item_name}`} data-testid={`loan-return-check-${i}`} />
                <div className="min-w-0 space-y-1">
                  <div className="text-sm font-medium"><span className="font-mono text-xs text-muted-foreground">{r.item_code}</span> {r.item_name}</div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>Pinjam: {r.from_name || "-"} <ArrowRight className="inline h-3 w-3" /> {r.to_name || "-"}</span>
                    <span className="font-medium text-foreground" data-testid={`loan-return-direction-${i}`}>Arah Return: {r.return_direction}</span>
                    {r.project_name && <span>Project: {r.project_name}</span>}
                    {r.unit_name && <span>Unit/Aset: {r.unit_name}</span>}
                  </div>
                  <div className="text-xs tabular-nums text-muted-foreground">Qty Pinjam {num(r.qty)} · Sudah Kembali {num(r.returned)} · <span className="font-semibold text-foreground" data-testid={`loan-return-outstanding-${i}`}>Outstanding {num(r.outstanding)}</span> {r.unit || ""}</div>
                </div>
                <div className="w-full md:w-36">
                  <Input type="number" step="any" min="0" inputMode="decimal" disabled={!checked} value={checked ? sel[id] : ""} placeholder={String(r.outstanding)}
                    onChange={(e) => setSel((s) => ({ ...s, [id]: e.target.value }))} aria-invalid={!!issue}
                    className={`h-10 text-right ${issue ? "border-destructive focus-visible:ring-destructive" : ""}`} data-testid={`loan-return-qty-${i}`} />
                  {issue && <div className="mt-1 text-xs text-destructive" data-testid={`loan-return-issue-${i}`}>{issue}</div>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex flex-col-reverse gap-2 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-muted-foreground">{picked.length ? `${picked.length} baris dipilih` : "Pilih baris yang dikembalikan"}</div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose} data-testid="loan-return-cancel">Batal</Button>
            <Button onClick={submit} disabled={blocked || saving} data-testid="loan-return-submit"><Undo2 className="mr-2 h-4 w-4" />{saving ? "Memproses..." : `Posting Return (${picked.length})`}</Button>
          </div>
        </div>
      </div>
    </section>
  );
}
