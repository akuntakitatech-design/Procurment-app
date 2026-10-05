import { useEffect, useState, useCallback, useMemo } from "react";
import api from "@/lib/api";
import { LOOKUP_TTL_MS, lookupCache, lookupInflight } from "@/lib/lookupStore";

// Reference lists for warehouse/requisition forms (no supplier/tax lookups needed).
export const STOCK_REFS = ["divisions", "contacts", "warehouses", "projects", "units", "items", "uoms", "item_categories"];

const fresh = (n) => { const c = lookupCache.get(n); return c && Date.now() - c.t < LOOKUP_TTL_MS; };

/** Ambil beberapa data referensi sekaligus via /lookup-batch (1 request), dengan cache & dedupe in-flight.
 *  Fallback ke /lookup/{name} per data bila endpoint batch tidak tersedia. Izin & cakupan divisi tetap dari backend. */
export async function fetchLookups(names, force = false) {
  const need = force ? names : names.filter((n) => !fresh(n));
  if (need.length) {
    const key = [...need].sort().join(",");
    let p = lookupInflight.get(key);
    if (!p) {
      p = api.get("/lookup-batch", { params: { names: key } })
        .then((r) => { const d = r.data?.data || {}; const t = Date.now(); need.forEach((n) => lookupCache.set(n, { t, data: d[n] || [] })); })
        .catch(() => Promise.all(need.map(async (n) => {
          const r = await api.get(`/lookup/${n}`).catch(() => ({ data: [] }));
          lookupCache.set(n, { t: Date.now(), data: r.data || [] });
        })))
        .finally(() => lookupInflight.delete(key));
      lookupInflight.set(key, p);
    }
    await p;
  }
  return Object.fromEntries(names.map((n) => [n, lookupCache.get(n)?.data || []]));
}

export function useMasters(names = ["divisions", "contacts", "warehouses", "projects", "units", "suppliers", "supplier_categories", "items", "uoms", "item_categories", "taxes"]) {
  const namesKey = names.join(",");
  // Isi awal langsung dari cache (tanpa kedip/tunggu) bila masih segar.
  const [data, setData] = useState(() => Object.fromEntries(names.filter(fresh).map((n) => [n, lookupCache.get(n).data])));
  const load = useCallback(async (only) => {
    const list = typeof only === "string" ? [only] : namesKey ? namesKey.split(",") : [];
    const out = await fetchLookups(list, typeof only === "string");
    setData((prev) => ({ ...prev, ...out }));
  }, [namesKey]);
  useEffect(() => { load(); }, [load]);

  const opts = (name, labelFn) => (data[name] || []).map((d) => ({ value: d.id, label: labelFn ? labelFn(d) : `${d.code ? d.code + " — " : ""}${d.name}` }));
  // map per data dibangun sekali per perubahan data (bukan setiap render/baris) — penting untuk daftar barang besar.
  const map = useMemo(() => {
    const maps = new Map();
    return (name) => { if (!maps.has(name)) maps.set(name, Object.fromEntries((data[name] || []).map((d) => [d.id, d]))); return maps.get(name); };
  }, [data]);
  const upsert = useCallback((name, doc) => setData((prev) => {
    const rows = [...(prev[name] || []).filter((x) => x.id !== doc.id), doc];
    lookupCache.delete(name);
    return { ...prev, [name]: rows };
  }), []);
  return { data, opts, map, reload: load, upsert };
}
