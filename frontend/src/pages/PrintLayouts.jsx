import { useEffect, useMemo, useRef, useState } from "react";
import api, { API, apiError } from "@/lib/api";
import { buildPoPrintHtml } from "@/lib/poPrintReal";
import { printImage, companyLogoPath, poSignaturePath } from "@/lib/printAssets";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/DatePicker";
import { Combobox } from "@/components/Combobox";
import { Save, ArrowUp, ArrowDown, RotateCcw, FileText, Upload, Trash2 } from "lucide-react";
import { toast } from "sonner";

const MODULES = [
  ["mro", "MRO", "Material Request Order"], ["ro", "RO", "Request Order"], ["po", "PO", "Purchase Order"],
  ["do", "DO", "Delivery Order / Penerimaan"], ["mi", "MI", "Material Issued"], ["transfer", "TRF", "Transfer Antar Gudang"],
  ["loan", "LOAN", "Pinjam Antar Gudang"], ["adjustment", "ADJ", "Stock Adjustment"], ["opname", "OPN", "Stock Opname"],
];

const DEFAULT_SECTIONS = ["header", "meta", "items", "message", "signatures", "footer"];
const SECTION_LABELS = { header: "Header Perusahaan & Dokumen", meta: "Informasi Dokumen", items: "Tabel Item", message: "Pesan / Ketentuan", signatures: "Tanda Tangan", footer: "Footer & QR" };
const DEFAULT_COLUMNS = ["item", "qty", "unit", "spk", "price", "total"];
const COLUMN_LABELS = { item: "Barang", qty: "Qty", unit: "Satuan", spk: "SPK", price: "Harga", discount: "Diskon", tax: "Pajak", total: "Total", notes: "Catatan" };
const META_FIELDS = [
  ["date", "Tanggal"], ["status", "Status"], ["requester", "Pemohon"], ["receiver", "Penerima"], ["supplier", "Supplier"],
  ["buyer", "Buyer Contact"], ["payment_term", "Payment Term"], ["delivery_term", "Delivery Term"], ["division", "Divisi"],
  ["warehouse", "Gudang"], ["project", "Proyek"], ["unit", "Unit / Aset"], ["supplier_invoice", "No. Faktur Supplier"], ["notes", "Keterangan"],
];

const defaultLayout = (code, name) => {
  const po = code === "PO";
  return {
    title: po ? "PURCHASE ORDER" : name,
    paper_size: "A4",
    orientation: "portrait",
    font_family: "Arial",
    font_size: 11,
    primary_color: po ? "#17396f" : "#1e3a8a",
    margin_mm: po ? 10 : 12,
    logo_width_mm: po ? 24 : 28,
    header_style: "classic",
    template_style: po ? "real_reference" : "generic",
    show_logo: true,
    show_company_address: true,
    show_qr: po ? false : true,
    show_message: true,
    show_signatures: true,
    sections: [...DEFAULT_SECTIONS],
    columns: po ? ["item", "qty", "unit", "price", "discount", "total"] : [...DEFAULT_COLUMNS],
    meta_fields: META_FIELDS.map(([key]) => key),
    signature_labels: po ? ["Approved by,", "Signed by,"] : ["Dibuat Oleh", "Diperiksa Oleh", "Disetujui Oleh"],
    footer_text: po ? "" : "Dokumen ini dibuat oleh sistem ProcureFlow.",
    po_delivery_company_name: "",
    po_bill_company_name: "",
    po_bill_address: "",
    po_bill_contact: "",
    po_bill_phone: "",
    po_approved_name: "",
    po_approved_company: "",
    code,
  };
};

const normalize = (src, code, name) => ({
  ...defaultLayout(code, name), ...(src || {}),
  sections: src?.sections?.length ? src.sections : [...DEFAULT_SECTIONS],
  columns: src?.columns?.length ? src.columns : defaultLayout(code, name).columns,
  meta_fields: src?.meta_fields?.length ? src.meta_fields : META_FIELDS.map(([key]) => key),
  signature_labels: src?.signature_labels?.length ? src.signature_labels : defaultLayout(code, name).signature_labels,
});

function move(arr, idx, dir) {
  const out = [...arr]; const j = idx + dir;
  if (j < 0 || j >= out.length) return out;
  [out[idx], out[j]] = [out[j], out[idx]];
  return out;
}

