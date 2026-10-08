import { AlertCircle, Lock, RotateCw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LOOKUP_LABELS, LOOKUP_MESSAGES } from "@/lib/lookupCore";

/**
 * Ringkasan status data referensi form (dari useMasters): gagal muat (error/auth) dengan tombol Muat ulang,
 * dan izin ditolak untuk field yang benar-benar dipakai form (`names`). Tidak tampil bila semua berhasil.
 */
export function LookupStatusAlert({ masters, names, testid = "lookup-status" }) {
  const relevant = (masters?.errors || []).filter((e) => !names || names.includes(e.name));
  const failed = relevant.filter((e) => e.state === "error" || e.state === "auth");
  const denied = relevant.filter((e) => e.state === "denied");
  if (!failed.length && !denied.length) return null;
  const label = (list) => list.map((e) => LOOKUP_LABELS[e.name] || e.name).join(", ");
  return (
    <div className="space-y-2" data-testid={testid}>
      {failed.length > 0 && (
        <Alert variant="destructive" data-testid={`${testid}-error`}>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{failed.some((e) => e.state === "auth") ? LOOKUP_MESSAGES.auth : LOOKUP_MESSAGES.error}</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>Data referensi belum termuat: {label(failed)}.</span>
            <Button type="button" variant="outline" size="sm" onClick={() => masters.retry()} data-testid={`${testid}-retry`}>
              <RotateCw className="mr-1.5 h-3.5 w-3.5" />Muat ulang
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {denied.length > 0 && (
        <Alert data-testid={`${testid}-denied`}>
          <Lock className="h-4 w-4" />
          <AlertTitle>{LOOKUP_MESSAGES.denied}</AlertTitle>
          <AlertDescription>Data referensi tanpa izin: {label(denied)}. Hubungi admin bila data ini diperlukan untuk transaksi.</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
