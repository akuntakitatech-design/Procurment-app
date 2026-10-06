// Source picker — reservasi form aktif (RO<-MRO, PO<-RO, DO<-PO, MI<-MRO).
//
// Sisa Efektif di Picker = Sisa yang tersedia untuk dokumen ini (server; saat Edit allocation dokumen
// ini dikecualikan lewat current_doc_id) - Qty yang sedang dipakai di form aktif (belum disimpan).
// Sisa Efektif <= 0 -> sumber tidak ditampilkan. Semua perhitungan dalam SATUAN DASAR.
// Ini hanya UX guard; server tetap memvalidasi ulang (agregat per baris sumber + named lock) saat simpan.
export const EPS = 1e-6;
const n = (v) => Number(v) || 0;
const r6 = (v) => +n(v).toFixed(6);

/** [[sourceLineId, qtyBase], ...] -> Map(sourceLineId -> total qtyBase). */
export function reserveMap(entries) {
  const m = new Map();
  for (const [id, q] of entries || []) {
    if (!id || n(q) <= EPS) continue;
    m.set(id, r6((m.get(id) || 0) + n(q)));
  }
  return m;
}

/** RO: reservasi per baris MRO dari sources[].qty (satuan dasar). */
export const roFormReservation = (lines) => reserveMap((lines || []).flatMap((l) => (l.sources || []).map((s) => [s.line_id, s.qty])));

/** PO: reservasi per baris RO dari _roSources[].line_id / qty (satuan dasar). */
export const poFormReservation = (lines) => reserveMap((lines || []).flatMap((l) => (l._roSources || []).map((s) => [s.line_id, s.qty])));

/** PO: reservasi per sumber RO (baris RO + allocation MRO->RO) untuk mengurangi sisa per rincian. */
export const poSourceReservation = (lines) => reserveMap((lines || []).flatMap((l) => (l._roSources || []).map((s) => [`${s.line_id}|${s.ro_alloc_id || ""}`, s.qty])));

/** DO/MI: reservasi per baris sumber dari qty baris form x faktor konversi baris. */
export const lineFormReservation = (lines, key) => reserveMap((lines || []).map((l) => [l[key], n(l.qty) * (n(l.conversion_factor) || 1)]));

/** Parameter pull: current_doc_id hanya saat Edit dokumen tersimpan. */
export const pullParams = (currentDocId) => (currentDocId ? { current_doc_id: currentDocId } : {});

/**
 * Baris pull generik (DO/MI): kurangi outstanding dengan reservasi form.
 * Mengembalikan baris baru (outstanding & outstanding_base efektif, reserved = qty di form, satuan baris sumber)
 * dan membuang baris dengan sisa efektif <= 0.
 */
export function applyLineReservation(rows, reserved) {
  const out = [];
  for (const r of rows || []) {
    const f = n(r.conversion_factor) || 1;
    const base = r.outstanding_base != null ? n(r.outstanding_base) : n(r.outstanding) * f;
    const used = n(reserved.get(r.line_id));
    const eff = r6(base - used);
    if (eff <= EPS) continue;
    out.push({ ...r, outstanding_base: eff, outstanding: r6(eff / f), reserved: r6(used / f), _db_outstanding_base: base });
  }
  return out;
}

/** Tambah qty (satuan dasar) ke rincian sumber FIFO, dibatasi sisa tiap sumber (qty <= sisa). */
export function addToSources(sources, incBase) {
  let rem = Math.max(0, n(incBase));
  const next = (sources || []).map((s) => {
    const room = Math.max(0, n(s.sisa) - n(s.qty));
    const take = Math.min(room, rem);
    rem -= take;
    return take > EPS ? { ...s, qty: r6(n(s.qty) + take) } : s;
  });
  return { sources: next, left: r6(rem) };
}

// ---------------------------------------------------------------- RO <- MRO
const sumK = (arr, k) => (arr || []).reduce((a, x) => a + n(x[k]), 0);
const byMroDate = (a, b) => String(a.mro_date || "").localeCompare(String(b.mro_date || "")) || String(a.mro_no || "").localeCompare(String(b.mro_no || ""));

/** Kurangi sisa baris MRO dengan qty yang sedang dipakai form RO aktif; sisa efektif <= 0 -> disembunyikan. */
export function applyRoReservation(rows, reserved) {
  const out = [];
  for (const r of rows || []) {
    const base = n(r.outstanding_base ?? r.outstanding);
    const used = n(reserved.get(r.line_id));
    const eff = r6(base - used);
    if (eff <= EPS) continue;
    out.push({ ...r, outstanding_base: eff, _db_outstanding_base: base, _reserved_base: used });
  }
  return out;
}

