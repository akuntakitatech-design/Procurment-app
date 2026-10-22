// Cetak DO — template "Bukti Penerimaan Barang" (mengikuti form manual PT REAL).
// MURNI PRESENTASI: seluruh nilai berasal dari data DO/master yang sudah tersimpan (tidak ada request tulis).
import { fmtDate } from "@/lib/format";
import { layoutMargins, PRINT_DIALOG_HINT } from "@/lib/printMargins";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nl2br = (v) => esc(v || "").replace(/\r?\n/g, "<br/>");

const PAGE_MM = { A4: [210, 297], A5: [148, 210], Letter: [215.9, 279.4] };

const qtyText = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 3 }).format(n);
};

const receivedAt = (doc) => {
  const date = doc?.date ? fmtDate(doc.date) : "";
  const stamp = doc?.created_at ? new Date(doc.created_at) : null;
  if (!stamp || Number.isNaN(stamp.getTime())) return date;
  const time = stamp.toLocaleTimeString("id-ID", { hour12: false, timeZone: "Asia/Jakarta" });
  return date ? `${date} ${time}` : time;
};

const uniq = (xs) => [...new Set((xs || []).map((x) => String(x || "").trim()).filter(Boolean))];

// Kolom "To": nomor SPK + nama project dari alokasi SPK tahap DO.
const spkProjectCell = (summary) => {
  const allocs = (summary?.allocations || []).filter((a) => Number(a.allocated_qty) > 0);
  const non = Number(summary?.non_spk_qty || 0);
  const label = (a) => [a.spk_number || a.spk_id || "", a.project_name || ""].filter(Boolean).join(" — ");
  if (!allocs.length) return "";
  if (allocs.length === 1 && non <= 1e-9) return label(allocs[0]);
  const parts = allocs.map((a) => `${label(a)} (${qtyText(a.allocated_qty)})`);
  if (non > 1e-9) parts.push(`Non-SPK (${qtyText(non)})`);
  return parts.join(", ");
};

