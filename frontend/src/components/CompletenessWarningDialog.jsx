import { useCallback, useState } from "react";
import { Button } from "@/components/ui/button";
import { AlertTriangle } from "lucide-react";

/**
 * Reusable, NON-BLOCKING completeness warning modal (amber styling).
 * Shows specific missing fields grouped by Header / Item and lets the user
 * either go back and complete, or proceed with the transaction anyway.
 */
export function CompletenessWarningDialog({ open, warnings, onCancel, onProceed }) {
  if (!open || !warnings) return null;
  const header = warnings.header || [];
  const items = warnings.items || [];
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4" role="dialog" aria-modal="true" data-testid="completeness-warning">
      <div className="absolute inset-0 bg-black/40" onClick={onCancel} />
      <div className="relative z-10 w-full max-w-lg overflow-hidden rounded-xl border border-amber-300 bg-card shadow-2xl">
        <div className="flex items-start gap-3 border-b border-amber-200 bg-amber-50 px-5 py-4">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-600">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <h3 className="font-head text-base font-semibold text-amber-900">Ada data yang belum lengkap</h3>
            <p className="mt-0.5 text-sm text-amber-700">Periksa data berikut sebelum melanjutkan.</p>
          </div>
        </div>

        <div className="max-h-[50vh] overflow-y-auto px-5 py-4 space-y-4 text-sm">
          {header.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Header</div>
              <ul className="space-y-1">
                {header.map((m, i) => (
                  <li key={`h-${i}`} className="flex items-start gap-2 text-amber-900">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                    <span>{m}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {items.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Item</div>
              <ul className="space-y-1">
                {items.map((m, i) => (
                  <li key={`i-${i}`} className="flex items-start gap-2 text-amber-900">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                    <span>{m}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="pt-1 text-muted-foreground">
            Data tersebut belum lengkap. Anda tetap dapat melanjutkan transaksi ini.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 border-t bg-muted/30 px-5 py-3">
          <Button variant="outline" onClick={onCancel} data-testid="warning-back">Kembali Lengkapi</Button>
          <Button className="bg-amber-500 text-white hover:bg-amber-600" onClick={onProceed} data-testid="warning-proceed">Tetap Simpan</Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Hook that wires the warning modal to any action.
 *   const { confirm, dialog } = useCompletenessWarning();
 *   confirm(warnings, () => doSave());  // proceeds immediately if no warnings
 * Render {dialog} once in the component tree.
 */
export function useCompletenessWarning() {
  const [state, setState] = useState(null); // { warnings, onProceed }

  const confirm = useCallback((warnings, onProceed) => {
    if (!warnings || !warnings.hasAny) { onProceed(); return; }
    setState({ warnings, onProceed });
  }, []);

  const close = useCallback(() => setState(null), []);
  const proceed = useCallback(() => {
    const cb = state?.onProceed;
    setState(null);
    if (cb) cb();
  }, [state]);

  const dialog = (
    <CompletenessWarningDialog open={!!state} warnings={state?.warnings} onCancel={close} onProceed={proceed} />
  );

  return { confirm, dialog };
}
