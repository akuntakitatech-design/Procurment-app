import api, { API } from "@/lib/api";
import { rupiah, num, fmtDate } from "@/lib/format";
import { dpRows } from "@/lib/poDp";
import { isPoV2, poV2SummaryRows, fmtIdr } from "@/lib/poTaxPrint";
import { buildPoPrintHtml, poApproved } from "@/lib/poPrintReal";
import { printImage, companyLogoPath, poSignaturePath } from "@/lib/printAssets";
import { layoutMargins, cssMargin, mergeLayout } from "@/lib/printMargins";

export { realPoHtml, buildPoPrintHtml, poRefGroups, poRefLabel, poSpkCell, renderTermsMessage } from "@/lib/poPrintReal";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SPK_DOC_TYPES = new Set(["mro", "ro", "po", "do", "mi"]);
// Cetak PO: nomor MRO yang terhubung ke baris (backend `mro_refs`, termasuk via RO) di atas nama barang, font kecil.
// Tanpa referensi -> sel Description identik dengan sebelumnya (hanya nama barang).
export const poDescCell = (l) => {
  const name = esc(l.item_name || l.item_code || "");
  const nos = [...new Set((l.mro_refs || []).map((x) => String(x || "").trim()).filter(Boolean))];
  return nos.length ? `<div class="mro-ref">${esc(nos.join(", "))}</div><div class="item-name">${name}</div>` : name;
};
// Horizontal compact allocation text, e.g. "SPK-001: 3 • SPK-002: 4 • Non-SPK: 3"
const allocText = (summary) => {
  if (!summary) return "Non-SPK";
  const parts = (summary.allocations || []).map((a) => `${a.spk_number || a.spk_id}: ${num(a.allocated_qty)}`);
  const nonSpk = Number(summary.non_spk_qty || 0);
  if (parts.length === 0) return `Non-SPK: ${num(summary.item_qty)}`;
  if (nonSpk > 1e-9) parts.push(`Non-SPK: ${num(nonSpk)}`);
  return parts.join(" • ");
};
const DEFAULT_SECTIONS = ["header", "meta", "items", "message", "signatures", "footer"];
const DEFAULT_COLUMNS = ["item", "qty", "unit", "spk", "price", "total"];
const DEFAULT_META = ["date", "status", "requester", "receiver", "supplier", "buyer", "payment_term", "delivery_term", "division", "warehouse", "project", "unit", "supplier_invoice", "notes"];

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
    margin_top_mm: 12, margin_right_mm: po ? 15 : 12, margin_bottom_mm: 12, margin_left_mm: po ? 15 : 12,
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
    // Transfer: default header (bukan sumber pergerakan barang).
    trf_from_default: doc.from_name || "",
    trf_to_default: doc.to_name || "",
    trf_project_default: doc.project_name || "",
    // Pinjam Barang: default header (bukan sumber pergerakan barang) + Target Pengembalian.
    loan_from_default: doc.from_name || "",
    loan_to_default: doc.to_name || "",
    loan_project_default: doc.project_name || "",
    loan_due: doc.due_date ? fmtDate(doc.due_date) : "",
    // Penyesuaian Stok: default header (bukan sumber stok/ledger — gudang dibaca per baris).
    adj_type: doc.adj_type || "",
    adj_reason: doc.reason || "",
    adj_wh_default: doc.warehouse_name || "",
    adj_project_default: doc.project_name || "",
  };
  return values[key] || "";
};

const metaLabel = (key) => ({
  date: "Tanggal", status: "Status", requester: "Pemohon", receiver: "Penerima", supplier: "Supplier", buyer: "Buyer Contact",
  payment_term: "Payment Term", delivery_term: "Delivery Term", division: "Divisi", warehouse: "Gudang", project: "Proyek", unit: "Unit / Aset",
  supplier_invoice: "No. Faktur", notes: "Keterangan",
  trf_from_default: "Gudang Asal Default", trf_to_default: "Gudang Tujuan Default", trf_project_default: "Project Default",
  loan_from_default: "Gudang Pemberi Default", loan_to_default: "Gudang Peminjam Default", loan_project_default: "Project Default", loan_due: "Target Pengembalian",
  adj_type: "Jenis Penyesuaian", adj_reason: "Alasan", adj_wh_default: "Gudang Default", adj_project_default: "Project Default",
}[key] || key);

