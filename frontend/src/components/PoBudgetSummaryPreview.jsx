import { useEffect, useMemo, useRef, useState } from "react";
import api from "@/lib/api";
import { rupiah } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw } from "lucide-react";

// Presentation-only mapping of the backend canonical decision values.
// The status/policy value itself always comes from the backend (evaluate_budget).
const STATUS_LABEL = { ok: "Within Budget", warning: "Warning", block: "Over Budget" };
const statusTone = (st) => (st === "block" ? "text-destructive" : st === "warning" ? "text-amber-600" : "text-emerald-600");
const StatusIcon = ({ st }) => (st === "ok" ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />);

// ---------------------------------------------------------------------------
// CP5A-3 — Pre-Save SPK Budget Preview.
// Reactive, read-only projection of budget impact per SPK for an editable PO
// (new OR Draft edit). All numbers come from POST /spk-allocations/po/preview-budget
// which reuses the exact same _distribute + evaluate_budget logic as the eventual
// Approved commitment. Non-SPK is excluded. Human-readable SPK numbers only.
// ---------------------------------------------------------------------------
export function PoBudgetSummaryPreview({ lines, allocMap, excludePoId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const seqRef = useRef(0);

  // Build the preview payload from the current (possibly unsaved) PO lines.
  // - unsaved line  -> PO-stage allocation comes from l._inheritPreview.allocations
  // - saved/editing  -> allocation comes from allocMap[l.id] (useDocAllocations)
  const payloadLines = useMemo(() => {
    return (lines || [])
      .filter((l) => l.item_id)
      .map((l, i) => {
        const allocs = l.id ? (allocMap?.[l.id]?.allocations || []) : (l._inheritPreview?.allocations || []);
        return {
          key: l.id || `tmp-${i}`,
          qty: Number(l.qty) || 0,
          price: Number(l.price) || 0,
          discount: Number(l.discount) || 0,
          tax: Number(l.tax) || 0,
          allocations: (allocs || [])
            .map((a) => ({ spk_id: a.spk_id, allocated_qty: Number(a.allocated_qty) || 0 }))
            .filter((a) => a.spk_id && a.allocated_qty > 0),
        };
      });
  }, [lines, allocMap]);

  const hasItems = payloadLines.length > 0;
  const hasAnyAlloc = payloadLines.some((x) => x.allocations.length > 0);
  const sig = useMemo(() => JSON.stringify(payloadLines) + "|" + (excludePoId || "") + "|" + reloadKey, [payloadLines, excludePoId, reloadKey]);

  useEffect(() => {
    if (!hasAnyAlloc) {
      setData(null);
      setError(false);
      setLoading(false);
      return;
    }
    const seq = ++seqRef.current;
    const ctrl = new AbortController();
    setLoading(true);
    const t = setTimeout(() => {
      api
        .post("/spk-allocations/po/preview-budget", { lines: payloadLines, exclude_po_id: excludePoId || null }, { signal: ctrl.signal })
        .then((r) => {
          if (seq !== seqRef.current) return; // stale response — ignore
          setData(r.data);
          setError(false);
          setLoading(false);
        })
        .catch((err) => {
          if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return; // superseded
          if (seq !== seqRef.current) return;
          setError(true);
          setLoading(false);
        });
    }, 350);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  if (!hasItems) return null;

  const perSpk = data?.per_spk || [];

  return (
    <div className="mt-3 rounded-lg border bg-muted/30 px-4 py-3" data-testid="po-budget-preview">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-semibold uppercase tracking-wider text-xs text-muted-foreground">Kontrol Budget SPK</span>
        {loading && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" data-testid="po-budget-preview-loading">
            <Loader2 className="h-3 w-3 animate-spin" />Memperbarui…
          </span>
        )}
      </div>

      {error ? (
        <div className="flex items-center gap-3 text-sm" data-testid="po-budget-preview-error">
          <span className="text-muted-foreground">Preview budget SPK belum dapat dimuat. Coba lagi.</span>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setReloadKey((k) => k + 1)} data-testid="po-budget-preview-reload">
            <RefreshCw className="h-3 w-3 mr-1" />Muat Ulang
          </Button>
        </div>
      ) : !hasAnyAlloc ? (
        <p className="text-sm text-muted-foreground" data-testid="po-budget-preview-empty">
          PO ini tidak memiliki alokasi budget SPK (seluruhnya Non-SPK).
        </p>
      ) : perSpk.length === 0 && !loading ? (
        <p className="text-sm text-muted-foreground" data-testid="po-budget-preview-empty">Belum ada alokasi SPK pada item PO.</p>
      ) : perSpk.length === 0 ? null : (
        <div className="overflow-x-auto rounded-md border bg-background">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr className="text-left text-xs uppercase text-muted-foreground">
                <th className="p-2">SPK</th>
                <th className="p-2 text-right">Budget</th>
                <th className="p-2 text-right">Commitment</th>
                <th className="p-2 text-right">PO Ini</th>
                <th className="p-2 text-right">Sisa Proyeksi</th>
                <th className="p-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {perSpk.map((s, i) => (
                <tr key={s.spk_number || i} className="border-t" data-testid={`po-budget-preview-row-${i}`}>
                  <td className="p-2">
                    <b>{s.spk_number}</b>
                    {s.project_name ? <div className="text-xs text-muted-foreground">{s.project_name}</div> : null}
                  </td>
                  <td className="p-2 text-right">{rupiah(s.current_procurement_budget)}</td>
                  <td className="p-2 text-right">{rupiah(s.existing_commitment)}</td>
                  <td className="p-2 text-right">{rupiah(s.po_amount)}</td>
                  <td className={`p-2 text-right font-semibold ${s.projected_remaining < 0 ? "text-destructive" : ""}`}>{rupiah(s.projected_remaining)}</td>
                  <td className={`p-2 font-semibold ${statusTone(s.status)}`}>
                    <span className="inline-flex items-center gap-1">
                      <StatusIcon st={s.status} />
                      {STATUS_LABEL[s.status] || s.status}
                      <span className="text-xs font-normal text-muted-foreground">({s.policy})</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
