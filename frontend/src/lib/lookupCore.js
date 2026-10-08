// Inti pengambilan data referensi (lookup) — murni/tanpa React agar bisa diuji di Node.
// Status per data referensi:
//   loading : sedang dimuat (belum ada data)
//   ready   : HTTP 200 (termasuk [] yang sah -> "Belum ada data")
//   denied  : 403 / tercantum di `denied` pada /lookup-batch -> bukan data kosong
//   auth    : 401 setelah alur refresh sesi gagal
//   error   : 5xx / network / respons tidak valid
export const LOOKUP_MESSAGES = {
  loading: "Memuat data...",
  empty: "Belum ada data",
  error: "Gagal memuat data referensi. Coba muat ulang.",
  denied: "Anda tidak memiliki izin untuk melihat data ini.",
  auth: "Sesi Anda berakhir. Silakan login kembali.",
};

export const LOOKUP_LABELS = {
  divisions: "Divisi", contacts: "Kontak", warehouses: "Gudang", projects: "Proyek", units: "Unit / Aset",
  items: "Barang", uoms: "Satuan", item_categories: "Kategori Barang", suppliers: "Supplier",
  supplier_categories: "Kategori Supplier", taxes: "Pajak", spk: "SPK",
};

const READY = Object.freeze({ state: "ready" });

/** Klasifikasi error axios untuk lookup. Tidak pernah menghasilkan data. */
export function classifyLookupError(err) {
  const status = err?.response?.status || 0;
  if (status === 401) return { state: "auth", status, message: LOOKUP_MESSAGES.auth };
  if (status === 403) return { state: "denied", status, message: LOOKUP_MESSAGES.denied };
  return { state: "error", status, message: LOOKUP_MESSAGES.error };
}

export const isLookupFailure = (s) => !!s && (s.state === "error" || s.state === "auth" || s.state === "denied");

/**
 * Membuat fungsi fetchLookups(names, force) -> { data, status }.
 * - /lookup-batch 200: data dipakai per nama; nama di `denied` -> status denied (tidak di-cache, tidak fallback).
 * - /lookup-batch 404: endpoint batch tidak tersedia -> fallback /lookup/{name}.
 * - /lookup-batch 401/403/5xx/network: TIDAK fallback, TIDAK cache; status error dipropagasi.
 *   (401 sudah melewati refresh + retry di interceptor axios.)
 * - Cache hanya untuk HTTP 200. Cache valid lama tidak ditimpa oleh error.
 */
export function createLookupFetcher({ get, cache, inflight, ttl, meta = { gen: 0 }, now = () => Date.now() }) {
  const fresh = (n) => { const c = cache.get(n); return !!c && now() - c.t < ttl; };
  const store = (gen, n, rows) => { if (meta.gen === gen) cache.set(n, { t: now(), data: rows }); };

  const run = async (need, key) => {
    const gen = meta.gen;
    const res = {};
    try {
      const r = await get("/lookup-batch", { params: { names: key } });
      const d = r?.data?.data;
      if (!d || typeof d !== "object") throw Object.assign(new Error("invalid lookup-batch response"), { invalidShape: true });
      const denied = new Set(Array.isArray(r.data.denied) ? r.data.denied : []);
      for (const n of need) {
        if (denied.has(n)) res[n] = { state: "denied", status: 403, message: LOOKUP_MESSAGES.denied };
        else if (Array.isArray(d[n])) { store(gen, n, d[n]); res[n] = { state: "ready", data: d[n] }; }
        else res[n] = { state: "error", status: 0, message: LOOKUP_MESSAGES.error };
      }
    } catch (e) {
      if (e?.response?.status === 404) {
        await Promise.all(need.map(async (n) => {
          try {
            const r = await get(`/lookup/${n}`);
            if (Array.isArray(r?.data)) { store(gen, n, r.data); res[n] = { state: "ready", data: r.data }; }
            else res[n] = { state: "error", status: 0, message: LOOKUP_MESSAGES.error };
          } catch (e2) {
            res[n] = classifyLookupError(e2);
          }
        }));
      } else {
        const cls = classifyLookupError(e);
        need.forEach((n) => { res[n] = cls; });
      }
    }
    return res;
  };

  return async function fetchLookups(names, force = false) {
    const need = force ? [...names] : names.filter((n) => !fresh(n));
    let results = {};
    if (need.length) {
      const key = [...need].sort().join(",");
      let p = inflight.get(key);
      if (!p) {
        p = run(need, key).finally(() => { if (inflight.get(key) === p) inflight.delete(key); });
        inflight.set(key, p);
      }
      results = await p;
    }
    const data = {}, status = {};
    for (const n of names) {
      const r = results[n];
      if (r && r.state === "ready") { data[n] = r.data; status[n] = READY; continue; }
      // Gagal: pertahankan data valid lama (bila ada) — jangan ganti dengan [] palsu.
      const cached = cache.get(n);
      if (cached) data[n] = cached.data;
      status[n] = r ? { state: r.state, status: r.status, message: r.message } : (cached ? READY : { state: "error", status: 0, message: LOOKUP_MESSAGES.error });
    }
    return { data, status };
  };
}
