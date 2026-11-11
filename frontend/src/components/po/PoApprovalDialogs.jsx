import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/**
 * Dialog catatan wajib (dipakai "Minta Revisi" dan "Tarik Approval").
 * Catatan minimal 5 karakter; nilainya dikirim ke backend yang juga memvalidasi.
 */
function NoteDialog({ open, onOpenChange, title, description, label, placeholder, cta, busy, onSubmit, testid }) {
  const [text, setText] = useState("");
  useEffect(() => { if (!open) setText(""); }, [open]);
  const ok = text.trim().length >= 5;
  const submit = async () => { if (!ok || busy) return; await onSubmit(text.trim()); };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) setText(""); onOpenChange(v); }}>
      <DialogContent className="max-w-lg" data-testid={`${testid}-dialog`}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <label className="text-sm font-medium" htmlFor={`${testid}-note`}>{label} *</label>
        <textarea
          id={`${testid}-note`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder={placeholder}
          data-testid={`${testid}-note`}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <p className="text-xs text-muted-foreground">Minimal 5 karakter. Catatan ini tersimpan di riwayat PO dan terlihat oleh purchasing.</p>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Batal</Button>
          <Button onClick={submit} disabled={!ok || busy} data-testid={`${testid}-submit`}>
            {busy ? "Menyimpan..." : cta}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Approver mengembalikan PO ke purchasing dengan catatan revisi (status PO -> Perlu Revisi). */
export function PoRevisionDialog({ poNo, ...rest }) {
  return (
    <NoteDialog
      {...rest}
      testid={rest.testid || "po-revision"}
      title="Minta Revisi PO"
      description={`${poNo ? `${poNo} — ` : ""}PO dikembalikan ke purchasing untuk diperbaiki, lalu diajukan ulang dari approval level 1.`}
      label="Catatan revisi"
      placeholder="contoh: Harga item 2 belum sesuai penawaran; mohon lampirkan No. Quotation terbaru."
      cta="Kirim Permintaan Revisi"
    />
  );
}

/** Admin/Director mencabut approval yang sudah diberikan agar isi PO dapat direvisi. */
export function PoRevokeDialog({ poNo, ...rest }) {
  return (
    <NoteDialog
      {...rest}
      testid={rest.testid || "po-revoke"}
      title="Tarik Approval PO"
      description={`${poNo ? `${poNo} — ` : ""}Approval yang sudah diberikan dibatalkan dan PO kembali menunggu approval mulai level 1.`}
      label="Alasan penarikan"
      placeholder="contoh: Nilai PO berubah setelah negosiasi ulang dengan vendor."
      cta="Tarik Approval"
    />
  );
}
