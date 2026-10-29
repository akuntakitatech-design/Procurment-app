// Cetak Transmittal Invoice — A4 landscape mengikuti form manual PT REAL (form "Pengiriman Transmittal Invoice").
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

// Form manual PT REAL mencetak minimal 7 baris bernomor (bisa ditulis tangan untuk invoice tambahan).
export const MIN_ROWS = 7;

// Kolom ✓ pada form: Invoice/PO/Faktur Pajak serta No DO (sistem & supplier) sudah jadi kolom sendiri.
export const PRINT_CHECKLIST = [
  { key: "kwitansi", label: "Kwitansi" },
  { key: "bast", label: "BAST / Timesheet" },
  { key: "kontrak", label: "Kontrak Kerja (Subcon)" },
];

/** ✓ Lengkap · ✗ Belum Lengkap · − Tidak Berlaku */
export const checklistMark = (status) => (status === "Lengkap" ? "✓" : status === "Tidak Berlaku" ? "−" : "✗");

const COLS = 11;

/** Isi satu dokumen transmittal (kop, info, tabel, tanda tangan). */
const docBody = ({ doc, company, logoImg }) => {
  const items = doc.items || [];
  const marks = (i) => {
    const c = normalizeChecklist(i.checklist);
    return `<td class="mono">${esc(i.do_nos || "-")}</td>
      <td class="mono">${esc(i.do_supplier_nos || "-")}</td>
      <td class="r">${money(i.amount)}</td>
      <td class="mark">${checklistMark(c.kwitansi)}</td>
      <td class="mark">${checklistMark(c.bast)}</td>
      <td class="mark">${checklistMark(c.kontrak)}</td>`;
  };
  const dataRows = items.map((i, n) => `<tr class="row">
      <td class="c">${n + 1}</td>
      <td class="vendor">${esc(i.supplier_name || "-")}</td>
      <td class="mono">${esc(i.invoice_no || "-")}</td>
      <td class="mono">${esc(i.tax_invoice_no || "-")}</td>
      <td class="mono">${esc(i.po_nos || "-")}</td>
      ${marks(i)}
    </tr>`);
  const emptyRows = Array.from({ length: Math.max(0, MIN_ROWS - items.length) },
    (_, k) => `<tr class="row"><td class="c">${items.length + k + 1}</td>${'<td></td>'.repeat(COLS - 1)}</tr>`);
  const rows = [...dataRows, ...emptyRows].join("");

  const companyName = company?.name || "";
  const companyAddress = String(company?.address || "").trim();
  const notes = String(doc.notes || "").trim();

  return `<div class="head">
      <div class="company">
        ${logoImg ? `<img class="logo" src="${logoImg}" alt=""/>` : ""}
        <div class="company-name">${esc(companyName)}</div>
        ${companyAddress ? `<div class="company-addr">${esc(companyAddress)}</div>` : ""}
      </div>
      <div class="title">
        <div class="t1">Pengiriman Transmittal Invoice</div>
        <div>Vendor Proyek PHR</div>
        <div>Tanggal : ${esc(longDate(doc.date))}</div>
        <div class="tno">No : ${esc(doc.no || "-")}</div>
      </div>
    </div>
    <div class="info">
      <div class="row"><span class="lab">Tujuan / Departemen</span><span class="val">${esc(doc.destination || "-")}</span></div>
      <div class="row"><span class="lab">Pengirim</span><span class="val"></span></div>
      <div class="row"><span class="lab">Penerima</span><span class="val"></span></div>
      <div class="row"><span class="lab">Total Invoice</span><span class="val">${items.length}</span></div>
    </div>
    <table>
      <thead>
        <tr>
          <th rowspan="2" style="width:10mm">No</th>
          <th rowspan="2" style="width:38mm">Nama Vendor</th>
          <th colspan="9">Item Pemeriksaan Kelengkapan</th>
        </tr>
        <tr>
          <th style="width:27mm">No. Invoice</th>
          <th style="width:29mm">No. Faktur Pajak</th>
          <th style="width:28mm">No. PO</th>
          <th style="width:28mm">No DO Sistem</th>
          <th style="width:32mm">No. DO Supplier</th>
          <th style="width:24mm">Nilai (Inc PPN)</th>
          <th style="width:13mm">Kwitansi</th>
          <th style="width:13mm">BAST / Timesheet</th>
          <th style="width:16mm">Kontrak Kerja (Subcon)</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    ${notes ? `<div class="notes"><div class="lab">Keterangan</div><div>${esc(notes)}</div></div>` : ""}
    <div class="signs">
      <div class="box">
        <div class="cap">Dikirim Oleh,</div>
        <div class="space"></div>
        <div class="line">Nama :</div>
        <div class="line">Tanggal :</div>
      </div>
      <div class="box">
        <div class="cap">Diterima Oleh,</div>
        <div class="space"></div>
        <div class="line">Nama :</div>
        <div class="line">Tanggal :</div>
      </div>
    </div>`;
};

