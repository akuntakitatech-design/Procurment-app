import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import api, { apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { TransactionPageHeader } from "@/components/TransactionPageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Field } from "@/components/DatePicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { rupiah, fmtDateTime } from "@/lib/format";
import { dateOnly, fmtD, todayDate } from "@/lib/invoice";
import { checklistSummary } from "@/lib/docChecklist";
import { openTransmittalPrint } from "@/lib/transmittalPrint";
import { ArrowLeft, CheckCircle2, Printer, Send, Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";

const Info = ({ label, children }) => <div><div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div><div className="mt-0.5 text-sm font-medium">{children || "-"}</div></div>;
const ACT_LABEL = { create: "Transmittal dibuat", edit: "Transmittal diubah", edit_items: "Daftar invoice diubah", send: "Dikirim", receive: "Diterima", return: "Dikembalikan", delete: "Transmittal dihapus" };

export default function InvoiceTransmittalForm() {
  const { id } = useParams();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const { can, user } = useAuth();
  const isNew = !id;
  const [t, setT] = useState(null);
  const [eligible, setEligible] = useState([]);
  const [checked, setChecked] = useState([]);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState({ date: todayDate(), destination: "", sender_name: "", receiver_name: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const [dialog, setDialog] = useState("");
  const [reason, setReason] = useState("");
  const [proofFile, setProofFile] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    api.get(`/invoice-transmittals/${id}`).then((r) => {
      const d = r.data;
      setT(d);
      setForm({ date: dateOnly(d.date), destination: d.destination || "", sender_name: d.sender_name || "", receiver_name: d.receiver_name || "", notes: d.notes || "" });
    }).catch((e) => { setT(false); toast.error(apiError(e.response?.data?.detail)); });
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!isNew) return;
    api.get("/invoice-transmittals/eligible-invoices").then((r) => setEligible(r.data || [])).catch((e) => toast.error(apiError(e.response?.data?.detail)));
    const ids = (sp.get("ids") || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (ids.length) setChecked(ids);
    setForm((f) => ({ ...f, sender_name: f.sender_name || user?.name || "" }));
  }, [isNew]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return eligible;
    return eligible.filter((r) => `${r.invoice_no || ""} ${r.supplier_name || ""} ${r.tax_invoice_no || ""} ${r.po_nos || ""}`.toLowerCase().includes(q));
  }, [eligible, search]);
  const selectedTotal = useMemo(() => eligible.filter((r) => checked.includes(r.id)).reduce((s, r) => s + Number(r.amount || 0), 0), [eligible, checked]);

  const toggle = (iid) => setChecked((cur) => (cur.includes(iid) ? cur.filter((x) => x !== iid) : [...cur, iid]));
  const toggleAll = () => setChecked((cur) => (rows.every((r) => cur.includes(r.id)) ? cur.filter((x) => !rows.some((r) => r.id === x)) : [...new Set([...cur, ...rows.map((r) => r.id)])]));

  const create = async () => {
    if (!checked.length) return toast.error("Pilih minimal satu invoice");
    if (!form.destination.trim()) return toast.error("Tujuan/Departemen wajib diisi");
    if (!form.sender_name.trim()) return toast.error("Pengirim wajib diisi");
    setSaving(true);
    try {
      const r = await api.post("/invoice-transmittals", { ...form, invoice_ids: checked });
      toast.success(`Transmittal ${r.data.no} dibuat`);
      nav(`/transmittal/${r.data.id}`);
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const saveHeader = async () => {
    setSaving(true);
    try { await api.put(`/invoice-transmittals/${id}`, form); toast.success("Transmittal diperbarui"); load(); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const act = async () => {
    setBusy(true);
    try {
      if (dialog === "send") { await api.post(`/invoice-transmittals/${id}/send`, {}); toast.success("Transmittal ditandai Dikirim"); }
      else if (dialog === "receive") {
        let proofId = "";
        if (proofFile && t?.items?.length) {
          const first = t.items[0].invoice_id;
          const fd = new FormData();
          fd.append("file", proofFile); fd.append("entity", "invoice"); fd.append("entity_id", first);
          fd.append("category", "Bukti Serah Terima"); fd.append("note", `Bukti terima ${t.no}`);
          const up = await api.post("/attachments", fd, { headers: { "Content-Type": "multipart/form-data" } });
          proofId = up.data.id;
        }
        await api.post(`/invoice-transmittals/${id}/receive`, { receiver_name: form.receiver_name || "", proof_attachment_id: proofId });
        toast.success("Transmittal ditandai Diterima");
      } else if (dialog === "return") {
        if (!reason.trim()) { toast.error("Alasan pengembalian wajib diisi"); setBusy(false); return; }
        await api.post(`/invoice-transmittals/${id}/return`, { reason });
        toast.success("Transmittal dikembalikan");
      } else if (dialog === "delete") {
        await api.delete(`/invoice-transmittals/${id}`);
        toast.success("Transmittal dihapus"); nav("/transmittal"); return;
      }
      setDialog(""); setReason(""); setProofFile(null); load();
    } catch (e) { toast.error(apiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };

  const print = async () => {
    try { const r = await api.get(`/invoice-transmittals/${id}/print`); openTransmittalPrint(r.data); }
    catch (e) { toast.error(apiError(e.response?.data?.detail)); }
  };

  if (t === false) return <div className="p-8 text-muted-foreground" data-testid="transmittal-error">Transmittal tidak dapat ditampilkan.</div>;
  if (!isNew && !t) return <div className="p-8 text-muted-foreground">Memuat...</div>;
  const isDraft = isNew || t?.status === "Draft";
  const status = t?.status || "Draft";

  return (
    <div className="space-y-4" data-testid="transmittal-form-page">
      <TransactionPageHeader type="transmittal" mode={isNew ? "new" : "view"} number={t?.no || "Transmittal Baru"}
        subtitle={isNew ? "Pilih satu atau beberapa Invoice Vendor, lalu tentukan tujuan pengiriman dokumen." : `${t.destination || ""} · ${fmtD(t.date)}`}>
        <Button variant="outline" onClick={() => nav("/transmittal")}><ArrowLeft className="mr-2 h-4 w-4" />Kembali</Button>
        {isNew && can("transmittal.create") && <Button onClick={create} disabled={saving} data-testid="transmittal-save-btn">{saving ? "Menyimpan..." : "Buat Transmittal"}</Button>}
        {!isNew && can("transmittal.print") && <Button variant="outline" onClick={print} data-testid="transmittal-print-btn"><Printer className="mr-2 h-4 w-4" />Cetak</Button>}
        {!isNew && isDraft && can("transmittal.delete") && <Button variant="outline" className="text-destructive" onClick={() => setDialog("delete")} data-testid="transmittal-delete-btn"><Trash2 className="mr-2 h-4 w-4" />Hapus</Button>}
        {!isNew && isDraft && can("transmittal.edit") && <Button onClick={() => setDialog("send")} data-testid="transmittal-send-btn"><Send className="mr-2 h-4 w-4" />Tandai Dikirim</Button>}
        {!isNew && status === "Dikirim" && can("transmittal.receive") && <Button onClick={() => setDialog("receive")} data-testid="transmittal-receive-btn"><CheckCircle2 className="mr-2 h-4 w-4" />Tandai Diterima</Button>}
        {!isNew && ["Dikirim", "Diterima"].includes(status) && can("transmittal.receive") && <Button variant="outline" onClick={() => setDialog("return")} data-testid="transmittal-return-btn"><Undo2 className="mr-2 h-4 w-4" />Kembalikan</Button>}
      </TransactionPageHeader>

      {!isNew && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3 text-sm" data-testid="transmittal-status-bar">
          <StatusBadge status={status} />
          <span className="text-xs text-muted-foreground">{t.invoice_count} invoice · Total {rupiah(t.total_amount)}</span>
          {t.sent_at && <span className="text-xs text-muted-foreground">Dikirim {fmtDateTime(t.sent_at)} oleh {t.sent_by_name || t.sent_by}</span>}
          {t.received_at && <span className="text-xs text-muted-foreground">Diterima {fmtDateTime(t.received_at)} oleh {t.received_by_name || t.received_by}</span>}
          {t.returned_at && <span className="text-xs text-rose-600">Dikembalikan {fmtDateTime(t.returned_at)} — {t.return_reason}</span>}
        </div>
      )}

      <Card><CardContent className="space-y-4 pt-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="Tanggal Pengiriman"><Input type="date" value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} disabled={!isDraft} data-testid="transmittal-date" /></Field>
          <Field label="Tujuan / Departemen"><Input value={form.destination} onChange={(e) => setForm((f) => ({ ...f, destination: e.target.value }))} disabled={!isDraft} data-testid="transmittal-destination" /></Field>
          <Field label="Pengirim"><Input value={form.sender_name} onChange={(e) => setForm((f) => ({ ...f, sender_name: e.target.value }))} disabled={!isDraft} data-testid="transmittal-sender" /></Field>
          <Field label="Penerima"><Input value={form.receiver_name} onChange={(e) => setForm((f) => ({ ...f, receiver_name: e.target.value }))} disabled={!isDraft} data-testid="transmittal-receiver" /></Field>
        </div>
        <Field label="Keterangan"><Textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} disabled={!isDraft} data-testid="transmittal-notes" /></Field>
        {!isNew && isDraft && can("transmittal.edit") && <div><Button variant="outline" onClick={saveHeader} disabled={saving} data-testid="transmittal-save-header">Simpan Perubahan</Button></div>}
      </CardContent></Card>

      {isNew ? (
        <Card><CardContent className="space-y-3 pt-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-head text-sm font-semibold">Pilih Invoice Vendor</h3>
            <span className="text-xs text-muted-foreground">{checked.length} dipilih · {rupiah(selectedTotal)}</span>
          </div>
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari no invoice, supplier, faktur pajak, PO..." className="h-11 sm:h-9 max-w-md" data-testid="transmittal-search-invoice" />
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                <th className="p-2.5 w-10"><input type="checkbox" aria-label="Pilih semua" checked={rows.length > 0 && rows.every((r) => checked.includes(r.id))} onChange={toggleAll} data-testid="transmittal-toggle-all" /></th>
                <th className="p-2.5">Supplier</th><th className="p-2.5">No Invoice</th><th className="p-2.5">Faktur Pajak</th><th className="p-2.5">PO</th><th className="p-2.5 text-right">Nilai Invoice</th><th className="p-2.5">Kelengkapan</th>
              </tr></thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={7} className="p-6 text-center text-muted-foreground">Tidak ada invoice yang dapat dikirim (semua sudah ada di Transmittal aktif).</td></tr>}
                {rows.map((r) => {
                  const c = checklistSummary(r.doc_checklist);
                  return (
                    <tr key={r.id} className="border-t" data-testid={`transmittal-pick-${r.invoice_no}`}>
                      <td className="p-2.5"><input type="checkbox" checked={checked.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`Pilih ${r.invoice_no}`} data-testid={`transmittal-pick-check-${r.id}`} /></td>
                      <td className="p-2.5">{r.supplier_name}</td>
                      <td className="p-2.5 font-mono text-xs font-semibold">{r.invoice_no}</td>
                      <td className="p-2.5 font-mono text-xs">{r.tax_invoice_no || "-"}</td>
                      <td className="p-2.5 font-mono text-xs">{r.po_nos || "-"}</td>
                      <td className="p-2.5 text-right tabular-nums">{rupiah(r.amount)}</td>
                      <td className="p-2.5 text-xs">{c.complete ? "Lengkap" : `Belum lengkap (${c.pending.length})`}</td>
                    </tr>);
                })}
              </tbody>
            </table>
          </div>
        </CardContent></Card>
      ) : (
        <Card><CardContent className="space-y-3 pt-6">
          <h3 className="font-head text-sm font-semibold">Dokumen dalam Transmittal</h3>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[1000px] text-sm" data-testid="transmittal-items">
              <thead className="bg-muted"><tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                <th className="p-2.5">Vendor</th><th className="p-2.5">No Invoice</th><th className="p-2.5">Faktur Pajak</th><th className="p-2.5">PO</th><th className="p-2.5">DO</th><th className="p-2.5 text-right">Nilai Invoice</th><th className="p-2.5">Kelengkapan</th>
              </tr></thead>
              <tbody>{(t.items || []).map((i) => {
                const c = checklistSummary(i.checklist);
                return (
                  <tr key={i.id} className="border-t" data-testid={`transmittal-item-${i.invoice_no}`}>
                    <td className="p-2.5">{i.supplier_name}</td>
                    <td className="p-2.5 font-mono text-xs font-semibold">{i.invoice_no}</td>
                    <td className="p-2.5 font-mono text-xs">{i.tax_invoice_no || "-"}<div className="text-[10px] text-muted-foreground">{i.tax_invoice_date ? fmtD(i.tax_invoice_date) : ""}</div></td>
                    <td className="p-2.5 font-mono text-xs">{i.po_nos || "-"}</td>
                    <td className="p-2.5 font-mono text-xs">{i.do_nos || "-"}</td>
                    <td className="p-2.5 text-right tabular-nums">{rupiah(i.amount)}</td>
                    <td className="p-2.5 text-xs">{c.complete ? "Lengkap" : `Belum lengkap (${c.pending.length})`}</td>
                  </tr>);
              })}</tbody>
              <tfoot><tr className="border-t bg-muted/40 font-semibold"><td colSpan={5} className="p-2.5 text-right">TOTAL</td><td className="p-2.5 text-right tabular-nums" data-testid="transmittal-total">{rupiah(t.total_amount)}</td><td /></tr></tfoot>
            </table>
          </div>
          {t.proof && <div className="text-xs text-muted-foreground">Bukti serah terima: <a className="text-primary hover:underline" href={`${api.defaults.baseURL}/attachments/${t.proof.id}/download`} target="_blank" rel="noreferrer">{t.proof.original_filename}</a></div>}
        </CardContent></Card>
      )}

      {!isNew && (
        <Card><CardContent className="space-y-2 pt-6">
          <h3 className="font-head text-sm font-semibold">Riwayat Transmittal</h3>
          {(t.history || []).length === 0 && <p className="text-sm text-muted-foreground">Belum ada riwayat.</p>}
          {(t.history || []).map((h) => (
            <div key={h.id} className="rounded-lg border p-2.5 text-xs" data-testid={`transmittal-history-${h.action}`}>
              <div className="flex flex-wrap gap-2"><span className="font-semibold">{ACT_LABEL[h.action] || h.action}</span><span className="text-muted-foreground">{h.user_name || h.user} · {fmtDateTime(h.at)}</span></div>
              {h.reason && <div className="mt-1">Alasan: {h.reason}</div>}
            </div>
          ))}
        </CardContent></Card>
      )}

      <AlertDialog open={!!dialog} onOpenChange={(o) => { if (!o) { setDialog(""); setReason(""); setProofFile(null); } }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {dialog === "send" ? "Tandai Transmittal Dikirim?" : dialog === "receive" ? "Tandai Transmittal Diterima?" : dialog === "return" ? "Kembalikan Transmittal?" : "Hapus Transmittal?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {dialog === "send" && "Status berubah menjadi Dikirim dan waktu/pengguna dicatat di audit trail. Cetak dokumen tidak mengubah status."}
              {dialog === "receive" && "Status berubah menjadi Diterima. Anda dapat melampirkan bukti serah terima (opsional)."}
              {dialog === "return" && "Status berubah menjadi Dikembalikan. Invoice dapat dikirim ulang melalui Transmittal baru setelah ini."}
              {dialog === "delete" && "Hanya Transmittal Draft yang dapat dihapus."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {dialog === "return" && <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Alasan pengembalian (wajib)" data-testid="transmittal-return-reason" />}
          {dialog === "receive" && (
            <div className="space-y-2">
              <Field label="Nama Penerima (opsional)"><Input value={form.receiver_name} onChange={(e) => setForm((f) => ({ ...f, receiver_name: e.target.value }))} data-testid="transmittal-receive-name" /></Field>
              <Field label="Bukti Serah Terima (opsional)"><Input type="file" onChange={(e) => setProofFile(e.target.files?.[0] || null)} data-testid="transmittal-proof-file" /></Field>
            </div>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Batal</AlertDialogCancel>
            <AlertDialogAction onClick={act} disabled={busy} data-testid="transmittal-dialog-confirm">{busy ? "Memproses..." : "Ya, lanjutkan"}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
