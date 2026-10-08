import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import api from "@/lib/api";
import { LOOKUP_TTL_MS, lookupCache, lookupInflight, lookupMeta } from "@/lib/lookupStore";
import { createLookupFetcher, isLookupFailure, LOOKUP_MESSAGES } from "@/lib/lookupCore";

// Reference lists for warehouse/requisition forms (no supplier/tax lookups needed).
export const STOCK_REFS = ["divisions", "contacts", "warehouses", "projects", "units", "items", "uoms", "item_categories"];

const fresh = (n) => { const c = lookupCache.get(n); return c && Date.now() - c.t < LOOKUP_TTL_MS; };

/** Ambil beberapa data referensi sekaligus via /lookup-batch (1 request), dengan cache & dedupe in-flight.
 *  Mengembalikan { data, status }. Fallback ke /lookup/{name} HANYA bila endpoint batch 404.
 *  401/403/5xx/network/denied TIDAK pernah diubah menjadi [] dan tidak di-cache. Izin & cakupan tetap dari backend. */
export const fetchLookups = createLookupFetcher({
  get: (url, cfg) => api.get(url, cfg), cache: lookupCache, inflight: lookupInflight, ttl: LOOKUP_TTL_MS, meta: lookupMeta,
});

const LOADING = Object.freeze({ state: "loading", message: LOOKUP_MESSAGES.loading });
const READY = Object.freeze({ state: "ready" });

export function useMasters(names = ["divisions", "contacts", "warehouses", "projects", "units", "suppliers", "supplier_categories", "items", "uoms", "item_categories", "taxes"]) {
  const namesKey = names.join(",");
  // Isi awal langsung dari cache (tanpa kedip/tunggu) bila masih segar.
  const [data, setData] = useState(() => Object.fromEntries(names.filter(fresh).map((n) => [n, lookupCache.get(n).data])));
  const [status, setStatus] = useState(() => Object.fromEntries(names.map((n) => [n, fresh(n) ? READY : LOADING])));
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const load = useCallback(async (only) => {
    const list = Array.isArray(only) ? only : typeof only === "string" ? [only] : namesKey ? namesKey.split(",") : [];
    if (!list.length) return;
    const force = typeof only === "string" || Array.isArray(only);
    setStatus((prev) => { const next = { ...prev }; list.forEach((n) => { if (force || !fresh(n)) next[n] = LOADING; }); return next; });
    const out = await fetchLookups(list, force);
    if (!alive.current) return;
    setData((prev) => ({ ...prev, ...out.data }));
    setStatus((prev) => ({ ...prev, ...out.status }));
  }, [namesKey]);
  useEffect(() => { load(); }, [load]);

  const statusOf = useCallback((name) => status[name] || (data[name] ? READY : LOADING), [status, data]);
  const retry = useCallback((name) => load(name ? [name] : Object.keys(status).filter((n) => isLookupFailure(status[n]))), [load, status]);
  const lookupState = useCallback((name) => ({ ...statusOf(name), retry: () => load(name) }), [statusOf, load]);

  // opts() membawa status lookup (non-enumerable) agar Combobox bisa menampilkan loading/error/izin secara jujur.
  const opts = (name, labelFn) => {
    const rows = (data[name] || []).map((d) => ({ value: d.id, label: labelFn ? labelFn(d) : `${d.code ? d.code + " — " : ""}${d.name}` }));
    Object.defineProperty(rows, "__lookup", { value: lookupState(name), enumerable: false });
    return rows;
  };
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
  const errors = useMemo(() => Object.entries(status).filter(([, s]) => isLookupFailure(s)).map(([name, s]) => ({ name, ...s })), [status]);
  const loading = useMemo(() => Object.values(status).some((s) => s.state === "loading"), [status]);
  return { data, opts, map, reload: load, upsert, status: lookupState, errors, loading, retry };
}