const pageHtml = ({ title, body, autoPrint }) => `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
  <style>
    /* margin halaman 0 + padding di .doc: header/footer otomatis browser (tanggal, jam, judul, URL
       "about:blank") tidak ikut tercetak, sementara isi dokumen tetap punya margin 10mm. */
    @page{size:A4 landscape;margin:0}
    *{box-sizing:border-box}
    html,body{margin:0;padding:0;background:#fff}
    body{color:#000;font-family:Arial,Helvetica,sans-serif;font-size:10.5px;line-height:1.3;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    .doc{padding:10mm;background:#fff}
    @media screen{body{background:#e5e7eb}.print-hint{font:12px/1.4 Arial,sans-serif;background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;border-radius:6px;padding:6px 10px;margin:10mm 10mm 0}}
    @media print{.print-hint{display:none!important}}
    .head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5mm}
    .company{display:flex;flex-direction:column;align-items:flex-start;max-width:150mm}
    .logo{display:block;max-height:16mm;max-width:46mm;object-fit:contain;margin-bottom:1.5mm}
    .company-name{font-weight:700;font-size:13.5px;text-transform:uppercase}
    .company-addr{font-size:10.5px;white-space:pre-line}
    .title{text-align:right;font-size:10.5px;line-height:1.45}
    .title .t1{font-weight:700;font-size:12px}
    .title .tno{font-weight:700}
    .info{display:grid;grid-template-columns:1fr 1fr;gap:1mm 10mm;margin-bottom:3mm;font-size:12px}
    .info .row{display:flex;gap:2mm}
    .info .lab{white-space:nowrap}
    .info .lab:after{content:" :"}
    .info .val{font-weight:700}
    table{width:100%;border-collapse:collapse;table-layout:fixed}
    th,td{border:.25mm solid #000;padding:1mm 1.2mm;vertical-align:middle}
    th{font-size:9px;text-align:center;font-weight:700;line-height:1.2}
    tbody td{height:6.2mm}
    td.c{text-align:center}
    td.r{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
    td.mono{font-family:monospace;font-size:9.5px}
    td.vendor{font-weight:700}
    td.mark{text-align:center;font-weight:700;font-size:12px}
    .notes{margin-top:3mm}
    .notes .lab{font-weight:700}
    .signs{display:grid;grid-template-columns:1fr 1fr;gap:20mm;margin-top:12mm;text-align:center}
    .signs .box{text-align:center}
    .signs .space{height:20mm}
    .signs .line{margin-top:.6mm}
    .doc + .doc{break-before:page;page-break-before:always}
  </style></head><body>
    ${autoPrint ? `<div class="print-hint">Dialog cetak terbuka otomatis. Pilih "Save as PDF" bila ingin menyimpan salinan.</div>` : ""}
    ${body}
    ${autoPrint ? `<script>window.onload=function(){setTimeout(function(){window.print()},450)}</script>` : ""}
  </body></html>`;

export function buildTransmittalHtml({ doc, company, logoImg = "", autoPrint = true }) {
  return pageHtml({
    title: doc.no || "TRANSMITTAL",
    body: `<section class="doc">${docBody({ doc, company, logoImg })}</section>`,
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
