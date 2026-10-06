import { useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { num } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Combobox } from "@/components/Combobox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { ListTree, Trash2, Search } from "lucide-react";
import { toast } from "sonner";
import { applyRoReservation, mergeRoPicked, pullParams, roFormReservation } from "@/lib/sourceReservation";
export { applyRoReservation };

const EPS = 1e-6;
const n = (v) => Number(v) || 0;
const sum = (arr, k) => arr.reduce((a, x) => a + n(x[k]), 0);
const byMroDate = (a, b) => String(a.mro_date || "").localeCompare(String(b.mro_date || "")) || String(a.mro_no || "").localeCompare(String(b.mro_no || ""));

/** Satu sumber per baris MRO; qty dalam satuan dasar barang. */
const sourceFromPull = (r) => ({
  mro_id: r.mro_id, mro_no: r.mro_no, mro_date: r.mro_date, line_id: r.line_id,
  spk: r.spk || [], non_spk_qty: r.non_spk_qty, spk_label: r.spk_label || "Non-SPK",
  project_id: r.project_id, project_name: r.project_name, unit_id: r.unit_id, unit_name: r.unit_name, warehouse_id: r.warehouse_id, source_header: r.source_header || null,
  mro_qty: n(r.requested_base ?? r.requested), sudah_ro: n(r.processed_base ?? r.processed), sisa: n(r.outstanding_base ?? r.outstanding), qty: 0,
  db_sisa: n(r._db_outstanding_base ?? r.outstanding_base ?? r.outstanding), reserved: n(r._reserved_base),
});

/** Kelompokkan baris MRO per Divisi + Barang (MRO/SPK/Proyek/Unit boleh berbeda). Supplier bukan kunci grouping. */
export function consolidatePulled(rows) {
  const map = new Map();
  for (const r of rows || []) {
    const key = `${r.division_id || ""}|${r.item_id}`;
    if (!map.has(key)) map.set(key, { key, item_id: r.item_id, item_code: r.item_code, item_name: r.item_name, division_id: r.division_id, division_name: r.division_name, base_unit: r.base_unit || r.unit, base_uom_id: r.base_uom_id, sources: [] });
    map.get(key).sources.push(sourceFromPull(r));
  }
  return [...map.values()].map((g) => ({ ...g, sources: g.sources.sort(byMroDate) }));
}

/** Bagi Qty RO ke sumber secara FIFO (MRO terlama dulu), dibatasi sisa tiap sumber. */
export function distribute(sources, qty) {
  let rem = Math.max(0, n(qty));
  return [...sources].sort(byMroDate).map((s) => { const take = Math.min(n(s.sisa), rem); rem -= take; return { ...s, qty: +take.toFixed(6) }; });
}

export const lineTotals = (l) => {
  const s = l.sources || [];
  return { need: sum(s, "mro_qty"), done: sum(s, "sudah_ro"), sisa: sum(s, "sisa"), alloc: sum(s, "qty"), mro: new Set(s.map((x) => x.mro_id)).size };
};

/** Label SPK human-readable: SPK-001 | Beberapa SPK (n) | Non-SPK | ... + Non-SPK. */
export function spkSummary(sources, onlyTaken = true) {
  const used = (sources || []).filter((s) => !onlyTaken || n(s.qty) > EPS);
  const spk = new Set(); let non = false;
  used.forEach((s) => { (s.spk || []).forEach((x) => spk.add(x.spk_number)); if (n(s.non_spk_qty) > EPS || !(s.spk || []).length) non = true; });
  const names = [...spk];
  const head = names.length === 0 ? "" : names.length === 1 ? names[0] : `Beberapa SPK (${names.length})`;
  return { text: head ? (non ? `${head} + Non-SPK` : head) : "Non-SPK", title: [...names, ...(non ? ["Non-SPK"] : [])].join(", ") };
}

/** Gabungkan grup hasil Tarik MRO ke baris RO terkonsolidasi (kunci: Barang; Divisi sudah satu per RO).
 *  Sumber MRO yang sama ditarik lagi -> qty ditambahkan ke rincian sumber existing (bukan baris/sumber kedua). */
export const mergePicked = mergeRoPicked;

/** Baris RO hasil GET -> state form. Qty/rincian selalu satuan dasar (normalisasi UOM existing). */
export const fromSavedLine = (l) => (l.sources || []).length ? {
  ...l, _consolidated: true, qty: n(l.qty), uom_id: l.base_uom_id || l.uom_id, conversion_factor: 1, unit: l.base_unit || l.unit,
  sources: l.sources.map((s) => ({ ...s, qty: n(s.qty) })),
} : { ...l, _readonly: true };

