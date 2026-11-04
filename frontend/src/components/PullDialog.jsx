import { useEffect, useMemo, useState } from "react";
import api, { apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NumericInput } from "@/components/NumericInput";
import { Checkbox } from "@/components/ui/checkbox";
import { num } from "@/lib/format";
import { Search, X, AlertTriangle } from "lucide-react";

/**
 * Inline source-document picker.
 *
 * Kept under the historical PullDialog name so transaction pages do not need a
 * second modal/page just to pull source documents. The picker now lives inside
 * the same transaction workspace and closes after selected rows are inserted.
 */
/**
 * transform(rows) — opsional: mis. kurangi sisa dengan qty yang sedang dipakai di form aktif
 * (sumber dengan sisa efektif <= 0 disembunyikan). Dihitung ulang setiap render agar mengikuti form.
 * params — query string tambahan (mis. current_doc_id saat Edit).
 * groupBy — opsional: tampilkan 1 baris per nilai kolom ini (mis. "po_no"). Saat dipilih, SELURUH
 * baris di bawah grup itu dimasukkan ke form (qty per baris = qtyKey), lalu qty/baris disesuaikan di form.
 */
export function PullDialog({ open, onClose, url, title, columns, idKey = "line_id", qtyKey = "outstanding", onConfirm, transform = null, params = null,
  groupBy = null, groupColumns = null, groupCountLabel = "dokumen", groupHint = null }) {
  const [raw, setRaw] = useState([]);
  const [sel, setSel] = useState({});
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setSel({});
    setQ("");
    setError("");
    setLoading(true);
    setRaw([]);
    api.get(url, params ? { params } : undefined)
      .then((r) => {
        setRaw(Array.isArray(r.data) ? r.data : []);
        setError("");
      })
      .catch((e) => {
        setRaw([]);
        setError(apiError(e.response?.data?.detail));
      })
      .finally(() => setLoading(false));
  }, [open, url, params?.current_doc_id]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows = useMemo(() => (transform ? transform(raw) : raw), [raw, transform]);

  // Mode grup: 1 baris per nomor dokumen (mis. 1 PO). Baris asli disimpan di `_rows`
  // supaya saat dikonfirmasi seluruh item dokumen itu yang masuk ke form.
  const grouped = useMemo(() => {
    if (!groupBy) return rows;
    const uniqJoin = (vals) => [...new Set(vals.map((v) => String(v || "").trim()).filter(Boolean))].join(", ") || "-";
    const sumBy = (list, key) => Math.round(list.reduce((s, r) => s + Number(r[key] || 0), 0) * 100) / 100;
    const map = new Map();
    for (const r of rows) {
      const key = String(r[groupBy] ?? "-");
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(r);
    }
    return [...map.entries()].map(([key, list]) => ({
      ...list[0],
      [groupBy]: key,
      supplier_name: uniqJoin(list.map((r) => r.supplier_name)),
      mro_no: uniqJoin(list.map((r) => r.mro_no)),
      ro_no: uniqJoin(list.map((r) => r.ro_no)),
      unit: uniqJoin(list.map((r) => r.unit)),
      item_count: list.length,
      qty_po: sumBy(list, "qty_po"),
      received: sumBy(list, "received"),
      outstanding: sumBy(list, "outstanding"),
      _rows: list,
    }));
  }, [rows, groupBy]);
  const displayColumns = groupBy ? (groupColumns || columns) : columns;

  if (!open) return null;

  const rowKey = (r) => (groupBy ? r[groupBy] : r[idKey]);
  const matches = (r) => {
    if (!q) return true;
    const needle = q.toLowerCase();
    const hay = groupBy ? `${JSON.stringify(r)} ${(r._rows || []).map((x) => JSON.stringify(x)).join(" ")}` : JSON.stringify(r);
    return hay.toLowerCase().includes(needle);
  };
  const filtered = grouped.filter(matches);

  const toggle = (r) => {
    const id = rowKey(r);
    setSel((s) => {
      const n = { ...s };
      if (n[id]) delete n[id];
      else n[id] = { row: r, qty: groupBy ? null : r[qtyKey] };
      return n;
    });
  };

  const setQty = (id, v) => setSel((s) => ({ ...s, [id]: { ...s[id], qty: v } }));
  const allChecked = filtered.length > 0 && filtered.every((r) => sel[rowKey(r)]);
  const toggleAll = () => {
    if (allChecked) return setSel({});
    const n = {};
    filtered.forEach((r) => { n[rowKey(r)] = { row: r, qty: groupBy ? null : r[qtyKey] }; });
    setSel(n);
  };

  const confirm = () => {
    let picked;
    if (groupBy) {
      picked = Object.values(sel)
        .flatMap((x) => (x.row._rows || []).map((r) => ({ ...r, _qty: Number(r[qtyKey]) })))
        .filter((r) => Number(r._qty) > 0);
    } else {
      picked = Object.values(sel)
        .filter((x) => Number(x.qty) > 0)
        .map((x) => ({ ...x.row, _qty: Number(x.qty) }));
    }
    if (!picked.length) return;
    onConfirm(picked);
    onClose();
  };

  const selectedCount = Object.keys(sel).length;
  const emptyText = q ? "Tidak ada data yang cocok dengan pencarian" : "Tidak ada dokumen yang memenuhi syarat untuk ditarik";
  const subtitle = groupBy
    ? (groupHint || "Pilih satu nomor dokumen; seluruh item di dalamnya masuk ke form untuk disesuaikan.")
    : "Pilih baris dan tentukan qty yang akan dimasukkan. Tidak perlu pindah halaman.";
  const colspan = displayColumns.length + (groupBy ? 1 : 2);

  return (
    <section className="mb-5 rounded-xl border bg-card shadow-sm overflow-hidden" data-testid="inline-source-picker">
      <div className="flex flex-col gap-3 border-b bg-muted/35 p-4 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold uppercase tracking-wider text-primary">Sumber Dokumen</div>
          <h2 className="font-head text-base font-semibold">{title}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="self-end sm:self-auto">
          <X className="mr-2 h-4 w-4" />Tutup
        </Button>
      </div>

      <div className="p-4 space-y-3">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" data-testid="pull-error">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div><div className="font-semibold">Sumber dokumen gagal dimuat</div><div className="text-xs mt-0.5">{error}</div></div>
          </div>
        )}

        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input data-testid="pull-search" placeholder="Cari nomor dokumen, barang, proyek..." value={q}
            onChange={(e) => setQ(e.target.value)} className="h-10 pl-9" autoFocus />
        </div>

        {/* Mobile: source rows as cards, easier for warehouse users on phones. */}
        <div className="space-y-2 md:hidden">
          {loading && <div className="rounded-lg border p-5 text-center text-sm text-muted-foreground">Memuat dokumen...</div>}
          {!loading && !error && filtered.length === 0 && <div className="rounded-lg border p-5 text-center text-sm text-muted-foreground">{emptyText}</div>}
          {filtered.map((r) => {
            const id = rowKey(r);
            const checked = !!sel[id];
            return (
              <div key={id} className={`rounded-lg border p-3 transition-colors ${checked ? "border-primary/50 bg-primary/5" : "bg-background"}`}>
                <div className="flex items-start gap-3">
                  <Checkbox checked={checked} onCheckedChange={() => toggle(r)} className="mt-1" />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    {displayColumns.map((c) => (
                      <div key={c.key} className="flex gap-3 text-sm">
                        <span className="w-24 shrink-0 text-xs text-muted-foreground">{c.label}</span>
                        <span className={`min-w-0 flex-1 break-words ${c.mono ? "font-mono text-xs" : ""} ${c.num ? "text-right tabular-nums" : ""}`}>
                          {c.num ? num(r[c.key]) : (r[c.key] ?? "-")}
                        </span>
                      </div>
                    ))}
                    {!groupBy && (
                      <div className="flex items-center gap-3 pt-1">
                        <span className="w-24 shrink-0 text-xs font-medium">Qty Ambil</span>
                        <NumericInput mode="quantity" disabled={!checked} value={checked ? sel[id].qty : r[qtyKey]}
                          onChange={(v) => setQty(id, v)} className="h-9 text-right" />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Desktop: dense table for fast operational input. */}
        <div className="hidden md:block max-h-[430px] overflow-auto rounded-md border">
          <table className="w-full text-sm zebra">
            <thead className="sticky top-0 z-10 bg-muted">
              <tr className="text-left">
                <th className="p-2 w-10"><Checkbox checked={allChecked} onCheckedChange={toggleAll} data-testid="pull-select-all" /></th>
                {displayColumns.map((c) => <th key={c.key} className="p-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap">{c.label}</th>)}
                {!groupBy && <th className="p-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground w-28">Qty Ambil</th>}
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={colspan} className="p-6 text-center text-muted-foreground">Memuat dokumen...</td></tr>}
              {!loading && error && <tr><td colSpan={colspan} className="p-6 text-center text-destructive">Gagal memuat sumber dokumen. Lihat pesan di atas.</td></tr>}
              {!loading && !error && filtered.length === 0 && <tr><td colSpan={colspan} className="p-6 text-center text-muted-foreground">{emptyText}</td></tr>}
              {filtered.map((r, ri) => {
                const id = rowKey(r); const checked = !!sel[id];
                return (
                  <tr key={id} data-testid={`pull-line-${r.po_no || r.ro_no || r.mro_no || "row"}-${ri}`} className={`border-t transition-colors ${checked ? "bg-primary/5" : "hover:bg-accent/40"}`}>
                    <td className="p-2"><Checkbox checked={checked} onCheckedChange={() => toggle(r)} data-testid={`pull-row-${id}`} /></td>
                    {displayColumns.map((c) => (
                      <td key={c.key} className={`p-2 whitespace-nowrap ${c.mono ? "font-mono text-xs" : ""} ${c.num ? "text-right tabular-nums" : ""}`}>
                        {c.num ? num(r[c.key]) : (r[c.key] ?? "-")}
                      </td>
                    ))}
                    {!groupBy && (
                      <td className="p-2">
                        <Input type="number" disabled={!checked} value={checked ? sel[id].qty : r[qtyKey]}
                          onChange={(e) => setQty(id, e.target.value)} className="h-8 text-right" data-testid={`pull-qty-${id}`} />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="flex flex-col-reverse gap-2 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-muted-foreground">
            {selectedCount ? `${selectedCount} ${groupBy ? groupCountLabel : "baris"} dipilih` : "Pilih dokumen sumber yang diperlukan"}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Batal</Button>
            <Button onClick={confirm} disabled={selectedCount === 0} data-testid="pull-confirm">
              Masukkan ke Form ({selectedCount}{groupBy ? ` ${groupCountLabel}` : ""})
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
