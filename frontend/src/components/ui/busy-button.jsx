import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Tombol aksi dengan status proses (mis. Simpan / Posting).
 * Saat `busy` aktif: tombol dinonaktifkan, ikon berputar, dan label diganti `busyLabel`
 * sehingga pengguna melihat prosesnya berjalan (tidak terkesan blank saat menunggu server).
 * Semua props lain diteruskan ke Button (variant, data-testid, dsb).
 */
export function BusyButton({ busy = false, busyLabel = "Menyimpan...", children, disabled, ...props }) {
  return (
    <Button {...props} disabled={disabled || busy} aria-busy={busy || undefined}>
      {busy ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          {busyLabel}
        </>
      ) : (
        children
      )}
    </Button>
  );
}

export default BusyButton;