// Pratinjau = fungsi cetak PO yang sama (buildPoPrintHtml) dengan data transaksi CONTOH; identitas perusahaan/logo/TTD dari pengaturan.
const SAMPLE_GROUP = "04|NORMAL|12|11|12";
const SAMPLE_PO = {
  no: "PO/2026/07/00115", date: "2026-07-23", status: "Approved", tax_engine_version: 2, supplier_name: "PT. Supplier Contoh", supplier_ref: "Penawaran 785/Q/VII/2026",
  buyer_contact_name: "Nama Buyer", buyer_contact_phone: "+62 812-0000-0000", payment_term: "N-30", delivery_term: "H+30 Setelah PO",
  gross_total: 267900000, item_discount_total: 0, final_discount_amount: 0, subtotal_after_discount: 267900000, dpp_total: 267900000, non_ppn_total: 0,
  dpp_other_total: 245575000, tax_total: 29469000, tax_facility_total: 0, ppnbm_total: 0, grand_total: 297369000,
  tax_groups: [{ group: SAMPLE_GROUP, trx_code: "04", dpp: 267900000, dpp_other: 245575000, ppn: 29469000 }], tax_rules_snapshot: [{ group: SAMPLE_GROUP, tax_rate: 12 }],
  dp_enabled: true, dp_type: "percentage", dp_value: 40, dp_amount: 118947600, dp_remaining: 178421400,
  approvals: [{ seq: 1, status: "Approved", acted_by: "Nama Approver" }],
  document_message: "Term and Condition\n1 Apabila dalam waktu 7 hari setelah PO diterima material / barang tidak dikirim, maka PO otomatis dianggap batal\n2 Pengiriman dilakukan secara partial dari vendor\n\nCatatan\n1 Pesanan Pembelian ini harus memenuhi syarat dan ketentuan yang berlaku setelah pesanan pembelian diterima\n2 Invoice hanya dapat di proses apabila melampirkan dokumen sebagai berikut:\n* Invoice\n* Kwitansi (Harus Bermaterai)\n* Faktur Pajak (Jika PKP)",
  lines: [["a", 'Smith Clamp 14"', 30, 980000], ["b", 'Smith Clamp 20"', 50, 1140000], ["c", 'Smith Clamp 24"', 150, 1210000]].map(([id, item_name, qty, price]) => ({
    id, item_name, qty, price, discount: 0, dpp: qty * price, display_unit: "Ea", tax_mode: "EXCLUDE", tax_code: "PPN04", tax_name: "PPN DPP Nilai Lain", tax_trx_code: "04", mro_refs: ["MRO 2248"], ro_refs: [{ ro_no: "RO/2026/07/00031" }] })),
};
const SAMPLE_ALLOC = [{ item_line_id: "c", allocations: [{ spk_number: "SPK/001", allocated_qty: 150 }], non_spk_qty: 0 }];
const SAMPLE_SUPPLIER = { name: "PT. Supplier Contoh", contacts: [{ name: "Marketing Supplier", phone: "+62 822-0000-0000", is_primary: true }], banks: [{ bank_name: "Bank Contoh", account_no: "000-000-000-000-0", account_name: "PT. Supplier Contoh", is_primary: true }] };
const A4_PX = [794, 1123];

