import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/api";

export const PAGE_SIZES = [25, 50, 100];

// List transaksi server-side: page/page_size/q/sort/dir/filter dikirim ke backend (?page=...).
export function useServerList(url, params = {}, { facets = "", counts = "" } = {}) {
  const [data, setData] = useState({ items: [], total: 0, page: 1, page_size: 25, facets: {} });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [sort, setSort] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const seq = useRef(0);
  const pkey = JSON.stringify(params);
  useEffect(() => { const t = setTimeout(() => setDq(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => { setPage(1); }, [dq, pkey, pageSize, sort]);
  const load = useCallback(async () => {
    const my = ++seq.current;
    setLoading(true); setError(false);
    const p = { page, page_size: pageSize, ...JSON.parse(pkey) };
    if (dq) p.q = dq;
    if (sort?.key) { p.sort = sort.key; p.dir = sort.dir; }
    if (facets) p.facets = facets;
    if (counts) p.counts = counts;
    Object.keys(p).forEach((k) => (p[k] === "" || p[k] == null) && delete p[k]);
    try { const r = await api.get(url, { params: p }); if (my === seq.current) setData(r.data); }
    catch (e) { if (my === seq.current) setError(true); }
    finally { if (my === seq.current) setLoading(false); }
  }, [url, page, pageSize, dq, sort, pkey, facets, counts]);
  useEffect(() => { load(); }, [load]);
  return { rows: data.items || [], total: data.total || 0, page, setPage, pageSize, setPageSize, q, setQ, sort, setSort, facets: data.facets || {}, loading, error, reload: load };
}