const columnLabel = (key) => ({ item: "Barang", qty: "Qty", unit: "Satuan", spk: "SPK", alokasi: "Alokasi SPK", price: "Harga", discount: "Diskon", tax: "Pajak", total: "Total", notes: "Keterangan", from_wh: "Gudang Asal", to_wh: "Gudang Tujuan", project: "Project", unit_asset: "Unit/Aset", loan_from_wh: "Gudang Pemberi", loan_to_wh: "Gudang Peminjam", adj_wh: "Gudang", adj_uom: "Satuan", adj_before: "Stok Sebelum", adj_qty: "Penyesuaian", adj_after: "Stok Sesudah", adj_cost: "Biaya Satuan", adj_reason: "Alasan" }[key] || key);

const lineValue = (key, line) => {
  const factor = Number(line.conversion_factor) || 1;
  const qty = line.display_qty ?? ((Number(line.qty) || 0) / factor);
  const price = line.display_price ?? ((Number(line.price) || 0) * factor);
  if (key === "item") return `${esc(line.item_code || "")}${line.item_code && line.item_name ? " — " : ""}${esc(line.item_name || "")}`;
  if (key === "qty") return num(qty);
  if (key === "unit") return esc(line.display_unit || line.unit || "");
  if (key === "spk") return esc(line.spk || "");
  if (key === "alokasi") return esc(line._spk_alloc || "Non-SPK");
  if (key === "price") return rupiah(price);
  if (key === "discount") return rupiah(line.discount || 0);
  if (key === "tax") return esc(line.tax_name || (line.tax != null ? `${num(line.tax)}%` : ""));
  if (key === "total") return rupiah(line.total || 0);
  if (key === "notes") return esc(line.notes || "");
  // Transfer multi gudang: gudang/project/unit dibaca per baris (bukan default header).
  if (key === "from_wh") return esc(line.from_name || "");
  if (key === "to_wh") return esc(line.to_name || "");
  if (key === "project") return esc(line.project_name || "");
  if (key === "unit_asset") return esc(line.unit_name || "");
  // Pinjam Barang multi gudang: gudang pemberi/peminjam per baris.
  if (key === "loan_from_wh") return esc(line.from_name || "");
  if (key === "loan_to_wh") return esc(line.to_name || "");
  // Penyesuaian Stok multi gudang: gudang/stok per baris (legacy: fallback header sudah di-resolve backend).
  if (key === "adj_wh") return esc(line.warehouse_name || "");
  if (key === "adj_uom") return esc(line.uom_label || "");
  if (key === "adj_before") return line.before == null ? "-" : num(line.before);
  if (key === "adj_qty") return `${Number(line.adjustment) > 0 ? "+" : ""}${num(line.adjustment)}`;
  if (key === "adj_after") return line.after == null ? "-" : num(line.after);
  if (key === "adj_cost") return Number(line.adjustment) > 0 && line.approved_unit_cost != null ? rupiah(line.approved_unit_cost) : "-";
  if (key === "adj_reason") return esc(line.reason || "");
  return "";
};

async function getMaster(name) {
  try { return (await api.get(`/lookup/${name}?active_only=false`)).data || []; } catch { return []; }
}

