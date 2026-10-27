// F2 — Perlakuan PPN per baris PO (Tax Engine v2). Backend = sumber perhitungan resmi:
// semua nominal di sini berasal dari POST /api/po/tax-preview (draft) atau nilai tersimpan dokumen (view).
// Frontend TIDAK menghitung nominal pajak sendiri.
import { useEffect, useMemo, useRef, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from "@/components/ui/sheet";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Combobox } from "@/components/Combobox";
import { buildTaxPreviewPayload, mapPreviewByIndex } from "@/lib/poTaxPayload";
import { poV2SummaryRows, poTaxGroupRows, fmtIdr, LINE_AMOUNT_LABEL } from "@/lib/poTaxPrint";
import { ChevronDown, RefreshCw, Lock } from "lucide-react";

export const MODE_LABEL = { EXCLUDE: "Exclude", INCLUDE: "Include", NONE: "Tanpa PPN" };
const MODE_HINT = "Exclude: PPN ditambahkan · Include: harga sudah termasuk PPN · Tanpa PPN: tidak dikenakan.";
const FAC_SHORT = { TIDAK_DIPUNGUT: "Tidak Dipungut", DTP: "DTP", DIBEBASKAN: "Dibebaskan" };
export const rp2 = (n) => (n == null || n === "" ? "–" : Number(n).toLocaleString("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

/** Jenis PPN dari Master Pajak (label, kelengkapan, masa berlaku pada tanggal PO). */
export function useTaxOptions(date, enabled = true) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    api.get("/po/tax-options", { params: { date: date ? String(date).slice(0, 10) : undefined } }).then((r) => live && setItems(r.data.items || [])).catch(() => live && setItems([]));
    return () => { live = false; };
  }, [date, enabled]);
  return items;
}

