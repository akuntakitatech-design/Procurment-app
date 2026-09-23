import api, { API } from "@/lib/api";
import { rupiah, num, fmtDate } from "@/lib/format";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const DEFAULT_SECTIONS = ["header", "meta", "items", "message", "signatures", "footer"];
const DEFAULT_COLUMNS = ["item", "qty", "unit", "spk", "price", "total"];
const DEFAULT_META = ["date", "status", "requester", "receiver", "supplier", "buyer", "payment_term", "delivery_term", "division", "warehouse", "project", "unit", "supplier_invoice", "notes"];
const APPROVED_PO_STATUSES = new Set(["approved", "partially received", "fully received"]);
const poApproved = (doc) => APPROVED_PO_STATUSES.has(String(doc?.status || "").trim().toLowerCase());

const moduleKey = (type) => {
  const t = String(type || "").toUpperCase();
  return ({ TRF: "transfer", TRANSFER: "transfer", LOAN: "loan", RET: "loan", ADJ: "adjustment", ADJUSTMENT: "adjustment", OPN: "opname", OPNAME: "opname" }[t] || t.toLowerCase());
};

const defaultLayout = (type, title) => {
  const po = String(type || "").toUpperCase() === "PO";
  return {
    title: po ? "PURCHASE ORDER" : (title || type),
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
    meta_fields: [...DEFAULT_META],
    signature_labels: po ? ["Approved by,", "Signed by,"] : ["Dibuat Oleh", "Diperiksa Oleh", "Disetujui Oleh"],
    footer_text: po ? "" : "Dokumen ini dibuat oleh sistem ProcureFlow.",
    po_delivery_company_name: "",
    po_bill_company_name: "",
    po_bill_address: "",
    po_bill_contact: "",
    po_bill_phone: "",
    po_approved_name: "",
    po_approved_company: "",
  };
};

const metaValue = (key, doc, buyerText) => {
  const values = {
    date: doc.date ? fmtDate(doc.date) : "",
    status: doc.status || "",
    requester: doc.requester || "",
    receiver: doc.receiver || "",
    supplier: doc.supplier_name || "",
    buyer: buyerText || "",
    payment_term: doc.payment_term || "",
    delivery_term: doc.delivery_term || "",
    division: doc.division_name || doc.division || "",
    warehouse: doc.default_warehouse_name || doc.warehouse_name || "",
    project: doc.default_project_name || doc.project_name || "",
    unit: doc.default_unit_name || doc.unit_name || "",
    supplier_invoice: doc.supplier_invoice || "",
    notes: doc.notes || doc.internal_notes || "",
  };
  return values[key] || "";
};

const metaLabel = (key) => ({
  date: "Tanggal", status: "Status", requester: "Pemohon", receiver: "Penerima", supplier: "Supplier", buyer: "Buyer Contact",
  payment_term: "Payment Term", delivery_term: "Delivery Term", division: "Divisi", warehouse: "Gudang", project: "Proyek", unit: "Unit / Aset",
  supplier_invoice: "No. Faktur", notes: "Keterangan",
}[key] || key);

const columnLabel = (key) => ({ item: "Barang", qty: "Qty", unit: "Satuan", spk: "SPK", price: "Harga", discount: "Diskon", tax: "Pajak", total: "Total", notes: "Catatan" }[key] || key);

const lineValue = (key, line) => {
  const factor = Number(line.conversion_factor) || 1;
  const qty = line.display_qty ?? ((Number(line.qty) || 0) / factor);
  const price = line.display_price ?? ((Number(line.price) || 0) * factor);
  if (key === "item") return `${esc(line.item_code || "")}${line.item_code && line.item_name ? " — " : ""}${esc(line.item_name || "")}`;
  if (key === "qty") return num(qty);
  if (key === "unit") return esc(line.display_unit || line.unit || "");
  if (key === "spk") return esc(line.spk || "");
  if (key === "price") return rupiah(price);
  if (key === "discount") return rupiah(line.discount || 0);
  if (key === "tax") return esc(line.tax_name || (line.tax != null ? `${num(line.tax)}%` : ""));
  if (key === "total") return rupiah(line.total || 0);
  if (key === "notes") return esc(line.notes || "");
  return "";
};

