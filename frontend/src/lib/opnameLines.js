// Stock Opname — helper murni (tanpa React) untuk workspace, ringkasan, payload hitung & cetak.
// Sumber angka (selisih, harga MWA, nilai, ringkasan) = SERVER. Helper ini hanya memformat & menyusun payload.

export const ACTIVE = ["Counting", "Review", "Waiting Approval"];
export const EDITABLE = ["Counting", "Review"];

export const STATUS_META = {
  uncounted: { label: "Belum Dihitung", tone: "bg-slate-100 text-slate-700 border-slate-200" },
  match: { label: "Sesuai", tone: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  plus: { label: "Selisih +", tone: "bg-sky-50 text-sky-700 border-sky-200" },
  minus: { label: "Selisih −", tone: "bg-rose-50 text-rose-700 border-rose-200" },
};

export const FILTERS = [
  { value: "all", label: "Semua" },
  { value: "uncounted", label: "Belum Dihitung" },
  { value: "match", label: "Sesuai" },
  { value: "variance", label: "Selisih (+/−)" },
  { value: "plus", label: "Selisih +" },
  { value: "minus", label: "Selisih −" },
  { value: "attention", label: "Perlu Perhatian" },
];

export const MODE_INFO = {
  live: "Live — transaksi tetap berjalan; stok sistem dicatat per barang saat hasil hitung disimpan, mutasi sesudahnya diperhitungkan kronologis.",
  freeze: "Freeze — semua mutasi stok gudang ini diblokir server sampai Opname diposting atau dibatalkan.",
};

/** Input fisik: "" / null / undefined = belum dihitung; "0" = sudah dihitung, fisik nol. */
export const isBlank = (v) => v === "" || v === null || v === undefined;

export const parseQty = (v) => {
  if (isBlank(v)) return null;
  const n = Number(String(v).replace(",", "."));
  return Number.isFinite(n) ? n : NaN;
};

/** Draft per baris (bertahan lintas halaman): { [lineId]: { qty, uom_id, reason, approved_unit_cost, cost_reason } } */
export const mergeDraft = (draft, lineId, patch) => ({ ...draft, [lineId]: { ...(draft[lineId] || {}), ...patch } });

/** Payload PUT /opname/{id}/count dari draft. Qty kosong pada baris yang tadinya terhitung -> clear. */
export function buildCountPayload(draft, linesById = {}) {
  const out = [];
  const errors = [];
  for (const [lineId, d] of Object.entries(draft || {})) {
    const row = { line_id: lineId };
    if ("qty" in d) {
      const q = parseQty(d.qty);
      if (q === null) { if (linesById[lineId]?.counted != null) row.clear = true; }
      else if (Number.isNaN(q) || q < 0) { errors.push(`${linesById[lineId]?.item_code || lineId}: qty fisik harus angka >= 0`); continue; }
      else { row.qty = q; if (d.uom_id) row.uom_id = d.uom_id; }
    } else if ("uom_id" in d && linesById[lineId]?.counted_qty != null) {
      row.qty = linesById[lineId].counted_qty; row.uom_id = d.uom_id;
    }
    if ("reason" in d) row.reason = d.reason || "";
    if ("approved_unit_cost" in d) { row.approved_unit_cost = isBlank(d.approved_unit_cost) ? null : Number(d.approved_unit_cost); row.cost_reason = d.cost_reason || ""; }
    if (Object.keys(row).length > 1) out.push(row);
  }
  return { lines: out, errors };
}

/** Pilihan satuan hitung barang (dasar + konversi). */
export function uomOptions(item, uomsMap = {}) {
  if (!item) return [];
  if (!item.base_uom_id) return item.unit ? [{ value: `legacy:${item.unit}`, label: item.unit, factor: 1 }] : [];
  const seen = new Set();
  const lab = (id) => { const u = uomsMap[id] || {}; return u.symbol || u.code || u.name || "Satuan"; };
  return [{ uom_id: item.base_uom_id, factor: 1, base: true }, ...(item.uoms || [])]
    .filter((r) => r.uom_id && !seen.has(r.uom_id) && seen.add(r.uom_id))
    .map((r) => ({ value: r.uom_id, factor: Number(r.factor) || 1, label: r.base ? `${lab(r.uom_id)} (dasar)` : `${lab(r.uom_id)} = ${Number(r.factor)} ${lab(item.base_uom_id)}` }));
}

export const progressPct = (s) => (s && s.total ? Math.round((100 * (s.counted || 0)) / s.total) : 0);

/** Tombol aksi yang ditampilkan — hanya dari izin server (permissions) + status dokumen. */
export function visibleActions(doc) {
  const p = doc?.permissions || {};
  return [
    p.count && "save", p.review && "review", p.submit && doc.status === "Review" && "submit",
    p.return && "return", p.reject && "reject", p.approve && "approve", p.cancel && "cancel",
  ].filter(Boolean);
}

export const PRICE_SUMMARY_KEYS = ["surplus_value", "shortage_value", "net_value"];