/** Preview resmi backend (debounce). Tidak menulis apa pun. */
export function usePoTaxPreview({ h, lines, poId, enabled }) {
  const [state, setState] = useState({ data: null, error: null, loading: false });
  const seq = useRef(0);
  const [nonce, setNonce] = useState(0);
  const payload = useMemo(() => buildTaxPreviewPayload({ h, lines, poId }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [poId, h.supplier_id, h.date, h.division_id, h.final_discount_type, h.final_discount_value, lines]);
  const sig = JSON.stringify(payload);
  useEffect(() => {
    if (!enabled || !payload.lines.length) { setState({ data: null, error: null, loading: false }); return; }
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    const t = setTimeout(() => {
      api.post("/po/tax-preview", payload).then((r) => { if (my === seq.current) setState({ data: r.data, error: null, loading: false }); })
        .catch((e) => { if (my === seq.current) setState({ data: null, error: apiError(e.response?.data?.detail) || "Gagal menghitung PPN", loading: false }); });
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, enabled, nonce]);
  // baris preview dipetakan ke indeks baris form (baris tanpa barang dilewati)
  const byIndex = useMemo(() => mapPreviewByIndex(lines, state.data), [lines, state.data]);
  return { ...state, byIndex, retry: () => setNonce((n) => n + 1) };
}

export function chipText(l, opt) {
  const mode = l.tax_mode || "NONE";
  if (mode === "NONE") return "Tanpa PPN";
  const fac = l.tax_facility || opt?.facility;
  const trx = l.tax_trx_code || opt?.trx_code;
  const name = opt?.name || l.tax_name || "Pilih Jenis PPN";
  return `${MODE_LABEL[mode]} · ${FAC_SHORT[fac] || name}${trx ? ` · ${trx}` : ""}`;
}

const chipTone = (l) => {
  const mode = l.tax_mode || "NONE";
  if (mode === "NONE") return "border-border bg-muted/60 text-muted-foreground";
  if (FAC_SHORT[l.tax_facility]) return "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200";
  if (mode === "INCLUDE") return "border-violet-300 bg-violet-50 text-violet-800 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-200";
  return "border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200";
};

/** Chip perlakuan PPN baris (klik -> drawer). */
export function PoTaxChip({ line, index, options, onOpen, disabled }) {
  const opt = options.find((o) => o.id === line.tax_id);
  return <button type="button" disabled={disabled} onClick={() => onOpen(index)} data-testid={`po-tax-chip-${index}`} aria-label={`Ubah perlakuan PPN baris ${index + 1}`}
    className={`inline-flex min-h-[36px] max-w-full items-center truncate rounded-full border px-3 py-1 text-xs font-semibold transition-[background-color,box-shadow] duration-150 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-70 ${chipTone({ ...line, tax_facility: line.tax_facility || opt?.facility })}`}>
    {disabled && <Lock className="mr-1 h-3 w-3" />}{chipText(line, opt)}
  </button>;
}

/** Drawer: 1. Mode harga · 2. Jenis transaksi PPN (master Accounting). PPnBM belum aktif (F2). */
export function PoTaxDrawer({ open, line, index, itemName, options, supplierPkp, onClose, onApply }) {
  const [draft, setDraft] = useState({ tax_mode: "EXCLUDE", tax_id: "" });
  useEffect(() => { if (open && line) setDraft({ tax_mode: line.tax_mode || "NONE", tax_id: line.tax_id || "" }); }, [open, line]);
  const usable = options.filter((o) => o.ready && o.valid_on_date);
  const blocked = options.filter((o) => !(o.ready && o.valid_on_date));
  const sel = options.find((o) => o.id === draft.tax_id);
  const facIncl = draft.tax_mode === "INCLUDE" && sel && sel.facility !== "NORMAL";
  const invalid = draft.tax_mode !== "NONE" && (!sel || !sel.ready || !sel.valid_on_date || facIncl);
  return <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
    <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto" data-testid="po-tax-drawer">
      <SheetHeader><SheetTitle className="font-head">Perlakuan PPN</SheetTitle><SheetDescription>Baris {index + 1}{itemName ? ` · ${itemName}` : ""}</SheetDescription></SheetHeader>
      <div className="mt-5 space-y-5">
        {!supplierPkp && <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100" data-testid="po-tax-nonpkp-note">Supplier Non-PKP — seluruh baris Tanpa PPN. Koreksi status PKP melalui Master Supplier.</div>}
        <section><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">1 · Mode harga</div>
          <div className="grid grid-cols-3 overflow-hidden rounded-md border" role="radiogroup" aria-label="Mode harga">
            {["EXCLUDE", "INCLUDE", "NONE"].map((m) => <button key={m} type="button" role="radio" aria-checked={draft.tax_mode === m} disabled={!supplierPkp && m !== "NONE"}
              onClick={() => setDraft((d) => ({ ...d, tax_mode: m, tax_id: m === "NONE" ? "" : d.tax_id }))} data-testid={`po-tax-mode-${m.toLowerCase()}`}
              className={`min-h-[44px] px-2 text-sm font-semibold transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${draft.tax_mode === m ? "bg-primary text-primary-foreground" : "bg-background hover:bg-accent"}`}>{MODE_LABEL[m]}</button>)}
          </div><p className="mt-2 text-xs text-muted-foreground">{MODE_HINT}</p></section>
        {draft.tax_mode !== "NONE" && <section><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">2 · Jenis transaksi PPN (kode faktur dari Master Accounting)</div>
          {usable.length === 0 && <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground" data-testid="po-tax-no-option">Belum ada Jenis PPN lengkap yang berlaku pada tanggal PO. Lengkapi Master Pajak.</p>}
          <RadioGroup value={draft.tax_id} onValueChange={(v) => setDraft((d) => ({ ...d, tax_id: v }))} className="space-y-2">
            {usable.map((o) => { const dis = draft.tax_mode === "INCLUDE" && o.facility !== "NORMAL"; return <label key={o.id} htmlFor={`taxopt-${o.id}`} className={`flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors duration-150 hover:bg-accent/50 ${draft.tax_id === o.id ? "border-primary bg-primary/5" : ""} ${dis ? "cursor-not-allowed opacity-50" : ""}`} data-testid={`po-tax-option-${o.id}`}>
              <RadioGroupItem id={`taxopt-${o.id}`} value={o.id} disabled={dis} className="mt-0.5" />
              <span className="min-w-0"><span className="block text-sm font-semibold">{o.label}</span><span className="block text-xs text-muted-foreground">{o.facility !== "NORMAL" ? "PPN terutang dihitung, tidak ditagih (fasilitas)" : `Tarif efektif ${Number(o.effective_rate).toLocaleString("id-ID")}%`}{dis ? " · tidak dapat dikombinasikan dengan Include" : ""}{o.notes ? ` · ${o.notes}` : ""}</span></span></label>; })}
          </RadioGroup>
          {blocked.length > 0 && <Collapsible className="mt-3"><CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-xs font-semibold text-muted-foreground hover:bg-accent" data-testid="po-tax-blocked-toggle">Tidak dapat dipilih ({blocked.length})<ChevronDown className="h-4 w-4" /></CollapsibleTrigger>
            <CollapsibleContent className="mt-2 space-y-1">{blocked.map((o) => <div key={o.id} className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground"><span className="font-semibold text-foreground">{o.name || o.code}</span> — {!o.ready ? `Belum lengkap: ${o.issues.join(", ")}` : "Tidak berlaku pada tanggal PO"}</div>)}</CollapsibleContent></Collapsible>}
        </section>}
        <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">Pengaturan lanjutan (PPnBM) belum diaktifkan sampai Vendor Invoice mendukungnya. Status PPN Masukan diatur Accounting.</div>
      </div>
      <SheetFooter className="mt-6 gap-2"><Button variant="outline" onClick={onClose} data-testid="po-tax-cancel">Batal</Button><Button onClick={() => onApply(draft)} disabled={invalid} data-testid="po-tax-apply">Terapkan</Button></SheetFooter>
    </SheetContent>
  </Sheet>;
}

/** Default header: mode + Jenis PPN untuk baris baru (+ terapkan ke semua baris). */
export function PoTaxDefaults({ mode, taxId, options, supplierPkp, disabled, onChange, onApplyAll }) {
  const usable = options.filter((o) => o.ready && o.valid_on_date);
  return <div className="grid grid-cols-1 gap-3 border-t border-dashed pt-4 md:grid-cols-[auto_minmax(240px,360px)_auto_1fr] md:items-start" data-testid="po-tax-defaults">
    <div><div className="mb-1 text-sm font-medium">Default Pajak Baris — Mode</div><div className="inline-grid h-11 grid-cols-3 overflow-hidden rounded-md border md:h-9">
      {["EXCLUDE", "INCLUDE", "NONE"].map((m) => <button key={m} type="button" disabled={disabled || (!supplierPkp && m !== "NONE")} onClick={() => onChange({ mode: m, taxId: m === "NONE" ? "" : taxId })} aria-pressed={mode === m} data-testid={`po-tax-default-mode-${m.toLowerCase()}`}
        className={`h-full min-h-[34px] px-3 text-sm font-semibold transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${mode === m ? "bg-primary text-primary-foreground" : "bg-background hover:bg-accent"}`}>{MODE_LABEL[m]}</button>)}
    </div></div>
    <div><div className="mb-1 text-sm font-medium">Default Jenis PPN</div><Combobox testid="po-tax-default-type" disabled={disabled || mode === "NONE" || !supplierPkp} options={usable.map((o) => ({ value: o.id, label: o.label }))} value={taxId || ""} onChange={(v) => onChange({ mode, taxId: v })} placeholder="Pilih Jenis PPN" /></div>
    <div><div className="mb-1 hidden text-sm md:block" aria-hidden="true">&nbsp;</div><Button type="button" variant="outline" disabled={disabled || !supplierPkp} onClick={onApplyAll} data-testid="po-tax-apply-all">Terapkan ke semua baris</Button></div>
    <p className="text-xs text-muted-foreground md:pt-6" data-testid="po-tax-defaults-hint">{supplierPkp ? "Default berlaku untuk baris baru; ubah per baris lewat chip Perlakuan PPN." : "Supplier Non-PKP: seluruh baris Tanpa PPN (dikunci). Koreksi status PKP di Master Supplier."}</p>
  </div>;
}

/** Rincian pajak satu baris (nilai backend). */
export function PoTaxLineDetail({ v, line }) {
  if (!v) return <p className="mb-2 text-muted-foreground">Rincian PPN tersedia setelah dihitung server.</p>;
  const f = `${v.tax_dpp_factor_num || 1}/${v.tax_dpp_factor_den || 1}`;
  const Row = ({ k, val, note }) => <div className="flex justify-between gap-4"><span className="text-muted-foreground">{k}{note ? <span className="ml-1 italic">{note}</span> : null}</span><span className="tabular-nums font-medium">{val}</span></div>;
  return <div className="mb-2 grid grid-cols-1 gap-x-8 gap-y-1 md:grid-cols-2" data-testid="po-tax-line-detail">
    <Row k="Nilai setelah diskon" val={fmtIdr(v.net_amount)} />
    <Row k={LINE_AMOUNT_LABEL} note={line.tax_mode === "INCLUDE" ? "(dikeluarkan dari harga Include)" : ""} val={fmtIdr(v.dpp)} />
    {v.taxable && <Row k="DPP Nilai Lain" note={`DPP × ${f}`} val={fmtIdr(v.dpp_other)} />}
    {v.taxable && <Row k="PPN" note={`DPP Nilai Lain × ${v.tax_rate}%${Number(v.tax_facility_amount) ? " — fasilitas, tidak ditagih" : ""}`} val={fmtIdr(Number(v.tax_facility_amount) ? v.tax_facility_amount : v.tax_amount)} />}
    <Row k="Jumlah termasuk PPN" val={fmtIdr(v.total)} />
    <Row k="Dasar biaya perolehan (DO)" note="= DPP; PPN tidak dikapitalisasi" val={fmtIdr(v.dpp)} />
  </div>;
}

/** Ringkasan PO dari nilai backend (preview draft atau nilai tersimpan). Baris & istilah = cetak PO (poV2SummaryRows). */
const SUM_TESTID = { gross: "po-sum-gross", item_disc: "po-sum-item-disc", final_disc: "po-sum-final-disc", after_disc: "po-sum-after-disc", before_ppn: "po-sum-before-ppn",
  non_ppn: "po-sum-non-ppn", dpp_other: "po-sum-dpp-other", ppn: "po-sum-tax", ppn_facility: "po-sum-tax-facility", ppnbm: "po-sum-ppnbm", grand: "po-sum-grand" };
export function PoTaxSummary({ totals, loading, error, onRetry, finalDiscount, stored }) {
  const t = totals || {};
  const busy = loading && !totals;
  const rows = poV2SummaryRows(t, { form: !!finalDiscount });
  const groups = poTaxGroupRows(t);
  const val = (r) => (busy ? <Skeleton className={r.grand ? "h-5 w-32" : "h-4 w-24"} /> : totals == null ? "–" : `${r.neg && r.value ? "−" : ""}${fmtIdr(r.value)}`);
  return <div className="w-full rounded-lg border bg-card p-4 text-sm shadow-sm space-y-1.5" data-testid="po-total-summary" aria-busy={loading}>
    <div className="mb-1 flex items-center justify-between gap-2"><span className="font-head font-semibold">Ringkasan PO</span><span className="text-[11px] text-muted-foreground" data-testid="po-tax-source">{stored ? "Nilai tersimpan · IDR" : loading ? "Menghitung di server…" : "Dihitung server · IDR"}</span></div>
    {error && <div className="flex items-start justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive" role="alert" data-testid="po-tax-preview-error"><span>{error}</span>{onRetry && <Button type="button" size="sm" variant="ghost" className="h-7 px-2" onClick={onRetry} data-testid="po-tax-retry"><RefreshCw className="mr-1 h-3 w-3" />Ulangi</Button>}</div>}
    {rows.map((r) => {
      if (r.grand) return <div key={r.key} className="border-t-2 border-foreground/70 pt-2 text-base"><div className="flex items-center justify-between"><span className="font-bold">GRAND TOTAL</span><span className="font-bold tabular-nums" data-testid={SUM_TESTID.grand}>{val(r)}</span></div></div>;
      if (r.key === "final_disc" && finalDiscount) return <div key={r.key} className="space-y-1">{finalDiscount}<div className="flex items-center justify-between text-muted-foreground"><span className="pl-1 text-xs italic">= Diskon Final</span><span className="tabular-nums text-destructive" data-testid={SUM_TESTID.final_disc}>{val(r)}</span></div></div>;
      const sep = r.key === "after_disc" || (r.key === "before_ppn" && !rows.some((x) => x.key === "after_disc"));
      return <div key={r.key} className={`flex items-center justify-between gap-3 ${sep ? "border-t pt-1.5" : ""} ${r.sub ? "pl-3 text-xs text-muted-foreground" : r.strong ? "" : "text-muted-foreground"}`}>
        <span className={r.strong ? "font-semibold text-foreground" : ""}>{r.sub ? "↳ " : ""}{r.label}{r.hint && <span className="block text-[11px] font-normal text-muted-foreground">{r.hint}</span>}</span>
        <span className={`tabular-nums ${r.neg && r.value ? "text-destructive" : ""} ${r.strong ? "font-semibold text-foreground" : ""}`} data-testid={SUM_TESTID[r.key]}>{r.sub && r.key === "ppn_facility" ? <>({val(r)})</> : val(r)}</span></div>;
    })}
    {groups.length > 0 && <Collapsible><CollapsibleTrigger className="mt-2 flex w-full items-center justify-between rounded-md border px-3 py-2 text-xs font-semibold transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" data-testid="po-tax-groups-toggle">Rincian pajak per kelompok<ChevronDown className="h-4 w-4" /></CollapsibleTrigger>
      <CollapsibleContent className="mt-2 overflow-x-auto"><table className="w-full text-xs" data-testid="po-tax-groups"><thead><tr className="text-left text-muted-foreground"><th className="py-1 pr-2">Kelompok</th><th className="py-1 pr-2 text-right">DPP</th><th className="py-1 pr-2 text-right">DPP Nilai Lain</th><th className="py-1 text-right">PPN</th></tr></thead>
        <tbody>{groups.map((g) => <tr key={g.key} className="border-t"><td className="py-1 pr-2">{g.label}</td><td className="py-1 pr-2 text-right tabular-nums">{fmtIdr(g.dpp)}</td><td className="py-1 pr-2 text-right tabular-nums">{fmtIdr(g.dpp_other)}</td><td className="py-1 text-right tabular-nums">{g.facility ? <span title="Fasilitas — tidak ditagih">0 <span className="text-muted-foreground">({fmtIdr(g.facility)})</span></span> : fmtIdr(g.ppn)}</td></tr>)}
          {Number(t.non_ppn_total) > 0 && <tr className="border-t text-muted-foreground"><td className="py-1 pr-2">Barang Tanpa PPN</td><td className="py-1 pr-2 text-right tabular-nums">{fmtIdr(t.non_ppn_total)}</td><td className="py-1 pr-2 text-right">–</td><td className="py-1 text-right">–</td></tr>}</tbody></table>
        <p className="mt-2 text-[11px] text-muted-foreground">PO dihitung presisi sen (HALF_UP). Pembulatan faktur pajak ke rupiah dilakukan pada tahap Invoice.</p></CollapsibleContent></Collapsible>}
  </div>;
}
