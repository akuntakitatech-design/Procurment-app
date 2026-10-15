// F2 — Audit READ-ONLY kesiapan PPN (go-live): Master Pajak belum lengkap + Supplier Non-PKP berisiko.
// Tidak mengubah data apa pun; koreksi dilakukan Accounting/Purchasing lewat Master Pajak / Master Supplier.
import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";

export function TaxReadinessPanel() {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const load = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    api.get("/po/tax-readiness").then((r) => setState({ data: r.data, error: null, loading: false }))
      .catch((e) => setState({ data: null, error: e.response?.status === 403 ? null : apiError(e.response?.data?.detail) || "Gagal memuat audit PPN", loading: false, hidden: e.response?.status === 403 }));
  }, []);
  useEffect(() => { load(); }, [load]);
  if (state.hidden) return null;
  const d = state.data;
  const taxes = d?.incomplete_taxes || [];
  const sups = d?.non_pkp_suppliers || [];
  const ready = d?.ready;
  return <Collapsible defaultOpen={false} className="mb-4 rounded-xl border bg-card shadow-sm" data-testid="tax-readiness-panel">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
      <CollapsibleTrigger className="flex min-h-[44px] flex-1 items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md" data-testid="tax-readiness-toggle">
        {state.loading ? <Skeleton className="h-5 w-5 rounded-full" /> : ready ? <ShieldCheck className="h-5 w-5 text-emerald-600" /> : <TriangleAlert className="h-5 w-5 text-amber-600" />}
        <span><span className="block font-head text-sm font-semibold">Audit Kesiapan PPN (read-only)</span>
          <span className="block text-xs text-muted-foreground" data-testid="tax-readiness-summary">{state.loading ? "Memeriksa…" : state.error ? "Audit gagal dimuat" : ready ? "Siap: semua Jenis PPN lengkap dan tidak ada Supplier Non-PKP berisiko." : `${taxes.length} Jenis PPN belum lengkap · ${sups.length} Supplier Non-PKP perlu dicek`}</span></span>
        <ChevronDown className="ml-auto h-4 w-4 text-muted-foreground" />
      </CollapsibleTrigger>
      <Button type="button" variant="ghost" size="sm" onClick={load} disabled={state.loading} data-testid="tax-readiness-refresh"><RefreshCw className="mr-1 h-3.5 w-3.5" />Periksa ulang</Button>
    </div>
    <CollapsibleContent className="space-y-4 border-t px-4 py-3 text-sm">
      {state.error && <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive" role="alert" data-testid="tax-readiness-error">{state.error}</div>}
      <section><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Jenis PPN belum lengkap</h4>
        {taxes.length === 0 ? <p className="text-xs text-muted-foreground" data-testid="tax-readiness-taxes-empty">Tidak ada.</p> :
          <ul className="space-y-1" data-testid="tax-readiness-taxes">{taxes.map((t) => <li key={t.id} className="rounded-md border border-dashed px-3 py-2 text-xs"><span className="font-semibold">{t.code} · {t.name}</span> — kurang: {t.issues.join(", ")}</li>)}</ul>}
      </section>
      <section><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Supplier Non-PKP yang perlu dicek</h4>
        {sups.length === 0 ? <p className="text-xs text-muted-foreground" data-testid="tax-readiness-suppliers-empty">Tidak ada.</p> :
          <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="tax-readiness-suppliers"><thead><tr className="text-left text-muted-foreground"><th className="py-1 pr-3">Supplier</th><th className="py-1 pr-3">Temuan</th><th className="py-1 text-right">PO ber-PPN</th></tr></thead>
            <tbody>{sups.map((s) => <tr key={s.id} className="border-t align-top"><td className="py-1.5 pr-3"><span className="font-mono font-semibold">{s.code}</span> {s.name}</td><td className="py-1.5 pr-3">{s.reasons.join(" · ")}{s.po_numbers.length > 0 && <div className="text-muted-foreground">{s.po_numbers.join(", ")}{s.po_count > s.po_numbers.length ? ` +${s.po_count - s.po_numbers.length} lainnya` : ""}</div>}</td><td className="py-1.5 text-right tabular-nums">{s.po_count}</td></tr>)}</tbody></table></div>}
        <p className="mt-2 text-[11px] text-muted-foreground">Supplier Non-PKP tidak dapat dikenakan PPN pada PO baru. Bila supplier sebenarnya PKP, perbaiki status PKP di Master Supplier; bila Non-PKP, kosongkan Default Pajak-nya. PO lama tidak diubah.</p>
      </section>
    </CollapsibleContent>
  </Collapsible>;
}
