import { useEffect, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { NumericInput } from "@/components/NumericInput";
import { rupiah } from "@/lib/format";
import { computeDp, dpRows, dpPaymentStatus } from "@/lib/poDp";
import { useAuth } from "@/context/AuthContext";
import api from "@/lib/api";

const TYPES = [["percentage", "Persentase (%)"], ["nominal", "Nominal (Rp)"]];
const CARD = "w-full rounded-lg border bg-card p-4 text-sm shadow-sm";
const TITLE = "mb-2 flex items-center justify-between gap-2";
const NOTE = "Syarat pembayaran pada PO — bukan catatan pembayaran. Pembayaran DP dicatat di menu DP Supplier.";

/** Kartu KETENTUAN PEMBAYARAN di form PO: syarat Uang Muka (DP) + keterangan. Tidak ada di Ringkasan PO. */
export function PoDpEditor({ h, setH, grand, fmt = rupiah }) {
  const dp = computeDp(h, grand);
  const set = (patch) => setH({ ...h, ...patch });
  const type = h.dp_type === "nominal" ? "nominal" : "percentage";
  return (
    <div className={`${CARD} space-y-2`} data-testid="po-dp-section">
      <div className={TITLE}><span className="font-head font-semibold">Ketentuan Pembayaran</span></div>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="po-dp-enabled" className="text-sm font-semibold">Uang Muka (DP)</Label>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Mensyaratkan DP?</span>
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
                  className={`rounded px-2 py-1 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${type === k ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}
                  data-testid={`po-dp-type-${k}`}>{label}</button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">{type === "percentage" ? "DP (% dari Grand Total)" : "DP (Rp)"}</span>
            <div className="w-[150px]"><NumericInput mode={type === "percentage" ? "quantity" : "money"} value={h.dp_value ?? ""} onChange={(v) => set({ dp_value: v })}
              className={`h-8 text-right ${dp.error ? "border-destructive" : ""}`} aria-invalid={!!dp.error} data-testid="po-dp-value" /></div>
          </div>
          <div className="flex items-center justify-between"><span className="text-muted-foreground">Nilai DP</span><span className="tabular-nums font-semibold" data-testid="po-dp-amount">{dp.amount != null ? fmt(dp.amount) : "–"}</span></div>
          <div className="flex items-center justify-between"><span className="text-muted-foreground">Sisa setelah DP</span><span className="tabular-nums font-semibold" data-testid="po-dp-remaining">{dp.remaining != null ? fmt(dp.remaining) : "–"}</span></div>
          {dp.error && <p className="text-xs text-destructive" role="alert" data-testid="po-dp-error">{dp.error}</p>}
          <p className="text-[11px] text-muted-foreground">{NOTE}</p>
        </>
      )}
      <div className="space-y-1 border-t pt-2">
        <Label htmlFor="po-payment-notes" className="text-xs text-muted-foreground">Keterangan Pembayaran (opsional)</Label>
        <Textarea id="po-payment-notes" rows={2} value={h.payment_notes || ""} onChange={(e) => set({ payment_notes: e.target.value })} placeholder="Contoh: DP dibayar setelah PO ditandatangani, pelunasan setelah barang diterima" className="text-sm" data-testid="po-payment-notes" />
      </div>
    </div>
  );
}

/** Status pembayaran DP aktual (hanya bila berizin melihat DP Supplier). null = tidak diketahui. */
function useDpStatus(doc) {
  const { can } = useAuth();
  const [info, setInfo] = useState(null);
  const enabled = !!(doc?.id && doc?.dp_enabled && can("supplier_dp.view"));
  useEffect(() => {
    let alive = true;
    setInfo(null);
    if (enabled) api.get(`/supplier-dp/${doc.id}`).then((r) => alive && setInfo(r.data)).catch(() => alive && setInfo({ _unavailable: true }));
    return () => { alive = false; };
  }, [enabled, doc?.id, doc?.status]);
  return enabled ? info : null;
}

/** Kartu KETENTUAN PEMBAYARAN di detail PO: syarat DP (bukan pembayaran aktual) + status DP bila diketahui + keterangan. */
export function PoPaymentTermsView({ doc, fmt = rupiah, showAmount = true }) {
  const info = useDpStatus(doc);
  const rows = showAmount ? dpRows(doc) : [];
  if (!doc || (!doc.dp_enabled && !doc.payment_notes)) return null;
  const st = info && !info._unavailable ? dpPaymentStatus(info) : null;
  const tone = st?.key === "paid" ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200" : st?.key === "pending" ? "border-amber-300 bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200" : "border-slate-300 bg-slate-50 text-slate-700 dark:bg-slate-900 dark:text-slate-200";
  return (
    <div className={`${CARD} space-y-1.5`} data-testid="po-payment-terms">
      <div className={TITLE}><span className="font-head font-semibold">Ketentuan Pembayaran</span>
        {st && <Badge variant="outline" className={`text-[11px] ${tone}`} data-testid="po-dp-status">{st.label}</Badge>}</div>
      {doc.dp_enabled && !showAmount && <div className="text-muted-foreground" data-testid="po-view-dp">Uang Muka (DP) disyaratkan</div>}
      {rows.map((r) => (
        <div key={r.key} className="flex items-center justify-between gap-3" data-testid={`po-view-${r.key}`}>
          <span className="text-muted-foreground">{r.label}</span><span className="tabular-nums font-medium">{fmt(r.amount)}</span>
        </div>
      ))}
      {st?.key === "paid" && showAmount && <div className="flex items-center justify-between gap-3" data-testid="po-dp-paid"><span className="text-muted-foreground">DP sudah dibayar</span><span className="tabular-nums font-medium">{fmt(st.amount)}</span></div>}
      {doc.dp_enabled && <p className="text-[11px] text-muted-foreground">{NOTE}</p>}
      {doc.payment_notes && <div className="border-t pt-2" data-testid="po-view-payment-notes">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Keterangan Pembayaran</div>
        <div className="whitespace-pre-wrap">{doc.payment_notes}</div>
      </div>}
    </div>
  );
}