export function buildDoPrintHtml({ doc, company, layout, logoImg, allocLines, autoPrint = true }) {
  company = company || {};
  layout = layout || {};
  const font = layout.font_family || "Arial";
  const fs = Math.max(8, Number(layout.font_size) || 11);
  const m = layoutMargins(layout);
  const paper = PAGE_MM[layout.paper_size] ? layout.paper_size : "A4";
  const orientation = layout.orientation === "landscape" ? "landscape" : "portrait";
  const logoWidth = Number(layout.logo_width_mm) || 24;

  const lines = doc?.lines || [];
  // Kolom "To" = SPK + nama project untuk baris ini (alokasi SPK tahap DO -> snapshot baris -> SPK header -> "-").
  const allocMap = {};
  (allocLines || []).forEach((l) => {
    const text = spkProjectCell(l);
    if (text) allocMap[l.item_line_id] = text;
  });
  const labels = layout.signature_labels || [];
  const signer1 = labels[0] || "Project Manager / Spv Part Management";
  const signer2 = labels[1] || "To Send Invoice, sign here & return";
  const signatureNote = layout.do_signature_note || "";
  const noteText = layout.do_note_text || "";

  const warehouseAddress = doc?.warehouse_address || company.address || "";
  const vendorName = doc?.supplier_legal_name || doc?.supplier_name || "";
  const vendorAddress = doc?.supplier_address || "";
  const vendorCity = doc?.supplier_city || "";
  const vendorPhone = doc?.supplier_phone || "";
  const supplierDn = doc?.supplier_dn || "";
  const supplierInvoice = doc?.supplier_invoice || "";
  const orderNo = doc?.order_no || uniq(lines.map((l) => l.po_no)).join(", ");
  const receivedBy = doc?.receiver || doc?.created_by || "";
  const state = doc?.receipt_state || doc?.status || "";

  const rows = lines.map((l) => {
    const qty = l.display_qty ?? l.qty;
    const unit = l.display_unit || l.unit || "";
    const to = allocMap[l.id] || l.spk || doc?.spk || "-";
    return `<tr>
      <td>${esc(l.item_name || l.item_code || "-")}</td>
      <td class="qty">${esc(qtyText(qty))}${unit ? ` ${esc(unit)}` : ""}</td>
      <td>${esc(to)}</td>
    </tr>`;
  }).join("");

  const addressLeft = `<div><div class="addr-title">Warehouse Address:</div><div class="addr-body">${nl2br(warehouseAddress) || "-"}</div></div>`;
  const vendorLines = [vendorName, vendorAddress, vendorCity, vendorPhone].filter(Boolean).map((x) => esc(x));
  // Nomor dokumen & faktur dari supplier, dicetak di bawah Vendor Address.
  const vendorMeta = [
    supplierDn ? `<div>No. DO: <b>${esc(supplierDn)}</b></div>` : "",
    supplierInvoice ? `<div>No. Faktur: <b>${esc(supplierInvoice)}</b></div>` : "",
  ].filter(Boolean).join("");
  const addressRight = `<div><div class="addr-title">Vendor Address:</div><div class="addr-body">${vendorLines.join("<br/>") || "-"}</div>${vendorMeta ? `<div class="addr-meta">${vendorMeta}</div>` : ""}</div>`;

  const signatures = layout.show_signatures === false ? "" : `<div class="signs">
    <div class="sign-col">
      <div class="sign-head">&nbsp;</div>
      <div class="sign-box"><div class="sign-cap">${esc(signer1)}</div></div>
    </div>
    <div class="sign-col">
      <div class="sign-head right">${esc(signer2)} :</div>
      <div class="sign-box"><div class="sign-cap">${esc(signatureNote)}</div></div>
    </div>
  </div>`;

  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(doc?.no || "DO")}</title>
  <style>
    @page{size:${paper} ${orientation};margin:0}
    *{box-sizing:border-box}
    body{margin:0;background:#eef1f5;font-family:${font},Arial,sans-serif;font-size:${fs}px;color:#111}
    /* Margin dokumen dipindah ke padding sheet + @page margin 0 agar browser tidak mencetak
       header/footer bawaan (tanggal, judul dokumen, URL, nomor halaman). */
    .sheet{background:#fff;max-width:${paper === "A5" ? 148 : 210}mm;margin:0 auto;padding:${m.top}mm ${m.right}mm ${m.bottom}mm ${m.left}mm}
    .print-hint{background:#fef3c7;color:#78350f;padding:6px 10px;font-size:12px;text-align:center}
    .top{display:flex;justify-content:space-between;align-items:flex-start;gap:10mm}
    .brand{display:flex;flex-direction:column;gap:2mm}
    .brand img{width:${logoWidth}mm;height:auto;object-fit:contain}
    .brand-name{font-weight:700;font-size:${fs + 1}px;letter-spacing:.2px}
    .doc-title{font-size:${Math.max(16, fs + 8)}px;font-weight:800;text-align:right;line-height:1.15}
    .addr{display:grid;grid-template-columns:1fr 1fr;gap:14mm;margin-top:13mm}
    .addr-title{font-weight:700;margin-bottom:1.6mm}
    .addr-body{line-height:1.45;color:#1f2937}
    .addr-meta{margin-top:3mm;line-height:1.5}
    .doc-no{font-size:${Math.max(22, fs + 15)}px;font-weight:700;margin:9mm 0 2.5mm;letter-spacing:.3px}
    table{width:100%;border-collapse:collapse}
    .summary th{text-align:left;font-weight:700;padding:1.6mm 0;border-bottom:1.4px solid #111}
    .summary td{text-align:left;padding:2.2mm 0;font-weight:700}
    .items{margin-top:8mm}
    .items th{text-align:left;font-weight:700;padding:2.2mm 0;border-bottom:1.4px solid #111}
    .items td{padding:2.6mm 0;vertical-align:top;border-bottom:.5px solid #e5e7eb}
    .items tr:last-child td{border-bottom:none}
    .qty{white-space:nowrap}
    .note{font-weight:700;margin-top:12mm}
    .signs{display:grid;grid-template-columns:1fr 1fr;gap:22mm;margin-top:14mm;break-inside:avoid;page-break-inside:avoid}
    .sign-head{font-size:${Math.max(8, fs - 1)}px;color:#374151;margin-bottom:1.6mm}
    .sign-head.right{text-align:right}
    .sign-box{border:1px solid #111;height:30mm;position:relative}
    .sign-cap{position:absolute;left:0;right:0;bottom:1.6mm;text-align:center;color:#9ca3af;font-size:${Math.max(8, fs - 2)}px}
    .footer{margin-top:24mm;text-align:center;font-weight:700;font-size:${Math.max(8, fs)}px;line-height:1.4;break-inside:avoid}
    @media print{body{background:#fff}.sheet{max-width:none}.print-hint{display:none}}
  </style></head><body>
    ${autoPrint ? `<div class="print-hint">${esc(PRINT_DIALOG_HINT)} Margin dokumen ini: atas ${m.top} mm, kanan ${m.right} mm, bawah ${m.bottom} mm, kiri ${m.left} mm.</div>` : ""}
    <div class="sheet">
      <div class="top">
        <div class="brand">
          ${layout.show_logo !== false && logoImg ? `<img src="${logoImg}" alt=""/>` : ""}
          <div class="brand-name">${esc(company.name || "PT. Perusahaan Anda")}</div>
        </div>
        <div class="doc-title">${esc(layout.title || "Bukti Penerimaan Barang")}</div>
      </div>

      <div class="addr">${addressLeft}${addressRight}</div>

      <div class="doc-no">${esc(doc?.no || "-")}</div>
      <table class="summary"><thead><tr>
        <th>Received By</th><th>Order</th><th>State</th><th>Received Date</th>
      </tr></thead><tbody><tr>
        <td>${esc(receivedBy || "-")}</td>
        <td>${esc(orderNo || "-")}</td>
        <td>${esc(state || "-")}</td>
        <td>${esc(receivedAt(doc) || "-")}</td>
      </tr></tbody></table>

      <table class="items"><thead><tr>
        <th>Product</th><th>Quantity</th><th>To</th>
      </tr></thead><tbody>${rows || `<tr><td colspan="3">-</td></tr>`}</tbody></table>

      ${noteText ? `<div class="note">${esc(noteText)}</div>` : ""}
      ${signatures}
      ${String(layout.footer_text || "").trim() ? `<div class="footer">${nl2br(String(layout.footer_text).trim())}</div>` : ""}
    </div>
    ${autoPrint ? `<script>window.onload=function(){setTimeout(function(){var t=document.title;document.title='';window.print();document.title=t;},550)}</script>` : ""}
  </body></html>`;
}