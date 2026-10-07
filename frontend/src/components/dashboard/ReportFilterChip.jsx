import { useMemo } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { RF_LABEL, asOfLabel } from "@/lib/dashboard";
import { LayoutDashboard, X } from "lucide-react";

const KEYS = ["rf_kind", "rf_asof", "rf_division_id", "rf_project_id", "rf_supplier_id", "date_from", "date_to", "f_document_status"];

/** Filter drill-down dari Dashboard (query URL) -> param list server-side existing. Tanpa query: perilaku list lama. */
export function useReportParams() {
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const { pathname } = useLocation();
  const params = useMemo(() => Object.fromEntries(KEYS.map((k) => [k, sp.get(k) || ""]).filter(([, v]) => v)), [sp]);
  const active = Object.keys(params).length > 0;
  const label = [RF_LABEL[params.rf_kind], params.f_document_status && "Status Dokumen", params.rf_supplier_id && "Supplier",
    params.rf_division_id && "Divisi", params.rf_project_id && "Project",
    // Kartu posisi (tanpa date_from) = saldo terbuka s/d tanggal; kartu aktivitas = rentang periode.
    params.date_to && !params.date_from ? `Posisi s/d ${asOfLabel(params.rf_asof || params.date_to)}`
      : (params.date_from || params.date_to) && `${params.date_from || "…"} s/d ${params.date_to || "…"}`].filter(Boolean).join(" · ");
  const chip = active ? (
    <span className="inline-flex h-9 items-center gap-2 rounded-lg border border-[#D6E2EF] bg-[#F3F7FB] px-3 text-xs text-[#2C4A6E]" data-testid="report-filter-chip">
      <LayoutDashboard className="h-3.5 w-3.5" />Dari Dashboard: <b className="font-medium">{label || "Filter"}</b>
      <button type="button" onClick={() => nav(pathname + (sp.get("tab") ? `?tab=${sp.get("tab")}` : ""), { replace: true })} className="rounded p-0.5 hover:bg-white" aria-label="Hapus filter dashboard" data-testid="report-filter-clear"><X className="h-3.5 w-3.5" /></button>
    </span>) : null;
  return { params, active, chip };
}
