import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { useMasters } from "@/hooks/useMasters";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Combobox } from "@/components/Combobox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { num, fmtDate, rupiah } from "@/lib/format";
import { FileSpreadsheet } from "lucide-react";

function RefDateCell({ refs = [] }) {
  if (!refs.length) return <span className="text-muted-foreground">-</span>;
  return (
    <div className="space-y-1">
      {refs.map((r) => (
        <div key={r.id} className="whitespace-nowrap text-xs text-muted-foreground">
          {r.date ? fmtDate(r.date) : "-"}
        </div>
      ))}
    </div>
  );
}

function RefNoCell({ refs = [] }) {
  if (!refs.length) return <span className="text-muted-foreground">-</span>;
  return (
    <div className="space-y-1">
      {refs.map((r) => (
        <div key={r.id} className="whitespace-nowrap font-mono text-xs font-semibold">
          {r.no || "-"}
        </div>
      ))}
    </div>
  );
}

function MoneyCell({ value, dashWhenZero = false, strong = false }) {
  if (value == null) return <span className="text-muted-foreground">***</span>;
  if (dashWhenZero && Number(value) === 0) return <span className="text-muted-foreground">-</span>;
  return <span className={`whitespace-nowrap tabular-nums ${strong ? "font-semibold" : ""}`}>{rupiah(value)}</span>;
}