/** Gabungkan grup hasil Tarik MRO ke baris RO terkonsolidasi (kunci: Barang; Divisi sudah satu per RO). */
export function mergeRoPicked(current, picked, defaults = {}) {
  const out = current.map((l) => ({ ...l, sources: [...(l.sources || [])] }));
  for (const g of picked) {
    const hit = out.find((l) => l._consolidated && l.item_id === g.item_id);
    if (hit) {
      // Sumber MRO yang sama ditarik lagi -> tambahkan ke rincian sumber existing (bukan sumber/baris kedua).
      const byLine = new Map(hit.sources.map((s, i) => [s.line_id, i]));
      for (const s of g.sources) {
        if (n(s.qty) <= EPS && byLine.has(s.line_id)) continue;
        if (byLine.has(s.line_id)) {
          const i = byLine.get(s.line_id); const cur = hit.sources[i];
          hit.sources[i] = { ...cur, qty: +Math.min(n(cur.sisa), n(cur.qty) + n(s.qty)).toFixed(6) };
        } else {
          hit.sources.push({ ...s, sisa: n(s.db_sisa ?? s.sisa) });
        }
      }
      hit.sources.sort(byMroDate);
      hit.qty = +sumK(hit.sources, "qty").toFixed(6);
      continue;
    }
    const uniq = (k) => { const v = [...new Set(g.sources.map((s) => s[k] || ""))]; return v.length === 1 ? v[0] : ""; };
    out.push({
      _key: `c-${g.key}-${Date.now()}`, _consolidated: true, item_id: g.item_id, item_code: g.item_code, item_name: g.item_name,
      division_id: g.division_id, division_name: g.division_name, unit: g.base_unit, uom_id: g.base_uom_id, conversion_factor: 1,
      warehouse_id: uniq("warehouse_id") || defaults.warehouse_id || "", project_id: uniq("project_id"), unit_id: uniq("unit_id"),
      qty: +sumK(g.sources, "qty").toFixed(6), sources: g.sources.map((s) => ({ ...s, sisa: n(s.db_sisa ?? s.sisa) })), notes: "",
    });
  }
  return out;
}


// ---------------------------------------------------------------- PO <- RO
const factorOf = (l) => n(l.conversion_factor) || 1;
/** Kurangi sisa baris RO (dan sisa per rincian sumber) dengan qty yang sedang dipakai form PO aktif. */
export function applyPoReservation(rows, formLines) {
  const byLine = poFormReservation(formLines), bySrc = poSourceReservation(formLines);
  const out = [];
  for (const r of rows || []) {
    const used = n(byLine.get(r.line_id));
    const eff = +(n(r.outstanding_base) - used).toFixed(6);
    if (eff <= EPS) continue;
    const sources = (r.sources || []).map((x) => {
      const u = n(bySrc.get(`${r.line_id}|${x.ro_alloc_id || ""}`));
      return { ...x, db_sisa: n(x.sisa), sisa: +Math.max(0, n(x.sisa) - u).toFixed(6) };
    });
    out.push({ ...r, outstanding_base: eff, reserved_base: used, _db_outstanding_base: n(r.outstanding_base), sources });
  }
  return out;
}

/** Tarik RO: sumber RO yang sudah ada di form -> qty ditambahkan ke baris PO tersebut (tidak membuat baris kedua). */
export function mergePulledIntoPo(lines, picked, makeLine) {
  const out = [...lines];
  const added = [];
  for (const r of picked) {
    const idx = out.findIndex((l) => (l._roSources || []).some((x) => x.line_id === r.line_id));
    if (idx < 0) {
      const nl = makeLine({ ...r, sources: (r.sources || []).map((x) => ({ ...x, sisa: n(x.db_sisa ?? x.sisa) })) });
      out.push(nl); added.push(nl);
      continue;
    }
    const l = out[idx];
    const have = new Set((l._roSources || []).filter((x) => x.line_id === r.line_id).map((x) => x.ro_alloc_id || ""));
    const extra = (r.sources || []).filter((x) => !have.has(x.ro_alloc_id || ""))
      .map((x) => ({ ...x, ro_id: r.ro_id, ro_no: r.ro_no, line_id: r.line_id, sisa: n(x.db_sisa ?? x.sisa), qty: 0 }));
    // Tambahan qty dibagi FIFO hanya ke rincian baris RO ini (dibatasi sisa tiap rincian); sumber lain tidak berubah.
    const all = [...(l._roSources || []), ...extra];
    const { sources: grown } = addToSources(all.filter((x) => x.line_id === r.line_id), r._qty);
    let k = 0;
    const merged = all.map((x) => (x.line_id === r.line_id ? grown[k++] : x));
    const base = +sumK(merged, "qty").toFixed(6);
    out[idx] = { ...l, _roSources: merged, qty: +(base / factorOf(l)).toFixed(6) };
  }
  return { lines: out, added };
}


// ---------------------------------------------------------------- DO <- PO, MI <- MRO
/**
 * Gabungkan baris pull ke baris form existing dengan sumber yang sama (key: po_line_id / mro_line_id).
 * qty tambahan dikonversi ke satuan baris existing; sources[0] disinkronkan. Sisanya dikembalikan sebagai `fresh`.
 */
export function mergeLinePull(lines, picked, key, docKey, skip = () => false) {
  const merged = [...(lines || [])];
  const fresh = [];
  for (const p of picked || []) {
    const k = merged.findIndex((l) => !skip(l) && l[key] && l[key] === p.line_id);
    if (k < 0) { fresh.push(p); continue; }
    const l = merged[k], f = factorOf(l);
    const q = r6(n(l.qty) + (n(p._qty) * (n(p.conversion_factor) || 1)) / f);
    merged[k] = { ...l, qty: q, sources: [{ [docKey]: l[docKey] || p[docKey], line_id: p.line_id, qty: q, base_qty: r6(q * f) }] };
  }
  return { merged, fresh };
}
