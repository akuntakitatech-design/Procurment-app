import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { openParam } from "@/lib/reportCenter";

// Drill-down Pusat Laporan -> halaman transaksi gudang: `?open=<id>` membuka detail dokumen sekali per id.
export function useOpenParam(open) {
  const { search } = useLocation();
  const done = useRef(null);
  useEffect(() => {
    const id = openParam(search);
    if (id && done.current !== id) {
      done.current = id;
      open(id);
    }
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
}
