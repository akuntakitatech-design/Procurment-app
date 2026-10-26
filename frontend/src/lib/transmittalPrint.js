// Cetak Transmittal Invoice — A4 mengikuti pola dokumen manual PT REAL.
// Murni presentasi: tidak memanggil API yang mengubah status (cetak != kirim).
import { checklistSummary } from "@/lib/docChecklist";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const idr = (v) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(Number(v || 0));
const MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
const longDate = (v) => {
  const s = String(v || "").slice(0, 10).split("-");
  const [y, m, d] = s.map(Number);
  if (s.length !== 3 || !y || !m || !d) return String(v || "-");
  return `${d} ${MONTHS[m - 1]} ${y}`;
};
const shortDate = (v) => {
  const s = String(v || "").slice(0, 10);
  return s.length === 10 ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : "-";
};

export function buildTransmittalHtml({ doc, company, autoPrint = true }) {
  const items = doc.items || [];
  const total = items.reduce((s, i) => s + Number(i.amount || 0), 0);
  const rows = items.map((i, n) => {
    const c = checklistSummary(i.checklist);
    const label = c.complete ? "Lengkap" : `Belum Lengkap (${c.pending.length})`;
    return `<tr>
      <td class="c">${n + 1}</td>
      <td>${esc(i.supplier_name || "-")}</td>
      <td class="mono">${esc(i.invoice_no || "-")}</td>
      <td class="mono">${esc(i.tax_invoice_no || "-")}<div class="sub">${i.tax_invoice_date ? esc(shortDate(i.tax_invoice_date)) : ""}</div></td>
      <td class="mono">${esc(i.po_nos || "-")}</td>
      <td class="r">${idr(i.amount)}</td>
      <td class="c ${c.complete ? "ok" : "warn"}">${esc(label)}</td>
    </tr>`;
  }).join("");

  const companyName = company?.name || "";
  const companyAddress = String(company?.address || "").trim();
  const receiver = doc.receiver_name || "";
  const sentAt = doc.sent_at ? shortDate(doc.sent_at) : shortDate(doc.date);
  const receivedAt = doc.received_at ? shortDate(doc.received_at) : "";

  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(doc.no || "TRANSMITTAL")}</title>
  <style>
    @page{size:A4 portrait;margin:12mm}
    *{box-sizing:border-box}
    html,body{margin:0;padding:0;background:#fff}
    body{color:#000;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:1.3;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    @media screen{body{padding:12mm}.print-hint{font:12px/1.4 Arial,sans-serif;background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;border-radius:6px;padding:6px 10px;margin:0 0 4mm}}
    @media print{.print-hint{display:none!important}}
    .head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:.4mm solid #000;padding-bottom:2mm;margin-bottom:3mm}
    .company{font-weight:700;font-size:13px}
    .company div{font-weight:400;font-size:9px;color:#374151;white-space:pre-line}
    .title{text-align:right}
    .title h1{margin:0;font-size:16px;letter-spacing:.4px}
    .title .no{font-family:monospace;font-weight:700;font-size:12px;margin-top:1mm}
    .info{display:grid;grid-template-columns:1fr 1fr;gap:1mm 6mm;margin-bottom:3mm}
    .info .row{display:grid;grid-template-columns:32mm 1fr}
    .info .lab{color:#374151}
    .info .val{font-weight:700}
    table{width:100%;border-collapse:collapse;margin-top:1mm}
    th,td{border:.25mm solid #000;padding:1.1mm 1.4mm;vertical-align:top}
    th{background:#f3f4f6;font-size:10px;text-align:center}
    td.c{text-align:center}
    td.r{text-align:right;white-space:nowrap}
    td.mono{font-family:monospace;font-size:10px}
    td .sub{font-size:8px;color:#4b5563}
    td.ok{font-weight:700}
    td.warn{font-weight:700}
    tfoot td{font-weight:700}
    .notes{margin-top:3mm;min-height:10mm}
    .notes .lab{font-weight:700;margin-bottom:.6mm}
    .signs{display:grid;grid-template-columns:1fr 1fr;gap:20mm;margin-top:12mm;text-align:center}
    .signs .box{display:flex;flex-direction:column;justify-content:flex-end}
    .signs .cap{font-weight:700;margin-bottom:1mm}
    .signs .space{height:20mm}
    .signs .name{font-weight:700;text-decoration:underline}
    .signs .meta{font-size:9px;color:#374151}
    .footer{margin-top:6mm;border-top:.35mm solid #000;padding-top:1.5mm;font-size:9px;text-align:center;color:#374151;white-space:pre-line}
  </style></head><body>
    ${autoPrint ? `<div class="print-hint">Dialog cetak terbuka otomatis. Pilih "Save as PDF" bila ingin menyimpan salinan.</div>` : ""}
    <div class="head">
      <div class="company">${esc(companyName)}${companyAddress ? `<div>${esc(companyAddress)}</div>` : ""}</div>
      <div class="title"><h1>TRANSMITTAL INVOICE</h1><div class="no">${esc(doc.no || "")}</div><div>Tanggal: ${esc(longDate(doc.date))}</div></div>
    </div>
    <div class="info">
      <div class="row"><span class="lab">Tujuan / Departemen</span><span class="val">${esc(doc.destination || "-")}</span></div>
      <div class="row"><span class="lab">Status</span><span class="val">${esc(doc.status || "-")}</span></div>
      <div class="row"><span class="lab">Pengirim</span><span class="val">${esc(doc.sender_name || "-")}</span></div>
      <div class="row"><span class="lab">Penerima</span><span class="val">${esc(receiver || "-")}</span></div>
      <div class="row"><span class="lab">Jumlah Invoice</span><span class="val">${items.length}</span></div>
      <div class="row"><span class="lab">Total Nilai (incl. PPN)</span><span class="val">Rp ${idr(total)}</span></div>
    </div>
    <table>
      <thead><tr><th style="width:8mm">No</th><th>Vendor</th><th style="width:26mm">No. Invoice</th><th style="width:28mm">Faktur Pajak</th><th style="width:28mm">No. PO</th><th style="width:26mm">Nilai Invoice</th><th style="width:28mm">Kelengkapan</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7" class="c">Tidak ada invoice</td></tr>`}</tbody>
      <tfoot><tr><td colspan="5" class="r">TOTAL</td><td class="r">${idr(total)}</td><td></td></tr></tfoot>
    </table>
    <div class="notes"><div class="lab">Keterangan</div><div>${esc(doc.notes || "-")}</div></div>
    <div class="signs">
      <div class="box"><div class="cap">Dikirim oleh,</div><div class="space"></div><div class="name">${esc(doc.sender_name || "")}</div><div class="meta">Tanggal: ${esc(sentAt)}</div></div>
      <div class="box"><div class="cap">Diterima oleh,</div><div class="space"></div><div class="name">${esc(receiver || "")}</div><div class="meta">Tanggal: ${esc(receivedAt || "____________")}</div></div>
    </div>
    ${String(company?.footer_text || "").trim() ? `<div class="footer">${esc(company.footer_text)}</div>` : ""}
    ${autoPrint ? `<script>window.onload=function(){setTimeout(function(){window.print()},450)}</script>` : ""}
  </body></html>`;
}

export function openTransmittalPrint(data, autoPrint = true) {
  const html = buildTransmittalHtml({ doc: data, company: data.company || {}, autoPrint });
  const w = window.open("", "_blank");
  if (!w) return false;
  w.document.write(html);
  w.document.close();
  return true;
}
