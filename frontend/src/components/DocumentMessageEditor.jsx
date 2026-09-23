import { useEffect, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { FileText, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

let cachedDefaults = null;

export async function getDocumentMessageDefaults(force = false) {
  if (!cachedDefaults || force) {
    const r = await api.get("/settings/document_messages");
    cachedDefaults = r.data?.modules || {};
  }
  return cachedDefaults;
}

export function clearDocumentMessageDefaultsCache() {
  cachedDefaults = null;
}

export async function saveDocumentMessage(module, id, text) {
  if (!module || !id) return;
  await api.put(`/document-message/${module}/${id}`, { document_message: text || "" });
}

export function DocumentMessageEditor({ module, value, onChange, readOnly = false, useDefault = false, title = "Pesan / Ketentuan Dokumen" }) {
  const [defaultText, setDefaultText] = useState("");
  const [loadingDefault, setLoadingDefault] = useState(false);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  valueRef.current = value;
  onChangeRef.current = onChange;

  useEffect(() => {
    let active = true;
    if (!useDefault) return () => { active = false; };
    setLoadingDefault(true);
    getDocumentMessageDefaults().then((mods) => {
      if (!active) return;
      const next = mods?.[module] || "";
      setDefaultText(next);
      if (valueRef.current == null && onChangeRef.current) onChangeRef.current(next);
    }).catch((e) => toast.error(apiError(e.response?.data?.detail) || "Gagal memuat pesan default")).finally(() => active && setLoadingDefault(false));
    return () => { active = false; };
  }, [module, useDefault]);

  const current = value == null ? "" : value;
  const reset = () => onChange && onChange(defaultText || "");

  return <div className="rounded-2xl border bg-card p-4 sm:p-5">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/8 text-primary ring-1 ring-primary/10"><FileText className="h-4.5 w-4.5" /></div>
        <div>
          <div className="font-head text-sm font-semibold">{title}</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Teks ini tersimpan sebagai snapshot pada transaksi. Perubahan pesan default di Pengaturan tidak mengubah dokumen lama.</p>
        </div>
      </div>
      {!readOnly && useDefault && <Button type="button" variant="outline" size="sm" onClick={reset} disabled={loadingDefault} className="rounded-xl shrink-0"><RotateCcw className="mr-2 h-3.5 w-3.5" />Gunakan Default</Button>}
    </div>
    {readOnly ? (
      <div className="mt-4 min-h-20 whitespace-pre-wrap rounded-xl bg-muted/25 p-4 text-sm leading-6 text-foreground/85">{current || <span className="text-muted-foreground">Tidak ada pesan / ketentuan pada dokumen ini.</span>}</div>
    ) : (
      <textarea
        value={current}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder="Tulis pesan, syarat & ketentuan, atau catatan yang akan tampil pada dokumen..."
        rows={12}
        className="mt-4 min-h-[220px] w-full resize-y rounded-xl border border-input bg-background px-3.5 py-3 text-sm leading-6 text-foreground outline-none transition focus:border-primary/50 focus:ring-2 focus:ring-primary/10"
      />
    )}
  </div>;
}
