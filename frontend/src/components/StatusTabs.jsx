import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

// Katalog grup status (definisi tunggal di backend: status_groups_layer) — diambil sekali per sesi.
let cache = null;
let inflight = null;

function loadCatalog() {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = api.get("/txn-status-groups")
      .then((r) => { cache = r.data || {}; return cache; })
      .catch(() => { cache = null; return {}; })
      .finally(() => { inflight = null; });
  }
  return inflight;
}

/** Tab kelompok status daftar transaksi (Semua / Draft / … / Lainnya). `counts` = {key: jumlah}. */
export function StatusTabs({ module, value = "all", onChange, counts = {}, testid }) {
  const [groups, setGroups] = useState(cache ? cache[module] : undefined);
  useEffect(() => {
    let alive = true;
    loadCatalog().then((all) => { if (alive) setGroups((all || {})[module]); });
    return () => { alive = false; };
  }, [module]);
  if (!groups || groups.length === 0) return null;

  const main = groups.filter((g) => !g.overflow);
  const overflow = groups.filter((g) => g.overflow);
  const inOverflow = overflow.some((g) => g.key === value);
  const n = (key) => (counts && counts[key] != null ? counts[key] : null);

  const seg = (g) => {
    const on = value === g.key || (g.key === "all" && !value);
    const c = n(g.key);
    return (
      <button key={g.key} type="button" onClick={() => onChange(g.key)} aria-pressed={on}
        data-testid={testid ? `${testid}-status-${g.key}` : undefined}
        className={cn("inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-r px-3 text-sm transition-colors last:border-r-0",
          on ? "bg-primary/5 font-semibold text-primary" : "text-foreground hover:bg-accent/60")}>
        {g.label}
        {c != null && <span className={cn("text-[11px] tabular-nums", on ? "text-primary/70" : "text-muted-foreground")}>{c}</span>}
      </button>
    );
  };

  return (
    <div className="inline-flex max-w-full flex-wrap overflow-hidden rounded-lg border bg-card" data-testid={testid ? `${testid}-status-tabs` : "status-tabs"}>
      {main.map(seg)}
      {overflow.length > 0 && (
        <div className="relative">
          <select value={inOverflow ? value : ""} onChange={(e) => e.target.value && onChange(e.target.value)}
            aria-label="Status lainnya" data-testid={testid ? `${testid}-status-more` : "status-tabs-more"}
            className={cn("h-9 appearance-none bg-transparent pl-3 pr-8 text-sm",
              inOverflow ? "font-semibold text-primary" : "text-foreground")}>
            <option value="">{inOverflow ? overflow.find((g) => g.key === value).label : "Lainnya"}</option>
            {overflow.map((g) => <option key={g.key} value={g.key}>{g.label}{n(g.key) != null ? ` (${n(g.key)})` : ""}</option>)}
            {inOverflow && <option value="all">Kembali ke Semua</option>}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        </div>
      )}
    </div>
  );
}

export default StatusTabs;