const idrPlain = (v) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(Number(v || 0));
const idrPrice = (v) => `Rp ${idrPlain(v)}`;
const MONTHS_ID = ["Januari","Februari","Maret","April","Mei","Juni","Juli","Agustus","September","Oktober","November","Desember"];
const longDateId = (v) => {
  if (!v) return "";
  const s = String(v).slice(0,10).split("-");
  if (s.length !== 3) return fmtDate(v);
  const y = Number(s[0]), m = Number(s[1]), d = Number(s[2]);
  if (!y || !m || !d) return fmtDate(v);
  return `${d} ${MONTHS_ID[m-1] || ""} ${y}`;
};
const nl2br = (v) => esc(v || "").replace(/\n/g, "<br/>");

async function getMaster(name) {
  try { return (await api.get(`/master/${name}`)).data || []; } catch { return []; }
}

function renderTermsMessage(text, spk) {
  const raw = String(text || "").trim();
  if (!raw && !spk) return "";
  const lines = raw ? raw.split(/\r?\n/) : [];
  let spkShown = !spk;
  const html = lines.map((line) => {
    const t = String(line || "").trim();
    const low = t.toLowerCase();
    if (spk && !spkShown && low.startsWith("catatan")) {
      spkShown = true;
      return `<div class="term-line">SPK : ${esc(spk)}</div><div class="term-heading">${esc(t)}</div>`;
    }
    if (low === "term and condition" || low === "term & condition" || low.startsWith("catatan")) return `<div class="term-heading">${esc(t)}</div>`;
    if (!t) return `<div class="term-gap"></div>`;
    return `<div class="term-line">${esc(line)}</div>`;
  }).join("");
  return html + (spk && !spkShown ? `<div class="term-line">SPK : ${esc(spk)}</div>` : "");
}