export default function Reports() {
  const nav = useNavigate();
  const masters = useMasters(["units"]);
  const [trace, setTrace] = useState([]);
  const [lead, setLead] = useState([]);
  const [usage, setUsage] = useState([]);
  const [unitId, setUnitId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [exporting, setExporting] = useState(false);

  const traceQuery = (from = dateFrom, to = dateTo) => {
    const params = new URLSearchParams();
    if (from) params.set("date_from", from);
    if (to) params.set("date_to", to);
    return params.toString();
  };

  const loadTrace = (from = dateFrom, to = dateTo) => {
    const qs = traceQuery(from, to);
    return api.get(`/reports/mro-traceability${qs ? `?${qs}` : ""}`).then((r) => setTrace(r.data));
  };

  const exportExcel = async () => {
    try {
      setExporting(true);
      const qs = traceQuery();
      const res = await api.get(`/reports/mro-traceability/export.xlsx${qs ? `?${qs}` : ""}`, { responseType: "blob" });
      const url = window.URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `MRO-Traceability_${dateFrom || "awal"}_${dateTo || "akhir"}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  useEffect(() => {
    api.get("/reports/mro-traceability").then((r) => setTrace(r.data));
    api.get("/reports/lead-time").then((r) => setLead(r.data));
  }, []);

  useEffect(() => {
    api.get(`/reports/unit-usage${unitId ? "?unit_id=" + unitId : ""}`).then((r) => setUsage(r.data));
  }, [unitId]);

  const resetPeriod = () => {
    setDateFrom("");
    setDateTo("");
    loadTrace("", "");
  };

  return (
    <div>
      <PageHeader title="Reporting" subtitle="Laporan lifecycle MRO, lead time, dan pemakaian unit" />
      <Tabs defaultValue="trace">
        <TabsList>
          <TabsTrigger value="trace" data-testid="rep-tab-trace">MRO Traceability</TabsTrigger>
          <TabsTrigger value="lead" data-testid="rep-tab-lead">Lead Time</TabsTrigger>
          <TabsTrigger value="usage" data-testid="rep-tab-usage">Pemakaian Unit</TabsTrigger>
        </TabsList>

        <TabsContent value="trace" className="mt-4">
          <div className="mb-4 rounded-xl border bg-card p-4 shadow-sm">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
              <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2 lg:max-w-xl">
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Dari Tanggal MRO</span>
                  <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Sampai Tanggal MRO</span>
                  <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => loadTrace()} data-testid="trace-filter-btn">Terapkan Periode</Button>
                <Button variant="outline" onClick={resetPeriod}>Reset</Button>
                <Button variant="outline" onClick={exportExcel} disabled={exporting}>
                  <FileSpreadsheet className="mr-2 h-4 w-4" />{exporting ? "Menyiapkan..." : "Export Excel"}
                </Button>
              </div>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Urutan lifecycle dibuat berkelompok: tanggal, nomor referensi, lalu qty untuk MRO → RO → PO → DO → MI. Nilai PO menampilkan nilai bruto, diskon, DPP, pajak, dan total. Total DO dihitung dari DPP per satuan dasar × qty yang benar-benar diterima.</p>
          </div>

          <div className="border rounded-md overflow-x-auto bg-card shadow-sm">
            <table className="w-full min-w-[3300px] text-sm zebra">
              <thead className="bg-muted">
                <tr className="text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="p-3">Kode Barang</th>
                  <th className="p-3">Nama Barang</th>
                  <th className="p-3">Kategori</th>
                  <th className="p-3">Satuan</th>
                  <th className="p-3">Tanggal MRO</th>
                  <th className="p-3">No. MRO</th>
                  <th className="p-3 text-right">Qty MRO</th>
                  <th className="p-3">Tanggal RO</th>
                  <th className="p-3">No. RO</th>
                  <th className="p-3 text-right">Qty RO</th>
                  <th className="p-3">Tanggal PO</th>
                  <th className="p-3">No. PO</th>
                  <th className="p-3 text-right">Qty PO</th>
                  <th className="p-3 text-right">Nilai PO</th>
                  <th className="p-3 text-right">Diskon</th>
                  <th className="p-3 text-right">DPP</th>
                  <th className="p-3 text-right">Pajak</th>
                  <th className="p-3 text-right">Total PO</th>
                  <th className="p-3">Tanggal DO</th>
                  <th className="p-3">No. DO</th>
                  <th className="p-3 text-right">Qty DO</th>
                  <th className="p-3 text-right">Total DO</th>
                  <th className="p-3">Tanggal MI</th>
                  <th className="p-3">No. MI</th>
                  <th className="p-3 text-right">Qty MI</th>
                  <th className="p-3 text-right">Outstanding</th>
                  <th className="p-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {trace.length === 0 && <tr><td colSpan={27} className="p-8 text-center text-muted-foreground">Belum ada data pada periode ini</td></tr>}
                {trace.map((t) => (
                  <tr
                    key={`${t.mro_id}-${t.item_id}`}
                    onClick={() => nav(`/traceability?mro=${t.mro_no}`)}
                    className="border-t cursor-pointer align-top hover:bg-accent/40 transition-colors"
                  >
                    <td className="p-3 font-mono text-xs font-semibold text-primary">{t.item_code || "-"}</td>
                    <td className="p-3 font-medium">{t.item_name || "-"}</td>
                    <td className="p-3">{t.category || "-"}</td>
                    <td className="p-3">{t.unit || "-"}</td>

                    <td className="p-3"><RefDateCell refs={t.mro_refs} /></td>
                    <td className="p-3"><RefNoCell refs={t.mro_refs} /></td>
                    <td className="p-3 text-right tabular-nums font-semibold">{num(t.request)}</td>

                    <td className="p-3"><RefDateCell refs={t.ro_refs} /></td>
                    <td className="p-3"><RefNoCell refs={t.ro_refs} /></td>
                    <td className="p-3 text-right tabular-nums">{num(t.qty_ro)}</td>

                    <td className="p-3"><RefDateCell refs={t.po_refs} /></td>
                    <td className="p-3"><RefNoCell refs={t.po_refs} /></td>
                    <td className="p-3 text-right tabular-nums">{num(t.qty_po)}</td>
                    <td className="p-3 text-right"><MoneyCell value={t.po_gross} /></td>
                    <td className="p-3 text-right"><MoneyCell value={t.po_discount} dashWhenZero /></td>
                    <td className="p-3 text-right"><MoneyCell value={t.po_dpp} /></td>
                    <td className="p-3 text-right"><MoneyCell value={t.po_tax} dashWhenZero /></td>
                    <td className="p-3 text-right"><MoneyCell value={t.po_total} strong /></td>

                    <td className="p-3"><RefDateCell refs={t.do_refs} /></td>
                    <td className="p-3"><RefNoCell refs={t.do_refs} /></td>
                    <td className="p-3 text-right tabular-nums">{num(t.qty_received)}</td>
                    <td className="p-3 text-right"><MoneyCell value={t.do_total} strong /></td>

                    <td className="p-3"><RefDateCell refs={t.mi_refs} /></td>
                    <td className="p-3"><RefNoCell refs={t.mi_refs} /></td>
                    <td className="p-3 text-right tabular-nums">{num(t.qty_mi)}</td>

                    <td className="p-3 text-right tabular-nums font-semibold">{num(t.outstanding)}</td>
                    <td className="p-3"><StatusBadge status={t.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TabsContent>

        <TabsContent value="lead" className="mt-4">
          <div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">MRO</th><th className="p-3">PO</th><th className="p-3">DO</th><th className="p-3">MI</th><th className="p-3 text-right">MRO→PO</th><th className="p-3 text-right">PO→DO</th><th className="p-3 text-right">DO→MI</th><th className="p-3 text-right">Total (hari)</th></tr></thead>
            <tbody>{lead.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-muted-foreground">Belum ada data</td></tr>}
              {lead.map((l, i) => (<tr key={i} className="border-t"><td className="p-3 font-mono text-xs">{l.mro_no}</td><td className="p-3 font-mono text-xs">{l.po_no || "-"}</td><td className="p-3 font-mono text-xs">{l.do_no || "-"}</td><td className="p-3 font-mono text-xs">{l.mi_no || "-"}</td><td className="p-3 text-right">{l.mro_to_po ?? "-"}</td><td className="p-3 text-right">{l.po_to_do ?? "-"}</td><td className="p-3 text-right">{l.do_to_mi ?? "-"}</td><td className="p-3 text-right font-semibold">{l.total ?? "-"}</td></tr>))}</tbody></table></div>
        </TabsContent>

        <TabsContent value="usage" className="mt-4">
          <div className="max-w-sm mb-4"><Combobox options={[{ value: "", label: "Semua Unit" }, ...masters.opts("units", (d) => `${d.name}${d.plate_no ? " (" + d.plate_no + ")" : ""}`)]} value={unitId} onChange={setUnitId} placeholder="Filter unit" /></div>
          <div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">Unit</th><th className="p-3">No. Polisi</th><th className="p-3">Kode</th><th className="p-3">Barang</th><th className="p-3 text-right">Qty</th><th className="p-3">Satuan</th></tr></thead>
            <tbody>{usage.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-muted-foreground">Belum ada pemakaian unit</td></tr>}
              {usage.map((u, i) => (<tr key={i} className="border-t"><td className="p-3">{u.unit_name}</td><td className="p-3 font-mono text-xs">{u.plate_no || "-"}</td><td className="p-3 font-mono text-xs">{u.item_code}</td><td className="p-3">{u.item_name}</td><td className="p-3 text-right font-semibold">{num(u.qty)}</td><td className="p-3">{u.unit}</td></tr>))}</tbody></table></div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