/** KETENTUAN PEMBAYARAN di cetak PO: syarat Uang Muka (DP) + keterangan. Bukan bukti/pencatatan pembayaran. */
function paymentTermsHtml(doc, showPrice, money) {
  const dp = showPrice ? dpRows(doc) : [];
  if (!dp.length && !doc.payment_notes && !(doc.dp_enabled && !showPrice)) return "";
  const rows = dp.map((r) => `<div class="term-row" data-dp="${r.key}"><span>${esc(r.label)}</span><span>${money(r.amount)}</span></div>`).join("");
  const hidden = doc.dp_enabled && !showPrice ? `<div class="term-line">Uang Muka (DP) disyaratkan</div>` : "";
  const note = doc.dp_enabled ? `<div class="term-note">Syarat pembayaran pada PO — bukan bukti pembayaran.</div>` : "";
  return `<div class="terms payment-notes" data-section="payment-terms"><div class="term-heading">Ketentuan Pembayaran</div>${rows}${hidden}${note}${doc.payment_notes ? `<div class="term-line">${esc(doc.payment_notes)}</div>` : ""}</div>`;
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
  const layout = mergeLayout(defaultLayout(type, opts.title || type), savedLayouts[key] || {});
  if (key === "po" && !layout.template_style) layout.template_style = "real_reference";
  layout.sections = layout.sections?.length ? layout.sections : [...DEFAULT_SECTIONS];
  layout.columns = layout.columns?.length ? layout.columns : [...DEFAULT_COLUMNS];
  layout.meta_fields = layout.meta_fields?.length ? layout.meta_fields : [...DEFAULT_META];
  layout.signature_labels = layout.signature_labels?.length ? layout.signature_labels : (key === "po" ? ["Approved by,", "Signed by,"] : ["Dibuat Oleh", "Diperiksa Oleh", "Disetujui Oleh"]);

  const verifyUrl = `${window.location.origin}/verify/${code}`;
  const qrImg = code ? `https://api.qrserver.com/v1/create-qr-code/?size=110x110&data=${encodeURIComponent(verifyUrl)}` : "";
  // Logo & TTD/stempel di-embed (data URL) agar pasti termuat di jendela cetak & PDF.
  const logoImg = layout.show_logo === false ? "" : await printImage(companyLogoPath(company));
  let signatureImg = "";
  if (key === "po" && poApproved(doc)) { // TTD/stempel hanya untuk PO Approved (logika existing)
    try {
      const s = (await api.get("/settings/print_layouts/po/signature-status")).data || {};
      signatureImg = await printImage(poSignaturePath(s));
    } catch {}
  }
  const showPrice = !!opts.showPrice;
  const internal = !!opts.internal;
  const lines = doc.lines || [];
  let allocLines = [];
  // Phase C: attach this document's OWN stage SPK allocation to each line (horizontal text)
  if (SPK_DOC_TYPES.has(key) && doc.id) {
    try {
      const ar = await api.get(`/spk-allocations/${key}/doc/${doc.id}`);
      const amap = {};
      allocLines = ar.data.lines || [];
      allocLines.forEach((l) => { amap[l.item_line_id] = allocText(l); });
      lines.forEach((l) => { l._spk_alloc = amap[l.id] || "Non-SPK"; });
    } catch { /* backward-compatible: no allocation -> Non-SPK */ }
  }
  const buyerText = doc.buyer_contact_name ? `${doc.buyer_contact_name}${doc.buyer_contact_position ? ` — ${doc.buyer_contact_position}` : ""}${doc.buyer_contact_phone ? ` · ${doc.buyer_contact_phone}` : ""}` : "";

  if (key === "po" && layout.template_style === "real_reference") {
    const [suppliers, projects] = await Promise.all([getMaster("suppliers"), getMaster("projects")]);
    const supplier = suppliers.find(x => x.id === doc.supplier_id) || {};
    const project = projects.find(x => x.id === doc.default_project_id) || {};
    const html = buildPoPrintHtml({ doc, allocLines, company, layout, logoImg, code, supplier, project, signatureImg, showPrice, internal });
    const w = window.open("", "_blank");
    w.document.write(html); w.document.close();
    return;
  }

  const financialCols = new Set(["price", "discount", "tax", "total"]);
  const columns = (layout.columns || []).filter(c => showPrice || !financialCols.has(c));
  // CP4 UX: item-level Keterangan must print — inject right after "Barang".
  if (key === "transfer") {
    // Khusus Transfer: satu dokumen bisa multi gudang -> gudang/project/unit dicetak PER BARIS;
    // header hanya dicetak sebagai default dokumen (label "... Default").
    const si = columns.indexOf("spk");
    if (si >= 0) columns.splice(si, 1);
    const ui = columns.indexOf("unit");
    const extra = ["from_wh", "to_wh", "project", "unit_asset"].filter((c) => !columns.includes(c));
    columns.splice(ui >= 0 ? ui + 1 : columns.length, 0, ...extra);
    if (!columns.includes("notes")) { const ii = columns.indexOf("item"); columns.splice(ii >= 0 ? ii + 1 : 0, 0, "notes"); }
    layout.meta_fields = (layout.meta_fields || []).flatMap((k) => (k === "warehouse" ? ["trf_from_default", "trf_to_default"] : k === "project" ? ["trf_project_default"] : [k]));
  }
  if (key === "loan") {
    // Khusus Pinjam Barang: satu dokumen bisa multi gudang -> gudang/project/unit dicetak PER BARIS;
    // header hanya default dokumen (label "... Default") + Target Pengembalian & Pemohon.
    const si = columns.indexOf("spk");
    if (si >= 0) columns.splice(si, 1);
    const ui = columns.indexOf("unit");
    const extra = ["loan_from_wh", "loan_to_wh", "project", "unit_asset"].filter((c) => !columns.includes(c));
    columns.splice(ui >= 0 ? ui + 1 : columns.length, 0, ...extra);
    if (!columns.includes("notes")) { const ii = columns.indexOf("item"); columns.splice(ii >= 0 ? ii + 1 : 0, 0, "notes"); }
    const mf = (layout.meta_fields || []).flatMap((k) => (k === "warehouse" ? ["loan_from_default", "loan_to_default"] : k === "project" ? ["loan_project_default"] : [k]));
    if (!mf.includes("loan_due")) mf.splice(Math.max(0, mf.indexOf("date") + 1), 0, "loan_due");
    if (!mf.includes("requester")) mf.push("requester");
    layout.meta_fields = mf;
  }
  if (key === "adjustment") {
    // Khusus Penyesuaian Stok: kolom baris tetap (gudang/project/unit/stok per baris). Biaya hanya bila izin harga
    // (backend juga meredaksi biaya untuk user tanpa view_purchase_price).
    columns.splice(0, columns.length, "item", "adj_wh", "project", "unit_asset", "adj_uom", "adj_before", "adj_qty", "adj_after", ...(showPrice ? ["adj_cost"] : []), "adj_reason");
    const base = (layout.meta_fields || []).filter((k) => !["warehouse", "project", "notes", "division"].includes(k));
    layout.meta_fields = [...base, "division", "adj_type", "adj_wh_default", "adj_project_default", "adj_reason", "notes"];
  }
  if (SPK_DOC_TYPES.has(key) && !columns.includes("notes")) {
    const ii = columns.indexOf("item");
    columns.splice(ii >= 0 ? ii + 1 : 0, 0, "notes");
  }
  // Phase C: ensure an "Alokasi SPK" column exists for SPK document types (after Satuan)
  if (SPK_DOC_TYPES.has(key) && !columns.includes("alokasi")) {
    const ui = columns.indexOf("unit");
    columns.splice(ui >= 0 ? ui + 1 : columns.length, 0, "alokasi");
  }

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
    const sumRow = (label, value, cls = "money") => `<tr class="tax-sum">${columns.map((c,i)=> i === totalIndex ? `<td class="${cls}">${value}</td>` : i === Math.max(0,totalIndex-1) ? `<td class="grand-label">${esc(label)}</td>` : `<td></td>`).join("")}</tr>`;
    // F2: PO v2 -> rincian DPP/PPN dari nilai tersimpan (urutan = Ringkasan PO di form). PO lama (v1) tidak berubah.
    const v2Rows = key === "po" && isPoV2(doc) ? poV2SummaryRows(doc).filter((r) => !r.grand).map((r) => sumRow(`${r.sub ? "↳ " : ""}${r.label}`, `${r.neg && r.value ? "- " : ""}${r.key === "ppn_facility" ? `(${fmtIdr(r.value)})` : fmtIdr(r.value)}`)).join("") : "";
    const foot = showPrice && totalIndex >= 0 ? `<tfoot>${v2Rows}<tr>${columns.map((c,i)=> i === totalIndex ? `<td class="money grand">${key === "po" && isPoV2(doc) ? fmtIdr(doc.grand_total) : rupiah(doc.grand_total)}</td>` : i === Math.max(0,totalIndex-1) ? `<td class="grand-label">Grand Total</td>` : `<td></td>`).join("")}</tr></tfoot>` : "";
    return `<table><thead><tr>${heads}</tr></thead><tbody>${rows}</tbody>${foot}</table>`;
  };

  const messageHtml = () => `${layout.show_message && doc.document_message ? `<div class="terms"><div class="terms-title">Pesan / Ketentuan Dokumen</div><div class="terms-body">${esc(doc.document_message)}</div></div>` : ""}${key === "po" ? paymentTermsHtml(doc, showPrice, isPoV2(doc) ? fmtIdr : rupiah).replace('class="term-heading"', 'class="terms-title"') : ""}`;
  const signaturesHtml = () => layout.show_signatures ? `<div class="sign">${layout.signature_labels.map((label,i)=>`<div><div>${esc(label)}</div>${key === "po" && i === 0 && poApproved(doc) && signatureImg ? `<img class="generic-signature" src="${signatureImg}"/>` : ""}<div class="line">${i===0 ? esc(doc.created_by || "") : "&nbsp;"}</div></div>`).join("")}</div>` : "";
  const footerHtml = () => `<div class="ft"><div class="footer-text">${esc(layout.footer_text || "")}</div>${layout.show_qr && qrImg ? `<div class="qr"><img src="${qrImg}" width="90" height="90"/><div>${esc(code)}</div></div>` : ""}</div>`;

  const sectionFns = { header: headerHtml, meta: metaHtml, items: itemsHtml, message: messageHtml, signatures: signaturesHtml, footer: footerHtml };
  const bodySections = layout.sections.map(s => sectionFns[s] ? sectionFns[s]() : "").join("\n");

  const primary = layout.primary_color || "#1e3a8a";
  const fontSize = Number(layout.font_size) || 11;
  const margins = layoutMargins(layout);
  const paper = layout.paper_size || "A4";
  const orientation = layout.orientation || "portrait";
  const font = layout.font_family || "Arial";
  const logoWidth = Number(layout.logo_width_mm) || 28;
  const draftMark = key === "po" && !poApproved(doc) ? `<div class="draft-watermark">DRAFT</div>` : "";

  const html = `<!doctype html><html><head><title>${esc(doc.no)}</title>
  <style>
    @page{size:${paper} ${orientation};margin:${cssMargin(margins)}}
    *{box-sizing:border-box}
    @media screen{body{padding:${cssMargin(margins)}!important}}
    body{margin:0;padding:0;color:#111;font-family:${font},sans-serif;font-size:${fontSize}px;-webkit-print-color-adjust:exact;print-color-adjust:exact;position:relative}
    .draft-watermark{position:fixed;left:50%;top:48%;transform:translate(-50%,-50%) rotate(-32deg);font-size:74px;font-weight:900;letter-spacing:8px;color:#6b7280;opacity:.14;z-index:9999;pointer-events:none}
    .hd{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;padding-bottom:10px;margin-bottom:13px;border-bottom:3px solid ${primary}}
    .hd.minimal{border-bottom:1px solid #cbd5e1}.hd.boxed{border:1px solid #cbd5e1;border-left:5px solid ${primary};padding:10px}
    .brand{display:flex;align-items:flex-start;gap:10px}.logo{width:${logoWidth}mm;max-height:22mm;object-fit:contain}.co{font-size:18px;font-weight:800;color:${primary}}.address{font-size:10px;color:#64748b;margin-top:3px;max-width:90mm;white-space:pre-line}.doc-title{text-align:right}.title{font-size:20px;font-weight:800}.doc-no{font-family:monospace;font-weight:700;margin-top:4px}
    .meta{display:grid;grid-template-columns:1fr 1fr;gap:4px 22px;margin:9px 0 12px}.meta div{font-size:${Math.max(9,fontSize-1)}px}.status{display:inline-block;padding:1px 8px;border:1px solid ${primary};border-radius:999px;color:${primary};font-weight:700}
    table{width:100%;border-collapse:collapse;margin-top:9px;page-break-inside:auto}thead{display:table-header-group}tr{page-break-inside:avoid}th,td{border:1px solid #cbd5e1;padding:6px 7px;font-size:${Math.max(8,fontSize-1)}px}th{background:#f1f5f9;text-align:left;text-transform:uppercase;font-size:${Math.max(8,fontSize-2)}px}.col-qty,.col-price,.col-discount,.col-total,.col-adj_before,.col-adj_qty,.col-adj_after,.col-adj_cost{text-align:right}.col-tax{white-space:nowrap}.col-alokasi{white-space:normal;word-break:normal;font-size:${Math.max(8,fontSize-2)}px}.money{text-align:right}.grand{font-weight:800}.grand-label{text-align:right;font-weight:800}
    .terms{margin-top:15px;border:1px solid #cbd5e1;border-radius:6px;padding:9px 11px;page-break-inside:avoid}.terms-title{font-weight:700;margin-bottom:6px;color:${primary}}.terms-body{white-space:pre-wrap;line-height:1.5;font-size:${Math.max(8,fontSize-1)}px}
    .sign{display:flex;justify-content:space-around;gap:20px;margin-top:40px;text-align:center;page-break-inside:avoid}.sign>div{min-width:120px;flex:1;max-width:180px}.generic-signature{display:block;max-width:36mm;max-height:18mm;object-fit:contain;margin:6px auto -4px}.line{border-top:1px solid #333;margin-top:50px;padding-top:4px}
    .ft{margin-top:20px;display:flex;justify-content:space-between;align-items:flex-end;gap:20px;page-break-inside:avoid}.footer-text{font-size:9px;color:#666;white-space:pre-line}.qr{text-align:center;font-family:monospace;font-size:8px}
  </style></head><body>${draftMark}${bodySections}<script>window.onload=function(){setTimeout(function(){window.print()},500)}</script></body></html>`;

  const w = window.open("", "_blank");
  w.document.write(html); w.document.close();
}