function realPoHtml({ doc, company, layout, logoImg, code, supplier, project, signatureImg, showPrice }) {
  const primary = layout.primary_color || "#17396f";
  const font = layout.font_family || "Arial";
  const fontSize = Math.max(8, Number(layout.font_size) || 11);
  const margin = Math.max(5, Number(layout.margin_mm) || 10);
  const logoWidth = Number(layout.logo_width_mm) || 24;
  const lines = doc.lines || [];
  const approved = poApproved(doc);

  const contacts = supplier?.contacts || [];
  const marketing = contacts.find(x => x.is_primary) || contacts[0] || {};
  const banks = supplier?.banks || [];
  const bank = banks.find(x => x.id === doc.supplier_bank_id) || banks.find(x => x.is_primary) || banks[0] || {};
  const bankName = doc.supplier_bank_name || bank.bank_name || "";
  const bankNo = doc.supplier_bank_account_no || bank.account_no || "";
  const bankAccountName = doc.supplier_bank_account_name || bank.account_name || supplier?.legal_name || supplier?.name || doc.supplier_name || "";

  const deliveryCompany = layout.po_delivery_company_name || company.name || "";
  const billCompany = layout.po_bill_company_name || company.name || "";
  const billAddress = layout.po_bill_address || company.address || "";
  const deliveryProject = project?.name ? `Project ${project.name}` : "";
  const deliveryAddress = company.address || "";

  const subtotal = lines.reduce((a,l) => {
    const factor = Number(l.conversion_factor) || 1;
    const q = l.display_qty ?? ((Number(l.qty)||0)/factor);
    const p = l.display_price ?? ((Number(l.price)||0)*factor);
    return a + Number(q||0)*Number(p||0) - Number(l.discount||0);
  }, 0);
  const dpp = lines.reduce((a,l) => a + Number(l.dpp ?? ((Number(l.qty)||0)*(Number(l.price)||0)-Number(l.discount||0))), 0);
  const taxAmount = lines.reduce((a,l) => a + Number(l.tax_amount || 0), 0);
  const grand = Number(doc.grand_total ?? (dpp + taxAmount));
  const rates = [...new Set(lines.map(l => Number(l.tax || 0)).filter(x => x > 0))];
  const taxLabel = rates.length === 1 ? `PPN ${num(rates[0])}%` : (taxAmount ? "Pajak" : "PPN");

  const itemRows = lines.map((l,i) => {
    const factor = Number(l.conversion_factor) || 1;
    const q = l.display_qty ?? ((Number(l.qty)||0)/factor);
    const p = l.display_price ?? ((Number(l.price)||0)*factor);
    const amount = Number(l.dpp ?? (Number(q||0)*Number(p||0)-Number(l.discount||0)));
    const financialCells = showPrice ? `<td class="r price">${idrPrice(p)}</td><td class="r discount">${Number(l.discount||0) ? idrPlain(l.discount) : ""}</td><td class="r amount">${idrPlain(amount)}</td>` : "";
    return `<tr>
      <td class="c no">${i+1}</td>
      <td class="desc">${esc(l.item_name || l.item_code || "")}</td>
      <td class="c qty">${num(q)}</td>
      <td class="c unit">${esc(l.display_unit || l.unit || "")}</td>
      ${financialCells}
    </tr>`;
  }).join("");

  const approvedTask = [...(doc.approvals || [])].reverse().find(a => String(a.status || "").toLowerCase() === "approved" && a.acted_by);
  const approvedName = layout.po_approved_name || approvedTask?.acted_by || "";
  const approvedCompany = layout.po_approved_company || company.name || "";
  const signedName = marketing.name || "";
  const supplierCompany = supplier?.legal_name || supplier?.name || doc.supplier_name || "";

  const terms = layout.show_message ? renderTermsMessage(doc.document_message, doc.spk) : "";
  const qrHtml = layout.show_qr && code ? `<div class="verify">Verification Code: ${esc(code)}</div>` : "";
  const approvedSignature = approved && signatureImg ? `<img class="approved-signature" src="${signatureImg}"/>` : "";
  const colgroup = showPrice
    ? `<colgroup><col style="width:5%"><col style="width:39%"><col style="width:6%"><col style="width:7%"><col style="width:16%"><col style="width:12%"><col style="width:15%"></colgroup>`
    : `<colgroup><col style="width:7%"><col style="width:63%"><col style="width:12%"><col style="width:18%"></colgroup>`;
  const tableHead = showPrice
    ? `<thead><tr><th>No</th><th>Description</th><th colspan="2">Qty</th><th>Price</th><th>Discount</th><th>Amount</th></tr></thead>`
    : `<thead><tr><th>No</th><th>Description</th><th colspan="2">Qty</th></tr></thead>`;
  const totals = showPrice ? `<tfoot>
        <tr><td class="sum-spacer" colspan="4"></td><td class="sum-label" colspan="2">Total</td><td class="sum-value">${idrPlain(subtotal)}</td></tr>
        <tr><td class="sum-spacer" colspan="4"></td><td class="sum-label" colspan="2">DPP</td><td class="sum-value">${idrPlain(dpp)}</td></tr>
        <tr><td class="sum-spacer" colspan="4"></td><td class="sum-label" colspan="2">${esc(taxLabel)}</td><td class="sum-value">${idrPlain(taxAmount)}</td></tr>
        <tr class="grand"><td class="sum-spacer" colspan="4"></td><td class="sum-label" colspan="2">Grand Total</td><td class="sum-value">${idrPlain(grand)}</td></tr>
      </tfoot>` : "";
  const emptyColspan = showPrice ? 7 : 4;

  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(doc.no || "PO")}</title>
  <style>
    @page{size:${layout.paper_size || "A4"} ${layout.orientation || "portrait"};margin:0}
    *{box-sizing:border-box}
    body{margin:0;padding:${margin}mm;color:${primary};font-family:${font},Arial,sans-serif;font-size:${fontSize}px;-webkit-print-color-adjust:exact;print-color-adjust:exact;background:white;position:relative}
    .draft-watermark{position:fixed;left:50%;top:48%;transform:translate(-50%,-50%) rotate(-32deg);font-size:74px;font-weight:900;letter-spacing:8px;color:#6b7280;opacity:.14;z-index:9999;pointer-events:none;user-select:none}
    .top{position:relative;min-height:29mm}.brand{width:46mm}.real-logo{width:${logoWidth}mm;max-height:22mm;object-fit:contain;display:block}.brand-name{font-weight:700;font-size:${Math.max(9,fontSize)}px;margin-top:2mm}.po-title{position:absolute;top:2mm;left:50%;transform:translateX(-50%);font-size:${fontSize+7}px;font-weight:800;letter-spacing:.3px;white-space:nowrap}
    .info-grid{display:grid;grid-template-columns:46% 52%;gap:2%;align-items:start}.address-block{line-height:1.25}.address-block .label{font-weight:700;margin-top:0}.address-block .label.bill{margin-top:4mm}.address-block .line{min-height:3.5mm}.meta-box{border-top:.25mm solid ${primary};border-bottom:.25mm solid ${primary};padding:1.2mm 1.5mm}.meta-row{display:grid;grid-template-columns:38% 3% 59%;line-height:1.42}.meta-row .lab{white-space:nowrap}
    .items{width:100%;border-collapse:collapse;border-spacing:0;margin-top:8mm;table-layout:fixed}.items th,.items td{border:.25mm solid ${primary};padding:1.3mm 1.7mm;vertical-align:middle}.items th{text-align:center;font-weight:700}.items .no{width:5%}.items .desc{width:39%}.items .qty{width:6%}.items .unit{width:7%}.items .price{width:16%}.items .discount{width:12%}.items .amount{width:15%}.c{text-align:center}.r{text-align:right}.items .price,.items .amount,.items .discount{white-space:nowrap}.items tfoot td{border:.25mm solid ${primary};padding:1.25mm 1.7mm}.items tfoot .sum-spacer{border:none!important;padding:0;background:transparent}.items tfoot .sum-label{font-weight:700;text-align:left}.items tfoot .sum-value{text-align:right;white-space:nowrap}.items tfoot .grand .sum-label,.items tfoot .grand .sum-value{font-weight:800}
    .terms{margin-top:7mm;line-height:1.35}.term-heading{font-weight:800;margin-top:1.5mm}.term-line{white-space:pre-wrap;margin-left:1.8mm}.term-gap{height:1.5mm}
    .bank-wrap{margin-top:4mm}.bank-title{font-weight:800;margin-bottom:1mm}.bank-table{width:100%;border-collapse:collapse;border-spacing:0;text-align:center}.bank-table th,.bank-table td{border-top:.25mm solid ${primary};border-bottom:.25mm solid ${primary};padding:1mm 1.5mm}.bank-table th{font-weight:700}
    .signatures{display:grid;grid-template-columns:1fr 1fr;gap:30mm;text-align:center;margin-top:6mm;page-break-inside:avoid}.sign-label{min-height:4mm}.sign-space{height:18mm;position:relative}.approved-signature{display:block;max-width:38mm;max-height:17mm;object-fit:contain;margin:0 auto}.sign-name{font-weight:800;text-decoration:underline}.sign-company{margin-top:.6mm}.verify{font-size:8px;text-align:right;margin-top:3mm;color:#64748b}
    @media print{body{print-color-adjust:exact;-webkit-print-color-adjust:exact}.items{break-inside:auto}.items tr{break-inside:avoid}}
  </style></head><body>
    ${!approved ? `<div class="draft-watermark">DRAFT</div>` : ""}
    <div class="top">
      <div class="brand">${layout.show_logo && logoImg ? `<img class="real-logo" src="${logoImg}"/>` : ""}<div class="brand-name">${esc(deliveryCompany)}</div></div>
      <div class="po-title">${esc(layout.title || "PURCHASE ORDER")}</div>
    </div>
    <div class="info-grid">
      <div class="address-block">
        <div class="label">Please Delivery to :</div>
        ${deliveryCompany ? `<div class="line">${esc(deliveryCompany)}</div>` : ""}
        ${deliveryProject ? `<div class="line">${esc(deliveryProject)}</div>` : ""}
        ${deliveryAddress ? `<div class="line">${nl2br(deliveryAddress)}</div>` : ""}
        <div class="label bill">Please Bill to :</div>
        ${billCompany ? `<div class="line">${esc(billCompany)}</div>` : ""}
        ${billAddress ? `<div class="line">${nl2br(billAddress)}</div>` : ""}
        ${layout.po_bill_contact ? `<div class="line">Up : ${esc(layout.po_bill_contact)}</div>` : ""}
        ${layout.po_bill_phone ? `<div class="line">Hp : ${esc(layout.po_bill_phone)}</div>` : ""}
      </div>
      <div class="meta-box">
        <div class="meta-row"><span class="lab">PO No.</span><span>:</span><span>${esc(doc.no || "")}</span></div>
        <div class="meta-row"><span class="lab">PO Date</span><span>:</span><span>${esc(longDateId(doc.date))}</span></div>
        <div class="meta-row"><span class="lab">Supplier</span><span>:</span><span>${esc(doc.supplier_name || supplier?.name || "")}</span></div>
        <div class="meta-row"><span class="lab">Supplier ref</span><span>:</span><span>${esc(doc.supplier_ref || doc.supplier_notes || "")}</span></div>
        <div class="meta-row"><span class="lab">Buyer's Contact</span><span>:</span><span>${esc(doc.buyer_contact_name || "")}</span></div>
        <div class="meta-row"><span class="lab">Phone</span><span>:</span><span>${esc(doc.buyer_contact_phone || "")}</span></div>
        <div class="meta-row"><span class="lab">Marketing Contact</span><span>:</span><span>${esc(marketing.name || "")}</span></div>
        <div class="meta-row"><span class="lab">Phone</span><span>:</span><span>${esc(marketing.phone || "")}</span></div>
        <div class="meta-row"><span class="lab">Payment terms</span><span>:</span><span>${esc(doc.payment_term || "")}</span></div>
        <div class="meta-row"><span class="lab">Delivery terms</span><span>:</span><span>${esc(doc.delivery_term || "")}</span></div>
      </div>
    </div>
    <table class="items">
      ${colgroup}
      ${tableHead}
      <tbody>${itemRows || `<tr><td colspan="${emptyColspan}" class="c">Tidak ada item</td></tr>`}</tbody>
      ${totals}
    </table>
    ${terms ? `<div class="terms">${terms}</div>` : ""}
    ${bankName || bankNo || bankAccountName ? `<div class="bank-wrap"><div class="bank-title">Pembayaran dilakukan ke Rekening :</div><table class="bank-table"><thead><tr><th>Nama Bank</th><th>No. Rekening</th><th>Atas Nama</th></tr></thead><tbody><tr><td>${esc(bankName)}</td><td>${esc(bankNo)}</td><td>${esc(bankAccountName)}</td></tr></tbody></table></div>` : ""}
    ${layout.show_signatures ? `<div class="signatures"><div><div class="sign-label">${esc(layout.signature_labels?.[0] || "Approved by,")}</div><div class="sign-space">${approvedSignature}</div><div class="sign-name">${esc(approvedName)}</div><div class="sign-company">${esc(approvedCompany)}</div></div><div><div class="sign-label">${esc(layout.signature_labels?.[1] || "Signed by,")}</div><div class="sign-space"></div><div class="sign-name">${esc(signedName)}</div><div class="sign-company">${esc(supplierCompany)}</div></div></div>` : ""}
    ${qrHtml}
    <script>window.onload=function(){setTimeout(function(){window.print()},550)}</script>
  </body></html>`;
  return html;
}

export async function printDoc(type, doc, opts = {}) {
  if (!doc) return;
  let code = null;
  try {
    const r = await api.post("/verify/generate", { doc_type: type, doc_id: doc.id, doc_no: doc.no, status: doc.status });
    code = r.data.code;
  } catch {}

  let company = {};
  try { company = (await api.get("/settings/company")).data; } catch {}

  let savedLayouts = {};
  try { savedLayouts = (await api.get("/settings/print_layouts")).data?.modules || {}; } catch {}
  const key = moduleKey(type);
  const layout = { ...defaultLayout(type, opts.title || type), ...(savedLayouts[key] || {}) };
  if (key === "po" && !layout.template_style) layout.template_style = "real_reference";
  layout.sections = layout.sections?.length ? layout.sections : [...DEFAULT_SECTIONS];
  layout.columns = layout.columns?.length ? layout.columns : [...DEFAULT_COLUMNS];
  layout.meta_fields = layout.meta_fields?.length ? layout.meta_fields : [...DEFAULT_META];
  layout.signature_labels = layout.signature_labels?.length ? layout.signature_labels : (key === "po" ? ["Approved by,", "Signed by,"] : ["Dibuat Oleh", "Diperiksa Oleh", "Disetujui Oleh"]);

  const verifyUrl = `${window.location.origin}/verify/${code}`;
  const qrImg = code ? `https://api.qrserver.com/v1/create-qr-code/?size=110x110&data=${encodeURIComponent(verifyUrl)}` : "";
  const logoImg = company.logo_path ? `${API}/company/logo?v=${encodeURIComponent(company.logo_version || "1")}` : "";
  let signatureImg = "";
  if (key === "po") {
    try {
      const s = (await api.get("/settings/print_layouts/po/signature-status")).data || {};
      if (s.available) signatureImg = `${API}/settings/print_layouts/po/signature?v=${encodeURIComponent(s.version || "1")}`;
    } catch {}
  }
  const showPrice = !!opts.showPrice;
  const lines = doc.lines || [];
  const buyerText = doc.buyer_contact_name ? `${doc.buyer_contact_name}${doc.buyer_contact_position ? ` — ${doc.buyer_contact_position}` : ""}${doc.buyer_contact_phone ? ` · ${doc.buyer_contact_phone}` : ""}` : "";

  if (key === "po" && layout.template_style === "real_reference") {
    const [suppliers, projects] = await Promise.all([getMaster("suppliers"), getMaster("projects")]);
    const supplier = suppliers.find(x => x.id === doc.supplier_id) || {};
    const project = projects.find(x => x.id === doc.default_project_id) || {};
    const html = realPoHtml({ doc, company, layout, logoImg, code, supplier, project, signatureImg, showPrice });
    const w = window.open("", "_blank");
    w.document.write(html); w.document.close();
    return;
  }

  const financialCols = new Set(["price", "discount", "tax", "total"]);
  const columns = (layout.columns || []).filter(c => showPrice || !financialCols.has(c));

  const headerHtml = () => {
    const styleClass = `hd ${layout.header_style || "classic"}`;
    return `<div class="${styleClass}"><div class="brand">${layout.show_logo && logoImg ? `<img class="logo" src="${logoImg}"/>` : ""}<div><div class="co">${esc(company.name || "PT. Perusahaan Anda")}</div>${layout.show_company_address ? `<div class="address">${esc(company.address || "")}</div>` : ""}</div></div><div class="doc-title"><div class="title">${esc(layout.title || opts.title || type)}</div><div class="doc-no">${esc(doc.no)}</div></div></div>`;
  };

  const metaHtml = () => {
    const fields = (layout.meta_fields || []).map(k => [k, metaValue(k, doc, buyerText)]).filter(([,v]) => v !== "" && v != null);
    if (!fields.length) return "";
    return `<div class="meta">${fields.map(([k,v]) => `<div><b>${esc(metaLabel(k))}:</b> ${k === "status" ? `<span class="status">${esc(v)}</span>` : esc(v)}</div>`).join("")}</div>`;
  };

  const itemsHtml = () => {
    if (!columns.length) return "";
    const rows = lines.map((l) => `<tr>${columns.map(c => `<td class="col-${c}">${lineValue(c,l)}</td>`).join("")}</tr>`).join("");
    const heads = columns.map(c => `<th>${esc(columnLabel(c))}</th>`).join("");
    const totalIndex = columns.indexOf("total");
    const foot = showPrice && totalIndex >= 0 ? `<tfoot><tr>${columns.map((c,i)=> i === totalIndex ? `<td class="money grand">${rupiah(doc.grand_total)}</td>` : i === Math.max(0,totalIndex-1) ? `<td class="grand-label">Grand Total</td>` : `<td></td>`).join("")}</tr></tfoot>` : "";
    return `<table><thead><tr>${heads}</tr></thead><tbody>${rows}</tbody>${foot}</table>`;
  };

  const messageHtml = () => layout.show_message && doc.document_message ? `<div class="terms"><div class="terms-title">Pesan / Ketentuan Dokumen</div><div class="terms-body">${esc(doc.document_message)}</div></div>` : "";
  const signaturesHtml = () => layout.show_signatures ? `<div class="sign">${layout.signature_labels.map((label,i)=>`<div><div>${esc(label)}</div>${key === "po" && i === 0 && poApproved(doc) && signatureImg ? `<img class="generic-signature" src="${signatureImg}"/>` : ""}<div class="line">${i===0 ? esc(doc.created_by || "") : "&nbsp;"}</div></div>`).join("")}</div>` : "";
  const footerHtml = () => `<div class="ft"><div class="footer-text">${esc(layout.footer_text || "")}</div>${layout.show_qr && qrImg ? `<div class="qr"><img src="${qrImg}" width="90" height="90"/><div>${esc(code)}</div></div>` : ""}</div>`;

  const sectionFns = { header: headerHtml, meta: metaHtml, items: itemsHtml, message: messageHtml, signatures: signaturesHtml, footer: footerHtml };
  const bodySections = layout.sections.map(s => sectionFns[s] ? sectionFns[s]() : "").join("\n");

  const primary = layout.primary_color || "#1e3a8a";
  const fontSize = Number(layout.font_size) || 11;
  const margin = Number(layout.margin_mm) || 12;
  const paper = layout.paper_size || "A4";
  const orientation = layout.orientation || "portrait";
  const font = layout.font_family || "Arial";
  const logoWidth = Number(layout.logo_width_mm) || 28;
  const draftMark = key === "po" && !poApproved(doc) ? `<div class="draft-watermark">DRAFT</div>` : "";

  const html = `<!doctype html><html><head><title>${esc(doc.no)}</title>
  <style>
    @page{size:${paper} ${orientation};margin:0}
    *{box-sizing:border-box}
    body{margin:0;padding:${margin}mm;color:#111;font-family:${font},sans-serif;font-size:${fontSize}px;-webkit-print-color-adjust:exact;print-color-adjust:exact;position:relative}
    .draft-watermark{position:fixed;left:50%;top:48%;transform:translate(-50%,-50%) rotate(-32deg);font-size:74px;font-weight:900;letter-spacing:8px;color:#6b7280;opacity:.14;z-index:9999;pointer-events:none}
    .hd{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;padding-bottom:10px;margin-bottom:13px;border-bottom:3px solid ${primary}}
    .hd.minimal{border-bottom:1px solid #cbd5e1}.hd.boxed{border:1px solid #cbd5e1;border-left:5px solid ${primary};padding:10px}
    .brand{display:flex;align-items:flex-start;gap:10px}.logo{width:${logoWidth}mm;max-height:22mm;object-fit:contain}.co{font-size:18px;font-weight:800;color:${primary}}.address{font-size:10px;color:#64748b;margin-top:3px;max-width:90mm;white-space:pre-line}.doc-title{text-align:right}.title{font-size:20px;font-weight:800}.doc-no{font-family:monospace;font-weight:700;margin-top:4px}
    .meta{display:grid;grid-template-columns:1fr 1fr;gap:4px 22px;margin:9px 0 12px}.meta div{font-size:${Math.max(9,fontSize-1)}px}.status{display:inline-block;padding:1px 8px;border:1px solid ${primary};border-radius:999px;color:${primary};font-weight:700}
    table{width:100%;border-collapse:collapse;margin-top:9px;page-break-inside:auto}thead{display:table-header-group}tr{page-break-inside:avoid}th,td{border:1px solid #cbd5e1;padding:6px 7px;font-size:${Math.max(8,fontSize-1)}px}th{background:#f1f5f9;text-align:left;text-transform:uppercase;font-size:${Math.max(8,fontSize-2)}px}.col-qty,.col-price,.col-discount,.col-total{text-align:right}.col-tax{white-space:nowrap}.money{text-align:right}.grand{font-weight:800}.grand-label{text-align:right;font-weight:800}
    .terms{margin-top:15px;border:1px solid #cbd5e1;border-radius:6px;padding:9px 11px;page-break-inside:avoid}.terms-title{font-weight:700;margin-bottom:6px;color:${primary}}.terms-body{white-space:pre-wrap;line-height:1.5;font-size:${Math.max(8,fontSize-1)}px}
    .sign{display:flex;justify-content:space-around;gap:20px;margin-top:40px;text-align:center;page-break-inside:avoid}.sign>div{min-width:120px;flex:1;max-width:180px}.generic-signature{display:block;max-width:36mm;max-height:18mm;object-fit:contain;margin:6px auto -4px}.line{border-top:1px solid #333;margin-top:50px;padding-top:4px}
    .ft{margin-top:20px;display:flex;justify-content:space-between;align-items:flex-end;gap:20px;page-break-inside:avoid}.footer-text{font-size:9px;color:#666;white-space:pre-line}.qr{text-align:center;font-family:monospace;font-size:8px}
  </style></head><body>${draftMark}${bodySections}<script>window.onload=function(){setTimeout(function(){window.print()},500)}</script></body></html>`;

  const w = window.open("", "_blank");
  w.document.write(html); w.document.close();
}