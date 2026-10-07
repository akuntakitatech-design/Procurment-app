import { Lock } from "lucide-react";
import { Combobox } from "@/components/Combobox";
import { DIVISION_REQUIRED_MSG } from "@/lib/txnValidation";

/**
 * Field Divisi wajib untuk form transaksi.
 * - label "Divisi *"
 * - state error (border merah + pesan) saat user mencoba Simpan/Post tanpa Divisi
 * - locked: Divisi diwarisi dari dokumen sumber dan tidak dapat diganti
 */
export function DivisionField({ options, value, onChange, disabled = false, locked = false, lockedHint, error, testid = "division-field" }) {
  const message = error === true ? DIVISION_REQUIRED_MSG : error;
  return (
    <div className="space-y-1.5" data-testid={testid}>
      <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Divisi <span className="text-destructive" aria-hidden="true">*</span>
        {locked && <Lock className="ml-1 inline h-3 w-3 align-[-2px]" aria-label="Terkunci" />}
      </label>
      <div title={locked ? (lockedHint || "Divisi mengikuti dokumen sumber dan tidak dapat diubah.") : undefined}>
        <Combobox options={options || []} value={value || ""} onChange={onChange} disabled={disabled || locked}
          invalid={!!message} testid={`${testid}-select`} placeholder="Pilih Divisi..." />
      </div>
      {locked && !message && <p className="text-[11px] text-muted-foreground" data-testid={`${testid}-locked-hint`}>{lockedHint || "Divisi mengikuti dokumen sumber dan tidak dapat diubah."}</p>}
      {message && <p role="alert" className="text-xs font-medium text-destructive" data-testid={`${testid}-error`}>{message}</p>}
    </div>
  );
}