function RealPoPreview({ layout, signature }) {
  const [company, setCompany] = useState({});
  const [logoImg, setLogoImg] = useState("");
  const [signatureImg, setSignatureImg] = useState("");
  const [sampleStatus, setSampleStatus] = useState("Approved");
  const [width, setWidth] = useState(520);
  const boxRef = useRef(null);
  useEffect(() => { api.get("/settings/company").then((r) => setCompany(r.data || {})).catch(() => setCompany({})); }, []);
  const logoPath = companyLogoPath(company);
  const sigPath = poSignaturePath(signature);
  useEffect(() => { let on = true; printImage(logoPath).then((u) => on && setLogoImg(u)); return () => { on = false; }; }, [logoPath]);
  useEffect(() => { let on = true; printImage(sigPath).then((u) => on && setSignatureImg(u)); return () => { on = false; }; }, [sigPath]);
  useEffect(() => {
    const el = boxRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const html = useMemo(() => buildPoPrintHtml({
    doc: { ...SAMPLE_PO, status: sampleStatus }, allocLines: SAMPLE_ALLOC, company, layout, supplier: SAMPLE_SUPPLIER, project: { name: "Contoh Proyek" }, showPrice: true, internal: false, autoPrint: false,
    logoImg: layout.show_logo === false ? "" : logoImg, signatureImg,
  }), [company, layout, logoImg, signatureImg, sampleStatus]);
  const scale = Math.min(1, width / A4_PX[0]);
  return <div className="space-y-2">
    <div className="flex items-center gap-2 text-xs" data-testid="po-preview-status-toggle">
      <span className="text-muted-foreground">Contoh status:</span>
      {[["Approved", "Approved (TTD/stempel)"], ["Draft", "Draft (watermark)"]].map(([v, l]) => <Button key={v} type="button" size="sm" variant={sampleStatus === v ? "default" : "outline"} onClick={() => setSampleStatus(v)} data-testid={`po-preview-status-${v.toLowerCase()}`} aria-pressed={sampleStatus === v}>{l}</Button>)}
    </div>
    <div ref={boxRef} className="rounded-xl border bg-slate-100 p-0 overflow-hidden" data-testid="po-print-preview">
      <div style={{ width: A4_PX[0] * scale, height: A4_PX[1] * scale }} className="mx-auto">
        <iframe title="Pratinjau cetak PO" srcDoc={html} sandbox="allow-same-origin" data-testid="po-print-preview-frame"
          style={{ width: A4_PX[0], height: A4_PX[1], border: 0, background: "#fff", transform: `scale(${scale})`, transformOrigin: "0 0" }} />
      </div>
    </div>
  </div>;
}

function Preview({ layout, active, signature }) {
  if (active === "po" && layout.template_style === "real_reference") return <RealPoPreview layout={layout} signature={signature}/>;
  const sections = layout.sections || DEFAULT_SECTIONS;
  const columnNames = layout.columns || DEFAULT_COLUMNS;
  const sample = { date: "17/09/2026", status: "Approved", supplier: "PT Supplier Contoh", buyer: "Nama Buyer", payment_term: "30 Hari", delivery_term: "Franco Gudang" };
  const section = (key) => {
    if (key === "header") return <div key={key} className="border-b-2 pb-3 flex justify-between gap-4" style={{ borderColor: layout.primary_color }}><div><div className="font-bold text-lg" style={{ color: layout.primary_color }}>PT. PERUSAHAAN ANDA</div>{layout.show_company_address && <div className="text-[10px] text-slate-500">Alamat perusahaan</div>}</div><div className="text-right"><div className="font-bold text-lg">{layout.title}</div><div className="font-mono text-xs">{layout.code}/2026/09/00001</div></div></div>;
    if (key === "meta") return <div key={key} className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">{layout.meta_fields.slice(0,8).map((m)=><div key={m}><b>{META_FIELDS.find(([k])=>k===m)?.[1] || m}:</b> {sample[m] || "Contoh"}</div>)}</div>;
    if (key === "items") return <table key={key} className="w-full border-collapse text-[9px]"><thead><tr>{columnNames.map(c=><th key={c} className="border bg-slate-100 p-1 text-left">{COLUMN_LABELS[c] || c}</th>)}</tr></thead><tbody><tr>{columnNames.map(c=><td key={c} className="border p-1">{c === "item" ? "BRG-001 — Barang Contoh" : c === "qty" ? "10" : c === "unit" ? "PCS" : c === "price" ? "Rp 100.000" : c === "total" ? "Rp 1.000.000" : "-"}</td>)}</tr></tbody></table>;
    if (key === "message") return layout.show_message ? <div key={key} className="rounded border p-2 text-[9px]"><b>Pesan / Ketentuan Dokumen</b><div className="mt-1 text-slate-600">Term and condition serta catatan transaksi tampil di sini.</div></div> : null;
    if (key === "signatures") return layout.show_signatures ? <div key={key} className="grid grid-cols-3 gap-4 pt-4 text-center text-[9px]">{layout.signature_labels.map((x,i)=><div key={i}><div>{x}</div><div className="mt-10 border-t pt-1">Nama / Tanda Tangan</div></div>)}</div> : null;
    if (key === "footer") return <div key={key} className="flex justify-between items-end text-[8px] text-slate-500"><span>{layout.footer_text}</span>{layout.show_qr && <div className="h-12 w-12 border grid place-items-center">QR</div>}</div>;
    return null;
  };
  return <div className="rounded-xl border bg-slate-100 p-4 overflow-auto"><div className="mx-auto bg-white shadow-sm space-y-4" style={{ width: layout.orientation === "landscape" ? 560 : 400, minHeight: layout.orientation === "landscape" ? 400 : 560, padding: `${Math.max(8, Number(layout.margin_mm)||12)}px`, fontFamily: layout.font_family, fontSize: `${layout.font_size || 11}px` }}>{sections.map(section)}</div></div>;
}

export default function PrintLayouts() {
  const [all, setAll] = useState({});
  const [active, setActive] = useState("po");
  const [saving, setSaving] = useState(false);
  const [signature, setSignature] = useState({available:false,version:null});
  const [signatureFile, setSignatureFile] = useState(null);
  const loadSignature=()=>api.get("/settings/print_layouts/po/signature-status").then(r=>setSignature(r.data||{available:false})).catch(()=>setSignature({available:false}));
  useEffect(() => { api.get("/settings/print_layouts").then(r => setAll(r.data?.modules || {})).catch(() => setAll({})); loadSignature(); }, []);
  const meta = MODULES.find(([k]) => k === active) || MODULES[0];
  const layout = useMemo(() => normalize(all[active], meta[1], meta[2]), [all, active, meta]);
  const setLayout = (patch) => setAll(cur => ({ ...cur, [active]: { ...layout, ...patch } }));
  const toggleMeta = (key) => setLayout({ meta_fields: layout.meta_fields.includes(key) ? layout.meta_fields.filter(x=>x!==key) : [...layout.meta_fields, key] });
  const toggleColumn = (key) => setLayout({ columns: layout.columns.includes(key) ? layout.columns.filter(x=>x!==key) : [...layout.columns, key] });
  const save = async () => { try { setSaving(true); const modules={}; MODULES.forEach(([k,c,n])=>{modules[k]=normalize(all[k],c,n);}); const r=await api.put("/settings/print_layouts",{modules}); setAll(r.data?.modules||modules); toast.success("Layout dokumen tersimpan"); } catch(e){ toast.error(apiError(e.response?.data?.detail)); } finally{ setSaving(false); } };
  const reset = () => setAll(cur => ({ ...cur, [active]: defaultLayout(meta[1], meta[2]) }));
  const uploadSignature=async()=>{if(!signatureFile)return toast.error("Pilih file tanda tangan terlebih dahulu");try{const fd=new FormData();fd.append("file",signatureFile);await api.post("/settings/print_layouts/po/signature",fd,{headers:{"Content-Type":"multipart/form-data"}});setSignatureFile(null);await loadSignature();toast.success("Tanda tangan PO tersimpan");}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const deleteSignature=async()=>{try{await api.delete("/settings/print_layouts/po/signature");setSignatureFile(null);await loadSignature();toast.success("Tanda tangan PO dihapus");}catch(e){toast.error(apiError(e.response?.data?.detail));}};
  const moduleOptions = MODULES.map(([value,code,name])=>({value,label:`${code} — ${name}`,selectedLabel:code}));

  return <div className="space-y-5">
    <PageHeader title="Layout Dokumen" subtitle="Atur desain print-out setiap transaksi secara independen."><Button variant="outline" onClick={reset}><RotateCcw className="h-4 w-4 mr-2"/>Reset Modul</Button><Button onClick={save} disabled={saving}><Save className="h-4 w-4 mr-2"/>{saving?"Menyimpan...":"Simpan Layout"}</Button></PageHeader>
    <div className="grid grid-cols-1 xl:grid-cols-[460px_minmax(0,1fr)] gap-5">
      <div className="space-y-4">
        <Card><CardContent className="pt-6 space-y-4"><Field label="Jenis Dokumen"><Combobox options={moduleOptions} value={active} onChange={setActive}/></Field>{active === "po" && <Field label="Template Visual PO"><Combobox options={[{value:"real_reference",label:"REAL — Referensi PO Existing"},{value:"generic",label:"Generic / Builder"}]} value={layout.template_style||"real_reference"} onChange={v=>setLayout({template_style:v})}/></Field>}<div className="grid grid-cols-2 gap-3"><Field label="Judul Dokumen"><Input value={layout.title} onChange={e=>setLayout({title:e.target.value})}/></Field><Field label="Ukuran Kertas"><Combobox options={[{value:"A4",label:"A4"},{value:"A5",label:"A5"},{value:"Letter",label:"Letter"}]} value={layout.paper_size} onChange={v=>setLayout({paper_size:v})}/></Field><Field label="Orientasi"><Combobox options={[{value:"portrait",label:"Portrait"},{value:"landscape",label:"Landscape"}]} value={layout.orientation} onChange={v=>setLayout({orientation:v})}/></Field><Field label="Gaya Header"><Combobox options={[{value:"classic",label:"Classic"},{value:"minimal",label:"Minimal"},{value:"boxed",label:"Boxed"}]} value={layout.header_style} onChange={v=>setLayout({header_style:v})}/></Field><Field label="Font"><Combobox options={["Arial","Inter","Helvetica","Georgia","Times New Roman"].map(v=>({value:v,label:v}))} value={layout.font_family} onChange={v=>setLayout({font_family:v})}/></Field><Field label="Ukuran Font"><Input type="number" min="8" max="16" value={layout.font_size} onChange={e=>setLayout({font_size:Number(e.target.value)})}/></Field><Field label="Margin (mm)"><Input type="number" min="5" max="30" value={layout.margin_mm} onChange={e=>setLayout({margin_mm:Number(e.target.value)})}/></Field><Field label="Warna Utama"><Input type="color" value={layout.primary_color} onChange={e=>setLayout({primary_color:e.target.value})}/></Field></div><div className="grid grid-cols-2 gap-2 text-sm">{[["show_logo","Tampilkan Logo"],["show_company_address","Alamat Perusahaan"],["show_qr","QR Verifikasi"],["show_message","Pesan/Ketentuan"],["show_signatures","Tanda Tangan"]].map(([k,l])=><label key={k} className="flex items-center gap-2 rounded-lg border px-3 py-2"><input type="checkbox" checked={!!layout[k]} onChange={e=>setLayout({[k]:e.target.checked})}/>{l}</label>)}</div></CardContent></Card>

        {active === "po" && layout.template_style === "real_reference" && <Card><CardContent className="pt-6 space-y-3"><div><div className="font-semibold">Detail Template REAL</div><div className="text-xs text-muted-foreground">Kosongkan field yang ingin mengambil data otomatis dari perusahaan/master supplier/proyek.</div></div><Field label="Nama Perusahaan - Delivery To"><Input value={layout.po_delivery_company_name||""} onChange={e=>setLayout({po_delivery_company_name:e.target.value})} placeholder="Otomatis dari perusahaan"/></Field><Field label="Nama Perusahaan - Bill To"><Input value={layout.po_bill_company_name||""} onChange={e=>setLayout({po_bill_company_name:e.target.value})} placeholder="Otomatis dari perusahaan"/></Field><Field label="Alamat Bill To"><Input value={layout.po_bill_address||""} onChange={e=>setLayout({po_bill_address:e.target.value})} placeholder="Otomatis dari alamat perusahaan"/></Field><div className="grid grid-cols-2 gap-3"><Field label="Up / PIC Bill To"><Input value={layout.po_bill_contact||""} onChange={e=>setLayout({po_bill_contact:e.target.value})}/></Field><Field label="HP Bill To"><Input value={layout.po_bill_phone||""} onChange={e=>setLayout({po_bill_phone:e.target.value})}/></Field></div><div className="grid grid-cols-2 gap-3"><Field label="Approved By"><Input value={layout.po_approved_name||""} onChange={e=>setLayout({po_approved_name:e.target.value})} placeholder="Bisa otomatis dari approval"/></Field><Field label="Perusahaan Approver"><Input value={layout.po_approved_company||""} onChange={e=>setLayout({po_approved_company:e.target.value})} placeholder="Otomatis dari perusahaan"/></Field></div></CardContent></Card>}

        {active === "po" && <Card><CardContent className="pt-6 space-y-3"><div><div className="font-semibold">Tanda Tangan PO</div><div className="text-xs text-muted-foreground">Upload PNG/JPG/WEBP. Tanda tangan hanya dicetak pada PO yang sudah Approved; PO Draft tetap tanpa tanda tangan dan memakai watermark DRAFT.</div></div>{signature.available&&<div className="h-28 rounded-lg border bg-white p-2 flex items-center justify-center"><img src={`${API}/settings/print_layouts/po/signature?v=${encodeURIComponent(signature.version||"1")}`} alt="Tanda tangan tersimpan" data-testid="po-signature-saved-img" className="max-h-full max-w-full object-contain"/></div>}<Input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>setSignatureFile(e.target.files?.[0]||null)}/><div className="flex gap-2"><Button type="button" variant="outline" onClick={uploadSignature} disabled={!signatureFile}><Upload className="h-4 w-4 mr-2"/>Upload Tanda Tangan</Button>{signature.available&&<Button type="button" variant="ghost" onClick={deleteSignature}><Trash2 className="h-4 w-4 mr-2 text-destructive"/>Hapus</Button>}</div></CardContent></Card>}

        {!(active === "po" && layout.template_style === "real_reference") && <>
        <Card><CardContent className="pt-6 space-y-3"><div><div className="font-semibold">Urutan Bagian</div><div className="text-xs text-muted-foreground">Atur posisi blok dari atas ke bawah.</div></div>{layout.sections.map((s,i)=><div key={s} className="flex items-center gap-2 rounded-lg border p-2"><FileText className="h-4 w-4 text-muted-foreground"/><span className="flex-1 text-sm">{SECTION_LABELS[s]||s}</span><Button size="icon" variant="outline" onClick={()=>setLayout({sections:move(layout.sections,i,-1)})} disabled={i===0}><ArrowUp className="h-4 w-4"/></Button><Button size="icon" variant="outline" onClick={()=>setLayout({sections:move(layout.sections,i,1)})} disabled={i===layout.sections.length-1}><ArrowDown className="h-4 w-4"/></Button></div>)}</CardContent></Card>
        <Card><CardContent className="pt-6 space-y-3"><div className="font-semibold">Informasi Header Dokumen</div><div className="grid grid-cols-2 gap-2 text-sm">{META_FIELDS.map(([k,l])=><label key={k} className="flex items-center gap-2 rounded-lg border px-3 py-2"><input type="checkbox" checked={layout.meta_fields.includes(k)} onChange={()=>toggleMeta(k)}/>{l}</label>)}</div></CardContent></Card>
        <Card><CardContent className="pt-6 space-y-3"><div className="font-semibold">Kolom Tabel Item</div><div className="grid grid-cols-2 gap-2 text-sm">{Object.entries(COLUMN_LABELS).map(([k,l])=><label key={k} className="flex items-center gap-2 rounded-lg border px-3 py-2"><input type="checkbox" checked={layout.columns.includes(k)} onChange={()=>toggleColumn(k)}/>{l}</label>)}</div><div className="space-y-2 pt-2">{layout.columns.map((c,i)=><div key={c} className="flex items-center gap-2 rounded-lg border p-2"><span className="flex-1 text-sm">{COLUMN_LABELS[c]||c}</span><Button size="icon" variant="outline" onClick={()=>setLayout({columns:move(layout.columns,i,-1)})} disabled={i===0}><ArrowUp className="h-4 w-4"/></Button><Button size="icon" variant="outline" onClick={()=>setLayout({columns:move(layout.columns,i,1)})} disabled={i===layout.columns.length-1}><ArrowDown className="h-4 w-4"/></Button></div>)}</div></CardContent></Card>
        </>}

        <Card><CardContent className="pt-6 space-y-3"><div className="font-semibold">Tanda Tangan & Footer</div>{layout.signature_labels.map((v,i)=><Field key={i} label={`Kolom Tanda Tangan ${i+1}`}><Input value={v} onChange={e=>setLayout({signature_labels:layout.signature_labels.map((x,j)=>j===i?e.target.value:x)})}/></Field>)}<Field label="Teks Footer"><Textarea rows={3} value={layout.footer_text||""} onChange={e=>setLayout({footer_text:e.target.value})} placeholder={active==="po"?"Alamat kantor pusat, telepon, fax (boleh beberapa baris)":""} data-testid="print-footer-text"/></Field></CardContent></Card>
      </div>
      <div className="xl:sticky xl:top-[86px] xl:self-start"><div className="mb-2"><div className="font-semibold">Preview Layout</div><div className="text-xs text-muted-foreground">Preview mengikuti struktur template. Data transaksi asli digunakan saat print.</div></div><Preview layout={layout} active={active} signature={signature}/></div>
    </div>
  </div>;
}
