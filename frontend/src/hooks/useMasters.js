import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";

export function useMasters(names = ["divisions", "contacts", "warehouses", "projects", "units", "suppliers", "supplier_categories", "items", "uoms", "item_categories", "taxes"]) {
  const [data, setData] = useState({});
  const namesKey = names.join(",");
  const load = useCallback(async () => {
    const out = {};
    const list = namesKey ? namesKey.split(",") : [];
    await Promise.all(list.map(async (n) => {
      const r = await api.get(`/master/${n}?active_only=true`);
      out[n] = r.data;
    }));
    setData(out);
  }, [namesKey]);
  useEffect(() => { load(); }, [load]);

  const opts = (name, labelFn) => (data[name] || []).map((d) => ({ value: d.id, label: labelFn ? labelFn(d) : `${d.code ? d.code + " — " : ""}${d.name}` }));
  const map = (name) => Object.fromEntries((data[name] || []).map((d) => [d.id, d]));
  return { data, opts, map, reload: load };
}
