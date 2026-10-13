import { useState } from "react";
import { toast } from "sonner";
import { FileSpreadsheet, FileText } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { listExportQuery, listExportState } from "@/lib/listExport";
import { exportMode } from "@/lib/exportJob";
import { startBackgroundExport } from "@/lib/backgroundExport";

const errMsg = async (e) => {
  const d = e?.response?.data;
  try {
    if (d instanceof Blob) return JSON.parse(await d.text()).detail || "Export gagal.";
  } catch { /* bukan JSON */ }
  return d?.detail || "Export gagal. Coba lagi.";
};

/** Tombol Export Excel/PDF daftar transaksi (P6). Mengekspor SELURUH hasil daftar sesuai filter/pencarian/periode/sort aktif. */
export function ListExportButtons({ reportKey, query, total, testidPrefix = "list" }) {
  const { can } = useAuth();
  const [busy, setBusy] = useState("");
  if (!reportKey || !can("export")) return null;
  const states = { xlsx: listExportState(total, "xlsx", true), pdf: listExportState(total, "pdf", true) };
  const run = async (fmt) => {
    if (!states[fmt].ok) { toast.error(states[fmt].reason); return; }
    setBusy(fmt);
    try {
      const qs = listExportQuery(query);
      if (exportMode(total, fmt) === "background") { await startBackgroundExport(reportKey, fmt, qs); return; }  // P7: export besar
      const r = await api.get(`/report-center/${encodeURIComponent(reportKey)}/export.${fmt}${qs ? `?${qs}` : ""}`, { responseType: "blob" });
      const cd = r.headers?.["content-disposition"] || "";
      const name = (cd.match(/filename="([^"]+)"/) || [])[1] || `${reportKey}.${fmt}`;
      const url = window.URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      const n = r.headers?.["x-report-rows"];  // jumlah baris dari server (seluruh hasil filter)
      toast.success(`Export ${fmt === "pdf" ? "PDF" : "Excel"} berhasil${n ? ` (${Number(n).toLocaleString("id-ID")} baris)` : ""}.`);
    } catch (e) { toast.error(await errMsg(e)); } finally { setBusy(""); }
  };
  const reason = states.pdf.ok ? "" : states.xlsx.ok ? states.pdf.reason.replace("Persempit filter.", "Gunakan Export Excel atau persempit filter.") : states.xlsx.reason;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={`${testidPrefix}-export`}>
      <Button type="button" variant="outline" size="sm" className="h-11 sm:h-9" onClick={() => run("xlsx")} disabled={!!busy || !states.xlsx.ok}
        title={states.xlsx.reason || "Export seluruh hasil filter ke Excel"} data-testid={`${testidPrefix}-export-xlsx`}>
        <FileSpreadsheet className="mr-1.5 h-4 w-4" />{busy === "xlsx" ? "Menyiapkan..." : "Export Excel"}
      </Button>
      <Button type="button" variant="outline" size="sm" className="h-11 sm:h-9" onClick={() => run("pdf")} disabled={!!busy || !states.pdf.ok}
        title={states.pdf.reason || "Export seluruh hasil filter ke PDF"} data-testid={`${testidPrefix}-export-pdf`}>
        <FileText className="mr-1.5 h-4 w-4" />{busy === "pdf" ? "Menyiapkan..." : "Export PDF"}
      </Button>
      {reason && <span className="text-xs text-amber-700" data-testid={`${testidPrefix}-export-limit`}>{reason}</span>}
    </div>
  );
}
