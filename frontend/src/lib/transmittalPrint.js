// Cetak Transmittal Invoice — A4 mengikuti form manual PT REAL.
// Murni presentasi: tidak memanggil API yang mengubah status (cetak != kirim).
import { normalizeChecklist } from "@/lib/docChecklist";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => new Intl.NumberFormat("en-US", { maximumFractionDigits: Number(v || 0) % 1 ? 2 : 0 }).format(Number(v || 0));
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

// Checklist pada cetak transmittal hanya 5 jenis (Invoice/PO/Faktur Pajak sudah jadi kolom sendiri).
export const PRINT_CHECKLIST = [
  { key: "do", label: "DO" },
  { key: "bukti_penerimaan", label: "Bukti Penerimaan Barang (PT. REAL)" },
  { key: "kwitansi", label: "Kwitansi" },
  { key: "bast", label: "BAST / Timesheet" },
  { key: "kontrak", label: "Kontrak Kerja (Subcon)" },
];

/** ✓ Lengkap · ✗ Belum Lengkap · − Tidak Berlaku */
export const checklistMark = (status) => (status === "Lengkap" ? "✓" : status === "Tidak Berlaku" ? "−" : "✗");

/** Isi satu dokumen transmittal (kop, info, tabel, keterangan, tanda tangan, footer). */
const docBody = ({ doc, company, logoImg }) => {
  const items = doc.items || [];
  const total = items.reduce((s, i) => s + Number(i.amount || 0), 0);
  const rows = items.map((i, n) => {
    const c = normalizeChecklist(i.checklist);
    const marks = PRINT_CHECKLIST.map((t) => `<td class="mark">${checklistMark(c[t.key])}</td>`).join("");
    return `<tr>
      <td class="c">${n + 1}</td>
      <td class="vendor">${esc(i.supplier_name || "-")}</td>
      <td class="mono">${esc(i.invoice_no || "-")}</td>
      <td class="mono">${esc(i.tax_invoice_no || "-")}</td>
      <td class="mono">${esc(i.po_nos || "-")}</td>
      <td class="r">${money(i.amount)}</td>
      ${marks}
    </tr>`;
  }).join("");

  const companyName = company?.name || "";
  const companyAddress = String(company?.address || "").trim();
  const receiver = doc.receiver_name || "";
  const sentAt = doc.sent_at ? shortDate(doc.sent_at) : shortDate(doc.date);
  const receivedAt = doc.received_at ? shortDate(doc.received_at) : "";

  return `<div class="head">
      <div class="company">
        ${logoImg ? `<img class="logo" src="${logoImg}" alt=""/>` : ""}
        <div class="company-name">${esc(companyName)}</div>
        ${companyAddress ? `<div class="company-addr">${esc(companyAddress)}</div>` : ""}
      </div>
      <div class="title"><h1>TRANSMITTAL INVOICE</h1><div class="no">${esc(doc.no || "")}</div><div>Tanggal: ${esc(longDate(doc.date))}</div></div>
    </div>
    <div class="info">
      <div class="row"><span class="lab">Tujuan / Departemen</span><span class="val">${esc(doc.destination || "-")}</span></div>
      <div class="row"><span class="lab">Status</span><span class="val">${esc(doc.status || "-")}</span></div>
      <div class="row"><span class="lab">Pengirim</span><span class="val">${esc(doc.sender_name || "-")}</span></div>
      <div class="row"><span class="lab">Penerima</span><span class="val">${esc(receiver || "-")}</span></div>
      <div class="row"><span class="lab">Jumlah Invoice</span><span class="val">${items.length}</span></div>
      <div class="row"><span class="lab">Total Nilai (Inc PPN)</span><span class="val">${money(total)}</span></div>
    </div>
    <table>
      <thead>
        <tr>
          <th rowspan="2" style="width:9mm">No</th>
          <th rowspan="2" style="width:42mm">Nama Vendor</th>
          <th rowspan="2" style="width:30mm">No. Invoice</th>
          <th rowspan="2" style="width:34mm">No. Faktur Pajak</th>
          <th rowspan="2" style="width:38mm">No. PO</th>
          <th rowspan="2" style="width:28mm">Nilai (Inc PPN)</th>
          <th colspan="5">Checklist Kelengkapan</th>
        </tr>
        <tr>${PRINT_CHECKLIST.map((t) => `<th>${esc(t.label)}</th>`).join("")}</tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="11" class="c">Tidak ada invoice</td></tr>`}</tbody>
      <tfoot><tr><td colspan="5" class="r">TOTAL</td><td class="r">${money(total)}</td><td colspan="5"></td></tr></tfoot>
    </table>
    <div class="notes"><div class="lab">Keterangan</div><div>${esc(doc.notes || "-")}</div></div>
    <div class="signs">
      <div class="box"><div class="cap">Dikirim oleh,</div><div class="space"></div><div class="name">${esc(doc.sender_name || "")}</div><div class="meta">Tanggal: ${esc(sentAt)}</div></div>
      <div class="box"><div class="cap">Diterima oleh,</div><div class="space"></div><div class="name">${esc(receiver || "")}</div><div class="meta">Tanggal: ${esc(receivedAt || "____________")}</div></div>
    </div>
    ${String(company?.footer_text || "").trim() ? `<div class="footer">${esc(company.footer_text)}</div>` : ""}`;
};

const pageHtml = ({ title, body, autoPrint }) => `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
  <style>
    @page{size:A4 landscape;margin:10mm}
    *{box-sizing:border-box}
    html,body{margin:0;padding:0;background:#fff}
    body{color:#000;font-family:Arial,Helvetica,sans-serif;font-size:10.5px;line-height:1.28;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    @media screen{body{padding:10mm}.print-hint{font:12px/1.4 Arial,sans-serif;background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;border-radius:6px;padding:6px 10px;margin:0 0 4mm}}
    @media print{.print-hint{display:none!important}}
    .head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:.4mm solid #000;padding-bottom:2mm;margin-bottom:3mm}
    .company{display:flex;flex-direction:column;align-items:flex-start}
    .logo{display:block;max-height:16mm;max-width:46mm;object-fit:contain;margin-bottom:1mm}
    .company-name{font-weight:700;font-size:14px}
    .company-addr{font-size:9px;color:#374151;white-space:pre-line}
    .title{text-align:right}
    .title h1{margin:0;font-size:17px;letter-spacing:.4px}
    .title .no{font-family:monospace;font-weight:700;font-size:12px;margin-top:1mm}
    .info{display:grid;grid-template-columns:1fr 1fr;gap:1mm 8mm;margin-bottom:3mm}
    .info .row{display:grid;grid-template-columns:34mm 1fr}
    .info .lab{color:#374151}
    .info .val{font-weight:700}
    table{width:100%;border-collapse:collapse;margin-top:1mm;table-layout:fixed}
    th,td{border:.25mm solid #000;padding:1mm 1.3mm;vertical-align:middle}
    th{background:#f3f4f6;font-size:9.5px;text-align:center;font-weight:700}
    td.c{text-align:center}
    td.r{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
    td.mono{font-family:monospace;font-size:9.5px}
    td.vendor{font-weight:700}
    td.mark{text-align:center;font-weight:700;font-size:12px}
    tfoot td{font-weight:700}
    .notes{margin-top:3mm;min-height:9mm}
    .notes .lab{font-weight:700;margin-bottom:.6mm}
    .signs{display:grid;grid-template-columns:1fr 1fr;gap:40mm;margin-top:10mm;text-align:center}
    .signs .box{display:flex;flex-direction:column;justify-content:flex-end}
    .signs .cap{font-weight:700;margin-bottom:1mm}
    .signs .space{height:18mm}
    .signs .name{font-weight:700;text-decoration:underline}
    .signs .meta{font-size:9px;color:#374151}
    .footer{margin-top:5mm;border-top:.35mm solid #000;padding-top:1.2mm;font-size:8.5px;text-align:center;color:#374151;white-space:pre-line}
    .doc + .doc{break-before:page;page-break-before:always}
  </style></head><body>
    ${autoPrint ? `<div class="print-hint">Dialog cetak terbuka otomatis. Pilih "Save as PDF" bila ingin menyimpan salinan.</div>` : ""}
    ${body}
    ${autoPrint ? `<script>window.onload=function(){setTimeout(function(){window.print()},450)}</script>` : ""}
  </body></html>`;

export function buildTransmittalHtml({ doc, company, logoImg = "", autoPrint = true }) {
  return pageHtml({
    title: doc.no || "TRANSMITTAL",
    body: docBody({ doc, company, logoImg }),
    autoPrint,
  });
}

/** Beberapa transmittal dalam satu dokumen cetak — satu transmittal per halaman (untuk export PDF massal). */
export function buildTransmittalMultiHtml({ docs = [], company, logoImg = "", autoPrint = true }) {
  const body = (docs || []).map((d) => `<section class="doc">${docBody({ doc: d, company: d.company || company || {}, logoImg: d.logoImg || logoImg })}</section>`).join("");
  return pageHtml({
    title: docs.length === 1 ? (docs[0].no || "TRANSMITTAL") : `Transmittal Invoice (${docs.length})`,
    body,
    autoPrint,
  });
}

const openPrint = (html) => {
  const w = window.open("", "_blank");
  if (!w) return false;
  w.document.write(html);
  w.document.close();
  return true;
};

export function openTransmittalPrint(data, autoPrint = true) {
  const html = buildTransmittalHtml({ doc: data, company: data.company || {}, logoImg: data.logoImg || "", autoPrint });
  return openPrint(html);
}

/** Cetak/export PDF 1..n transmittal (hasil export massal = satu halaman per transmittal). */
export function openTransmittalPrintMany(docs, autoPrint = true) {
  const html = buildTransmittalMultiHtml({ docs, autoPrint });
  return openPrint(html);
}
