import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { NumericInput } from "@/components/NumericInput";
import { rupiah } from "@/lib/format";
import { computeDp, dpRows } from "@/lib/poDp";

const TYPES = [["percentage", "Persentase (%)"], ["nominal", "Nominal (Rp)"]];

/** Editor Uang Muka / DP di ringkasan form PO (ketentuan pembayaran, belum transaksi). */
export function PoDpEditor({ h, setH, grand }) {
  const dp = computeDp(h, grand);
  const set = (patch) => setH({ ...h, ...patch });
  const type = h.dp_type === "nominal" ? "nominal" : "percentage";
  return (
    <div className="mt-2 space-y-2 border-t pt-2" data-testid="po-dp-section">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="po-dp-enabled" className="text-sm font-semibold">Uang Muka / DP</Label>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Menggunakan DP?</span>
          <Switch id="po-dp-enabled" checked={!!h.dp_enabled} onCheckedChange={(v) => set({ dp_enabled: v, dp_type: h.dp_type || "percentage" })} data-testid="po-dp-enabled" />
          <span className="w-7 font-medium text-foreground" data-testid="po-dp-enabled-label">{h.dp_enabled ? "Ya" : "Tidak"}</span>
        </div>
      </div>
      {h.dp_enabled && (
        <>
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Tipe DP</span>
            <div className="flex rounded-md border p-0.5" role="radiogroup" aria-label="Tipe DP">
              {TYPES.map(([k, label]) => (
                <button key={k} type="button" role="radio" aria-checked={type === k} onClick={() => set({ dp_type: k, dp_value: "" })}
                  className={`rounded px-2 py-1 text-xs font-semibold transition-colors ${type === k ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
                  data-testid={`po-dp-type-${k}`}>{label}</button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Nilai DP {type === "percentage" ? "(%)" : "(Rp)"}</span>
            <div className="w-[150px]"><NumericInput mode={type === "percentage" ? "quantity" : "money"} value={h.dp_value ?? ""} onChange={(v) => set({ dp_value: v })}
              className={`h-8 text-right ${dp.error ? "border-destructive" : ""}`} aria-invalid={!!dp.error} data-testid="po-dp-value" /></div>
          </div>
          <div className="flex items-center justify-between"><span className="text-muted-foreground">Nilai DP Terhitung</span><span className="tabular-nums font-semibold" data-testid="po-dp-amount">{dp.amount != null ? rupiah(dp.amount) : "-"}</span></div>
          <div className="flex items-center justify-between"><span className="text-muted-foreground">Sisa Pembayaran</span><span className="tabular-nums font-semibold" data-testid="po-dp-remaining">{dp.remaining != null ? rupiah(dp.remaining) : "-"}</span></div>
          {dp.error && <p className="text-xs text-destructive" role="alert" data-testid="po-dp-error">{dp.error}</p>}
        </>
      )}
      <div className="space-y-1">
        <Label htmlFor="po-payment-notes" className="text-xs text-muted-foreground">Keterangan Pembayaran (opsional)</Label>
        <Textarea id="po-payment-notes" rows={2} value={h.payment_notes || ""} onChange={(e) => set({ payment_notes: e.target.value })} placeholder="Contoh: DP dibayar setelah PO ditandatangani, pelunasan setelah barang diterima" className="text-sm" data-testid="po-payment-notes" />
      </div>
    </div>
  );
}

/** Baris DP pada tampilan PO tersimpan (mode lihat). */
export function PoDpRowsView({ doc, colSpan }) {
  return dpRows(doc).map((r) => (
    <tr key={r.key} className="bg-muted/30" data-testid={`po-view-${r.key}`}>
      <td colSpan={colSpan} className="p-2 text-right">{r.label}</td>
      <td className="p-2 text-right tabular-nums">{rupiah(r.amount)}</td>
    </tr>
  ));
}

export function PoPaymentNotesView({ doc }) {
  if (!doc?.payment_notes) return null;
  return (
    <div className="mt-3 rounded-md border bg-muted/20 px-3 py-2 text-sm" data-testid="po-view-payment-notes">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Keterangan Pembayaran</div>
      <div className="whitespace-pre-wrap">{doc.payment_notes}</div>
    </div>
  );
}
