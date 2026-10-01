import { PriceHistory } from "@/components/PriceHistory";
import { rupiah } from "@/lib/format";

// CP5A-2 — per-item price control status (read-only, decision support).
// Price Override is determined ONLY by Vendor Contract Price + tolerance,
// never by historical price. Never mutates the contract master.
export function computePriceStatus(contract, displayPrice) {
  const cp = contract && contract.found ? Number(contract.contract_price || 0) : 0;
  const pp = Number(displayPrice || 0);
  if (!contract || !contract.found || !cp) return { status: "No Contract", cp: null };
  const varRp = pp - cp;
  const varPct = cp ? (varRp / cp) * 100 : 0;
  const tol = Number(contract.tolerance_pct || 0);
  const status = varPct > tol + 1e-9 ? "Price Override" : "Normal";
  return { status, cp, varRp, varPct, tol, contract_number: contract.contract_number,
           effective_start: contract.effective_start, effective_end: contract.effective_end };
}

const BADGE = {
  "Normal": "bg-emerald-100 text-emerald-700 border-emerald-200",
  "Price Override": "bg-amber-100 text-amber-800 border-amber-300",
  "No Contract": "bg-slate-100 text-slate-600 border-slate-200",
};

export function StatusBadgePrice({ status, testid }) {
  return <span data-testid={testid} className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${BADGE[status] || BADGE["No Contract"]}`}>{status}</span>;
}

export function PoPriceControl({ line, index, contract, displayPrice, itemName, supplierId }) {
  const r = computePriceStatus(contract, displayPrice);
  const fmtPct = (p) => `${p >= 0 ? "+" : ""}${p.toFixed(2).replace(".", ",")}%`;
  const fmtRp = (v) => `${v >= 0 ? "+" : "-"}${rupiah(Math.abs(v))}`;
  return (
    <div className="mt-1 space-y-0.5" data-testid={`po-price-control-${index}`}>
      <div className="flex items-center gap-1.5 text-[10px]">
        <span className="text-muted-foreground">Kontrak:</span>
        {r.cp != null
          ? <span className="font-medium text-foreground">{rupiah(r.cp)}</span>
          : <span className="text-muted-foreground">Tidak ada kontrak</span>}
      </div>
      {r.cp != null && (
        <div className="text-[10px] text-muted-foreground" data-testid={`po-variance-${index}`}>
          Selisih: <span className={r.varRp > 0 ? "text-amber-700" : r.varRp < 0 ? "text-emerald-700" : ""}>{fmtRp(r.varRp)} / {fmtPct(r.varPct)}</span>
        </div>
      )}
      <StatusBadgePrice status={r.status} testid={`po-status-${index}`} />
      <PriceHistory itemId={line.item_id} uomId={line.uom_id} supplierId={supplierId} itemName={itemName} />
    </div>
  );
}