/** Payload server: hanya sumber dengan qty > 0; base_qty = qty (sudah satuan dasar). */
export const toPayloadLine = (l) => {
  if (!l._consolidated) return { ...l, sources: l.sources || [] };
  return {
    id: l.id, item_id: l.item_id, qty: n(l.qty), uom_id: l.uom_id, conversion_factor: 1, unit: l.unit,
    warehouse_id: l.warehouse_id || null, project_id: l.project_id || null, unit_id: l.unit_id || null, notes: l.notes || "",
    sources: (l.sources || []).filter((s) => n(s.qty) > EPS).map((s) => ({ mro_id: s.mro_id, line_id: s.line_id, qty: n(s.qty), base_qty: n(s.qty) })),
  };
};

export const lineIsValid = (l) => {
  const t = lineTotals(l);
  return n(l.qty) > EPS && Math.abs(t.alloc - n(l.qty)) <= EPS && (l.sources || []).every((s) => n(s.qty) <= n(s.sisa) + EPS);
};

export function RoSourcePickerDialog({ open, onClose, divisionId, onConfirm, formLines = [], currentDocId = null }) {
  const [raw, setRaw] = useState(null);
  const [q, setQ] = useState("");
  const [div, setDiv] = useState(divisionId || "");
  const [sel, setSel] = useState(new Set());
  useEffect(() => {
    if (!open) return;
    setRaw(null); setSel(new Set()); setQ(""); setDiv(divisionId || "");
    api.get("/pull/mro-for-ro", { params: pullParams(currentDocId) }).then((r) => setRaw(r.data || [])).catch((e) => { setRaw([]); toast.error(apiError(e.response?.data?.detail)); });
  }, [open, divisionId, currentDocId]);
  // Sisa efektif = sisa untuk dokumen ini - qty yang sudah dipakai di form RO aktif (dihitung ulang setiap form berubah).
  const reserved = useMemo(() => roFormReservation(formLines), [formLines]);
  const rows = useMemo(() => (raw === null ? null : consolidatePulled(applyRoReservation(raw, reserved))), [raw, reserved]);
  const divOptions = useMemo(() => {
    const m = new Map(); (rows || []).forEach((g) => g.division_id && m.set(g.division_id, g.division_name || "-"));
    return [...m.entries()].map(([value, label]) => ({ value, label }));
  }, [rows]);
  const shown = (rows || []).filter((g) => (!div || g.division_id === div) && (!q || `${g.item_code} ${g.item_name} ${g.sources.map((s) => s.mro_no).join(" ")}`.toLowerCase().includes(q.toLowerCase())));
  // Belum ada Divisi: memilih baris pertama sekaligus mengunci Divisi (satu RO = satu Divisi).
  const toggle = (g) => { if (!divisionId && !div) setDiv(g.division_id || ""); setSel((c) => { const x = new Set(c); x.has(g.key) ? x.delete(g.key) : x.add(g.key); return x; }); };
  const confirm = () => {
    const picked = shown.filter((g) => sel.has(g.key)).map((g) => ({ ...g, sources: distribute(g.sources, sum(g.sources, "sisa")) }));
    onConfirm(picked); onClose();
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto" data-testid="ro-source-picker">
        <DialogHeader><DialogTitle className="font-head">Tarik MRO — Kebutuhan Terkonsolidasi</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">Barang yang sama dalam satu Divisi digabung menjadi satu baris walaupun MRO, SPK, Proyek, atau Unit/Aset berbeda. Satu RO hanya untuk satu Divisi.</p>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[240px] flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari barang / nomor MRO..." className="pl-9" data-testid="ro-source-search" /></div>
          <div className="w-64" data-testid="ro-source-division">{divisionId ? <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">Divisi: <span className="font-semibold">{divOptions.find((d) => d.value === divisionId)?.label || "Divisi RO"}</span></div> : <Combobox options={divOptions} value={div} onChange={(v) => { setDiv(v); setSel(new Set()); }} placeholder="Pilih Divisi" />}</div>
        </div>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="w-10 p-2" /><th className="p-2">Barang</th><th className="p-2">Divisi</th><th className="p-2 text-right">Qty Kebutuhan</th><th className="p-2 text-right">Sudah RO</th><th className="p-2 text-right">Sisa</th><th className="p-2">Satuan</th><th className="p-2 text-right">Jumlah MRO</th><th className="p-2">Alokasi SPK</th>
          </tr></thead><tbody>
            {rows === null && <tr><td colSpan={9} className="p-6 text-center text-muted-foreground">Memuat kebutuhan MRO...</td></tr>}
            {rows && shown.length === 0 && <tr><td colSpan={9} className="p-6 text-center text-muted-foreground" data-testid="ro-source-empty">Tidak ada sisa kebutuhan MRO{div ? " untuk divisi ini" : ""}.</td></tr>}
            {shown.map((g) => { const t = lineTotals(g); const s = spkSummary(g.sources, false); return (
              <tr key={g.key} className="border-t" data-testid={`ro-source-row-${g.item_code}`}>
                <td className="p-2"><Checkbox checked={sel.has(g.key)} onCheckedChange={() => toggle(g)} aria-label={`Pilih ${g.item_name}`} data-testid={`ro-source-select-${g.item_code}`} /></td>
                <td className="p-2"><div className="font-medium">{g.item_name}</div><div className="font-mono text-xs text-muted-foreground">{g.item_code}</div></td>
                <td className="p-2">{g.division_name || "-"}</td>
                <td className="p-2 text-right tabular-nums">{num(t.need)}</td><td className="p-2 text-right tabular-nums">{num(t.done)}</td><td className="p-2 text-right font-semibold tabular-nums" data-testid={`ro-source-sisa-${g.item_code}`}>{num(t.sisa)}{sum(g.sources, "reserved") > EPS && <div className="text-[11px] font-normal text-muted-foreground" data-testid={`ro-source-reserved-${g.item_code}`}>di form: {num(sum(g.sources, "reserved"))}</div>}</td>
                <td className="p-2">{g.base_unit}</td>
                <td className="p-2 text-right" title={g.sources.map((x) => x.mro_no).join(", ")}>{t.mro} MRO</td>
                <td className="p-2 text-xs" title={s.title}>{s.text}</td>
              </tr>); })}
          </tbody></table>
        </div>
        {!divisionId && !div && rows && rows.length > 0 && <p className="text-xs text-muted-foreground" data-testid="ro-source-division-hint">Pilih Divisi atau langsung centang barang. Divisi RO mengikuti baris pertama yang dipilih.</p>}
        <DialogFooter><Button variant="outline" onClick={onClose}>Batal</Button><Button onClick={confirm} disabled={sel.size === 0} data-testid="ro-source-confirm">Tambahkan {sel.size ? `(${sel.size})` : ""}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RoSourceDetailDialog({ line, onClose, onChange, readOnly }) {
  if (!line) return null;
  const t = lineTotals(line);
  const setSrc = (i, v) => { const sources = line.sources.map((s, x) => (x === i ? { ...s, qty: Math.max(0, n(v)) } : s)); onChange({ ...line, sources, qty: +sum(sources, "qty").toFixed(6) }); };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto" data-testid="ro-source-detail">
        <DialogHeader><DialogTitle className="font-head">Rincian Sumber — {line.item_code} {line.item_name}</DialogTitle></DialogHeader>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th className="p-2">MRO</th><th className="p-2">SPK</th><th className="p-2">Proyek</th><th className="p-2">Unit/Aset</th><th className="p-2 text-right">Qty MRO</th><th className="p-2 text-right">Sudah RO</th><th className="p-2 text-right">Sisa</th><th className="p-2 text-right w-36">Qty ke RO</th>
          </tr></thead><tbody>
            {line.sources.map((s, i) => { const over = n(s.qty) > n(s.sisa) + EPS; return (
              <tr key={s.line_id} className="border-t" data-testid={`ro-source-detail-row-${i}`}>
                <td className="p-2 font-mono text-xs font-semibold">{s.mro_no}</td>
                <td className="p-2 text-xs">{s.spk_label}</td><td className="p-2">{s.project_name || "-"}</td><td className="p-2">{s.unit_name || "-"}</td>
                <td className="p-2 text-right tabular-nums">{num(s.mro_qty)}</td><td className="p-2 text-right tabular-nums">{num(s.sudah_ro)}</td><td className="p-2 text-right tabular-nums">{num(s.sisa)}</td>
                <td className="p-1.5 text-right">{readOnly ? <span className="font-semibold tabular-nums">{num(s.qty)}</span> : <><Input type="number" min="0" step="any" value={s.qty} onChange={(e) => setSrc(i, e.target.value)} className={`h-8 text-right ${over ? "border-destructive ring-1 ring-destructive/40" : ""}`} aria-invalid={over || undefined} data-testid={`ro-source-qty-${i}`} />{over && <div className="mt-0.5 text-[11px] text-destructive">Melebihi sisa</div>}</>}</td>
              </tr>); })}
          </tbody><tfoot><tr className="border-t bg-muted/40 font-semibold"><td className="p-2" colSpan={4}>Total</td><td className="p-2 text-right">{num(t.need)}</td><td className="p-2 text-right">{num(t.done)}</td><td className="p-2 text-right">{num(t.sisa)}</td><td className="p-2 text-right" data-testid="ro-source-detail-total">{num(t.alloc)} {line.unit}</td></tr></tfoot></table>
        </div>
        <p className="text-xs text-muted-foreground">Qty RO = total alokasi sumber. Alokasi per MRO tidak boleh melebihi sisa; server memvalidasi ulang saat simpan.</p>
        <DialogFooter><Button onClick={onClose} data-testid="ro-source-detail-close">Selesai</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Tabel baris RO terkonsolidasi (form & lihat). */
export function RoConsolidatedTable({ lines, onChange, readOnly, divisionName, allocCell, extraCols }) {
  const [detail, setDetail] = useState(null);
  const upd = (i, patch) => onChange(lines.map((l, x) => (x === i ? { ...l, ...patch } : l)));
  const setQty = (i, v) => { const l = lines[i]; const sources = distribute(l.sources, v); upd(i, { qty: Math.max(0, n(v)), sources }); };
  return <>
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
        <th className="p-2">Barang</th><th className="p-2">Divisi</th><th className="p-2 text-right">Qty Kebutuhan</th><th className="p-2 text-right">Sudah RO</th><th className="p-2 text-right">Sisa</th><th className="p-2 text-right w-32">Qty RO</th><th className="p-2">Satuan</th><th className="p-2 text-right">Jumlah MRO</th><th className="p-2">Alokasi SPK</th><th className="p-2 text-right">Rincian</th>{extraCols?.head}{!readOnly && <th className="w-10 p-2" />}
      </tr></thead><tbody>
        {lines.length === 0 && <tr><td colSpan={13} className="p-6 text-center text-muted-foreground" data-testid="ro-consolidated-empty">Belum ada kebutuhan MRO. Gunakan tombol Tarik MRO.</td></tr>}
        {lines.map((l, i) => { const t = lineTotals(l); const over = n(l.qty) > t.sisa + EPS; const bad = !readOnly && !lineIsValid(l); const sk = spkSummary(l.sources); return (
          <tr key={l.id || l._key || i} className="border-t" data-testid={`ro-line-${i}`}>
            <td className="p-2"><div className="font-medium">{l.item_name}</div><div className="font-mono text-xs text-muted-foreground">{l.item_code}</div></td>
            <td className="p-2">{l.division_name || divisionName || "-"}</td>
            <td className="p-2 text-right tabular-nums">{num(t.need)}</td><td className="p-2 text-right tabular-nums">{num(t.done)}</td><td className="p-2 text-right tabular-nums">{num(t.sisa)}</td>
            <td className="p-1.5 text-right">{readOnly ? <span className="font-semibold tabular-nums" data-testid={`ro-line-qty-${i}`}>{num(l.qty)}</span> : <><Input type="number" min="0" step="any" value={l.qty} onChange={(e) => setQty(i, e.target.value)} className={`h-8 text-right ${over || bad ? "border-destructive ring-1 ring-destructive/40" : ""}`} aria-invalid={over || bad || undefined} data-testid={`ro-line-qty-${i}`} />{over && <div className="mt-0.5 text-[11px] text-destructive">Melebihi sisa</div>}</>}</td>
            <td className="p-2">{l.unit}</td>
            <td className="p-2 text-right" title={(l.sources || []).map((s) => s.mro_no).join(", ")}><Badge variant="outline" data-testid={`ro-line-mro-count-${i}`}>{t.mro} MRO</Badge></td>
            <td className="p-2 text-xs" title={sk.title}>{allocCell ? allocCell(l, i, sk) : sk.text}</td>
            <td className="p-2 text-right"><Button type="button" variant="ghost" size="sm" className="h-8" onClick={() => setDetail(i)} disabled={!(l.sources || []).length} data-testid={`ro-line-detail-${i}`}><ListTree className="mr-1 h-3.5 w-3.5" />Lihat Rincian</Button></td>
            {extraCols?.cells?.(l, i)}
            {!readOnly && <td className="p-2"><Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={() => onChange(lines.filter((_, x) => x !== i))} aria-label="Hapus baris" data-testid={`ro-line-remove-${i}`}><Trash2 className="h-4 w-4 text-destructive" /></Button></td>}
          </tr>); })}
      </tbody></table>
    </div>
    <RoSourceDetailDialog line={detail === null ? null : lines[detail]} readOnly={readOnly} onClose={() => setDetail(null)} onChange={(nl) => upd(detail, nl)} />
  </>;
}
