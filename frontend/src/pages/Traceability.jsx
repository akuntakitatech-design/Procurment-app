import { useCallback, useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, ArrowRight, FileText } from "lucide-react";
import { num, fmtDate } from "@/lib/format";
import { toast } from "sonner";

const STEP_ROUTES = { ro: "/ro/", po: "/po/", do: "/do/", mi: "/mi/" };

export default function Traceability() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [q, setQ] = useState(params.get("mro") || "");
  const [data, setData] = useState(null);

  const run = useCallback(async (val) => {
    if (!val) return;
    try { const r = await api.get(`/traceability/${encodeURIComponent(val)}`); setData(r.data); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); setData(null); }
  }, []);
  useEffect(() => { const mro = params.get("mro"); if (mro) run(mro); }, [params, run]);

  const stages = data ? [
    { label: "MRO", nodes: [{ no: data.mro.no }], done: true },
    { label: "RO", nodes: data.documents.RO },
    { label: "PO", nodes: data.documents.PO },
    { label: "DO", nodes: data.documents.DO },
    { label: "MI", nodes: data.documents.MI },
  ] : [];

  return (
    <div>
      <PageHeader title="Traceability" subtitle="Telusuri lifecycle penuh: MRO → RO → PO → DO → MI" />
      <div className="flex gap-2 max-w-lg mb-6">
        <div className="relative flex-1"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run(q)} placeholder="Masukkan No. MRO, contoh: MRO/2026/09/00001" className="pl-9" data-testid="trace-input" /></div>
        <Button onClick={() => run(q)} data-testid="trace-search-btn">Telusuri</Button>
      </div>

      {data && (<>
        <Card className="mb-6"><CardContent className="pt-6">
          <div className="flex items-center gap-2 overflow-x-auto pb-2">
            {stages.map((s, i) => (
              <div key={s.label} className="flex items-center gap-2 shrink-0">
                <div className={`rounded-lg border p-3 min-w-[130px] ${s.nodes.length ? "border-primary bg-accent" : "border-dashed opacity-60"}`}>
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{s.label}</div>
                  {s.nodes.length === 0 && <div className="text-sm text-muted-foreground mt-1">Belum ada</div>}
                  {s.nodes.map((n) => (
                    <button key={n.no} onClick={() => n.id && STEP_ROUTES[s.label.toLowerCase()] && nav(STEP_ROUTES[s.label.toLowerCase()] + n.id)}
                      className="block font-mono text-xs font-semibold text-primary hover:underline mt-1">{n.no}</button>
                  ))}
                </div>
                {i < stages.length - 1 && <ArrowRight className="h-5 w-5 text-muted-foreground shrink-0" />}
              </div>
            ))}
          </div>
        </CardContent></Card>

        <div className="border rounded-md overflow-x-auto bg-card shadow-sm"><table className="w-full text-sm zebra"><thead className="bg-muted"><tr className="text-left text-xs uppercase tracking-wider text-muted-foreground"><th className="p-3">Barang</th><th className="p-3 text-right">Request</th><th className="p-3 text-right">RO</th><th className="p-3 text-right">PO</th><th className="p-3">SPK</th><th className="p-3 text-right">Diterima</th><th className="p-3 text-right">MI</th><th className="p-3 text-right">Outstanding</th></tr></thead>
          <tbody>{data.rows.map((r, i) => (<tr key={i} className="border-t"><td className="p-3">{r.item_code} — {r.item_name}</td><td className="p-3 text-right">{num(r.request)}</td><td className="p-3 text-right">{num(r.qty_ro)}</td><td className="p-3 text-right">{num(r.qty_po)}</td><td className="p-3 font-mono text-xs">{(r.spk || []).join(", ") || "-"}</td><td className="p-3 text-right">{num(r.qty_received)}</td><td className="p-3 text-right">{num(r.qty_mi)}</td><td className="p-3 text-right font-semibold">{num(r.outstanding)}</td></tr>))}</tbody></table></div>
      </>)}

      {!data && <div className="text-center py-16 text-muted-foreground"><FileText className="h-12 w-12 mx-auto mb-3 opacity-40" />Masukkan nomor MRO untuk melihat seluruh rangkaian dokumen</div>}
    </div>
  );
}
