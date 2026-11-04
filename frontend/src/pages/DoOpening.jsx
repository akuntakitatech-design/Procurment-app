import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useMasters } from "@/hooks/useMasters";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { DatePicker, Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { StatusBadge } from "@/components/StatusBadge";
import { fmtDate, rupiah, toNum, todayISO } from "@/lib/format";
import { ArrowLeft, Pencil, Plus, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";

const EMPTY = {
  no: "", date: todayISO(), supplier_id: "", division_id: "", project_id: "",
  po_no: "", ro_no: "", mro_no: "", spk: "", dpp: "", ppn: "", notes: "",
};

// DO sebelum periode berjalan yang dimasukkan sebagai saldo awal:
// nilai manual (DPP + PPN), tanpa baris item, dan tidak menggerakkan stok.
export default function DoOpening() {
  const nav = useNavigate();
  const { can } = useAuth();
  const masters = useMasters(["suppliers", "divisions", "projects"]);
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(null); // null = tertutup, {id?} = terbuka
  const [h, setH] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get("/opening-dos")
      .then((r) => setRows(r.data || []))
      .catch((e) => toast.error(apiError(e.response?.data?.detail) || "Gagal memuat DO saldo awal."))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const editId = params.get("edit");
  useEffect(() => {
    if (!editId || !rows.length) return;
    const row = rows.find((r) => r.id === editId);
    if (row && !form) {
      setForm({ id: row.id });
      setH({ ...EMPTY, ...row, date: String(row.date || "").slice(0, 10), dpp: String(row.dpp ?? ""), ppn: String(row.ppn ?? "") });
    }
  }, [editId, rows, form]);

  const total = useMemo(() => Math.round((toNum(h.dpp) + toNum(h.ppn)) * 100) / 100, [h.dpp, h.ppn]);
  const openCreate = () => { setForm({}); setH(EMPTY); params.delete("edit"); setParams(params, { replace: true }); };
  const closeForm = () => { setForm(null); setH(EMPTY); params.delete("edit"); setParams(params, { replace: true }); };
  const set = (k) => (v) => setH((c) => ({ ...c, [k]: v }));

  const save = async () => {
    if (!h.no.trim()) return toast.error("No. DO wajib diisi.");
    if (!h.date) return toast.error("Tanggal DO wajib diisi.");
    if (!h.supplier_id) return toast.error("Supplier wajib dipilih.");
    if (!h.division_id) return toast.error("Divisi wajib dipilih.");
    if (total <= 0) return toast.error("Nilai DO (DPP + PPN) harus lebih dari 0.");
    const body = {
      no: h.no.trim(), date: h.date, supplier_id: h.supplier_id, division_id: h.division_id,
      project_id: h.project_id || null, po_no: h.po_no, ro_no: h.ro_no, mro_no: h.mro_no, spk: h.spk,
      dpp: toNum(h.dpp), ppn: toNum(h.ppn), notes: h.notes,
    };
    setSaving(true);
    try {
      if (form?.id) await api.put(`/opening-dos/${form.id}`, body);
      else await api.post("/opening-dos", body);
      toast.success(form?.id ? "DO saldo awal diperbarui." : "DO saldo awal disimpan.");
      closeForm();
      load();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail) || "Gagal menyimpan DO saldo awal.");
    } finally { setSaving(false); }
  };

  const remove = async (row) => {
    if (!window.confirm(`Hapus DO saldo awal ${row.no}?`)) return;
    try {
      await api.delete(`/opening-dos/${row.id}`);
      toast.success("DO saldo awal dihapus.");
      load();
    } catch (e) {
      toast.error(apiError(e.response?.data?.detail) || "Gagal menghapus DO saldo awal.");
    }
  };

  return (
    <div data-testid="opening-do-page">
      <PageHeader title="DO Saldo Awal" testid="opening-do"
        subtitle="Dokumen DO sebelum periode berjalan. Nilai diinput manual (DPP + PPN), tanpa rincian barang dan tanpa pergerakan stok.">
        <Button variant="outline" onClick={() => nav("/do")} data-testid="opening-do-back"><ArrowLeft className="mr-2 h-4 w-4" />Daftar DO</Button>
        {can("create", "do") && !form && <Button onClick={openCreate} data-testid="opening-do-add"><Plus className="mr-2 h-4 w-4" />Tambah Saldo Awal</Button>}
      </PageHeader>

      {form && (
        <Card className="mb-4" data-testid="opening-do-form">
          <CardContent className="space-y-4 pt-6">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
              <Field label="No. DO"><Input value={h.no} onChange={(e) => set("no")(e.target.value)} placeholder="DO/2026/10/00001" data-testid="opening-do-no" /></Field>
              <Field label="Tanggal DO"><DatePicker value={h.date} onChange={set("date")} testid="opening-do-date" /></Field>
              <Field label="Supplier"><Combobox options={masters.opts("suppliers", (s) => s.legal_name || s.name)} value={h.supplier_id} onChange={set("supplier_id")} placeholder="Pilih supplier" testid="opening-do-supplier" /></Field>
              <Field label="Divisi"><Combobox options={masters.opts("divisions", (d) => d.name)} value={h.division_id} onChange={set("division_id")} placeholder="Pilih divisi" testid="opening-do-division" /></Field>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
              <Field label="No. PO"><Input value={h.po_no} onChange={(e) => set("po_no")(e.target.value)} placeholder="Opsional" data-testid="opening-do-po" /></Field>
              <Field label="No. RO"><Input value={h.ro_no} onChange={(e) => set("ro_no")(e.target.value)} placeholder="Opsional" data-testid="opening-do-ro" /></Field>
              <Field label="No. MRO"><Input value={h.mro_no} onChange={(e) => set("mro_no")(e.target.value)} placeholder="Opsional" data-testid="opening-do-mro" /></Field>
              <Field label="SPK"><Input value={h.spk} onChange={(e) => set("spk")(e.target.value)} placeholder="Opsional" data-testid="opening-do-spk" /></Field>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
              <Field label="Proyek"><Combobox options={masters.opts("projects", (p) => p.name)} value={h.project_id} onChange={set("project_id")} placeholder="Opsional" testid="opening-do-project" /></Field>
              <Field label="DPP"><Input type="number" step="0.01" min="0" value={h.dpp} onChange={(e) => set("dpp")(e.target.value)} className="text-right tabular-nums" data-testid="opening-do-dpp" /></Field>
              <Field label="PPN"><Input type="number" step="0.01" min="0" value={h.ppn} onChange={(e) => set("ppn")(e.target.value)} className="text-right tabular-nums" data-testid="opening-do-ppn" /></Field>
              <Field label="Nilai DO (DPP + PPN)"><Input value={rupiah(total)} disabled className="text-right tabular-nums" data-testid="opening-do-total" /></Field>
            </div>
            <Field label="Catatan"><Textarea value={h.notes} onChange={(e) => set("notes")(e.target.value)} rows={2} placeholder="Opsional" data-testid="opening-do-notes" /></Field>
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={closeForm} data-testid="opening-do-cancel"><X className="mr-2 h-4 w-4" />Batal</Button>
              <Button onClick={save} disabled={saving} data-testid="opening-do-save"><Save className="mr-2 h-4 w-4" />{form?.id ? "Simpan Perubahan" : "Simpan"}</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="overflow-x-auto rounded-xl border bg-card">
        <table className="w-full min-w-[1450px] text-sm" data-testid="opening-do-table">
          <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {["No. DO", "Tanggal", "Supplier", "No. PO", "No. RO", "No. MRO", "Proyek", "Divisi", "SPK", "DPP", "PPN", "Nilai DO", "Terpakai", "Sisa", ""].map((c, i) => (
              <th key={c + i} className={`p-2.5 ${i >= 9 ? "text-right" : ""}`}>{c}</th>
            ))}
          </tr></thead>
          <tbody>
            {loading && <tr><td colSpan={15} className="p-6 text-center text-muted-foreground">Memuat...</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={15} className="p-6 text-center text-muted-foreground" data-testid="opening-do-empty">Belum ada DO saldo awal.</td></tr>}
            {!loading && rows.map((r) => (
              <tr key={r.id} className="border-t" data-testid={`opening-do-row-${r.no}`}>
                <td className="p-2.5 font-mono text-xs font-semibold">{r.no}</td>
                <td className="p-2.5 text-xs">{fmtDate(r.date)}</td>
                <td className="p-2.5 text-xs">{r.supplier_name || "-"}</td>
                <td className="p-2.5 font-mono text-[11px]">{r.po_no || "-"}</td>
                <td className="p-2.5 font-mono text-[11px]">{r.ro_no || "-"}</td>
                <td className="p-2.5 font-mono text-[11px]">{r.mro_no || "-"}</td>
                <td className="p-2.5 text-xs">{r.project_name || "-"}</td>
                <td className="p-2.5 text-xs">{r.division_name || "-"}</td>
                <td className="p-2.5 text-xs">{r.spk || "-"}</td>
                <td className="p-2.5 text-right tabular-nums">{rupiah(r.dpp)}</td>
                <td className="p-2.5 text-right tabular-nums">{rupiah(r.ppn)}</td>
                <td className="p-2.5 text-right tabular-nums font-semibold">{rupiah(r.do_value)}</td>
                <td className="p-2.5 text-right tabular-nums">{rupiah(r.billed)}</td>
                <td className="p-2.5 text-right tabular-nums">
                  {rupiah(r.remaining)}
                  <div className="mt-1"><StatusBadge status={r.billed > 0 ? "Ditagihkan" : "Posted"} /></div>
                </td>
                <td className="p-2.5">
                  <div className="flex justify-end gap-1">
                    {can("edit", "do") && !(r.billed > 0) && (
                      <Button size="icon" variant="ghost" aria-label={`Ubah ${r.no}`} data-testid={`opening-do-edit-${r.no}`}
                        onClick={() => { setForm({ id: r.id }); setH({ ...EMPTY, ...r, date: String(r.date || "").slice(0, 10), dpp: String(r.dpp ?? ""), ppn: String(r.ppn ?? "") }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    )}
                    {can("delete", "do") && !(r.billed > 0) && (
                      <Button size="icon" variant="ghost" aria-label={`Hapus ${r.no}`} data-testid={`opening-do-delete-${r.no}`} onClick={() => remove(r)}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
