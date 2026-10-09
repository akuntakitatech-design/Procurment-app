// Cetak Stock Opname: (A) Lembar Penghitungan Fisik, (B) Berita Acara Hasil Stock Opname.
// Data dari GET /opname/{id}/print-data (harga sudah diredaksi server bila tanpa izin). Tidak memengaruhi print.js modul lain.
import api, { API } from "@/lib/api";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n = (v) => (v == null ? "" : Number(v).toLocaleString("id-ID", { maximumFractionDigits: 4 }));
const rp = (v) => (v == null ? "" : `Rp ${Number(v).toLocaleString("id-ID", { maximumFractionDigits: 2 })}`);
const d10 = (v) => (v ? new Date(String(v).length <= 10 ? `${v}T00:00:00` : v).toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" }) : "-");
const STATUS = { uncounted: "Belum Dihitung", match: "Sesuai", plus: "Selisih +", minus: "Selisih −" };

export function opnameHtml(kind, doc, company = {}) {
  const showPrice = doc?.permissions?.price && doc?.summary && "net_value" in doc.summary;
  const sheet = kind === "sheet";
  const title = sheet ? "LEMBAR PENGHITUNGAN FISIK" : "BERITA ACARA HASIL STOCK OPNAME";
  const meta = [["No. Opname", doc.no], ["Tanggal", d10(doc.date)], ["Gudang", `${doc.warehouse_code || ""} ${doc.warehouse_name || ""}`.trim()],
    ["Divisi", doc.division_name || "-"], ["Mode", doc.mode === "freeze" ? "Freeze" : "Live"], ["Petugas Hitung", doc.counter_name || "-"], ["Status", doc.status]];
  const head = sheet
    ? ["No", "Kode", "Nama Barang", "Satuan", "Stok Sistem", "Hasil Fisik", "Catatan"]
    : ["No", "Kode", "Nama Barang", "Satuan", "Sistem", "Fisik", "Selisih", ...(showPrice ? ["Harga Avg", "Nilai Selisih"] : []), "Alasan"];
  const rows = (doc.lines || []).map((l, i) => sheet
    ? `<tr><td class=c>${i + 1}</td><td>${esc(l.item_code)}</td><td>${esc(l.item_name)}</td><td class=c>${esc(l.unit)}</td><td class=r>${n(l.system_qty)}</td><td class=box></td><td class=box></td></tr>`
    : `<tr><td class=c>${i + 1}</td><td>${esc(l.item_code)}</td><td>${esc(l.item_name)}</td><td class=c>${esc(l.unit)}</td><td class=r>${n(l.system_qty)}</td><td class=r>${l.counted == null ? "-" : n(l.counted)}</td><td class=r>${l.variance == null ? "-" : (l.variance > 0 ? "+" : "") + n(l.variance)}</td>${showPrice ? `<td class=r>${rp(l.unit_price)}</td><td class=r>${rp(l.value)}</td>` : ""}<td>${esc(l.reason || (l.status ? STATUS[l.status] : ""))}</td></tr>`).join("");
  const s = doc.summary || {};
  const sum = sheet ? "" : `<table class=sum><tr><td>Total Barang</td><td class=r>${n(s.total)}</td><td>Sesuai</td><td class=r>${n(s.match)}</td></tr>
    <tr><td>Selisih Plus</td><td class=r>${n(s.plus)}</td><td>Selisih Minus</td><td class=r>${n(s.minus)}</td></tr>
    ${showPrice ? `<tr><td>Total Nilai Surplus</td><td class=r>${rp(s.surplus_value)}</td><td>Total Nilai Shortage</td><td class=r>${rp(s.shortage_value)}</td></tr><tr><td colspan=2><b>Nilai Selisih Bersih</b></td><td colspan=2 class=r><b>${rp(s.net_value)}</b></td></tr>` : ""}</table>`;
  const signs = sheet ? [["Petugas Penghitung", doc.counter_name], ["Pemeriksa", ""]] : [["Petugas Penghitung", doc.counter_name], ["Pemeriksa", doc.reviewed_by_name || ""], ["Disetujui", doc.approved_by || ""]];
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)} ${esc(doc.no)}</title><style>
  @page{size:A4;margin:14mm 12mm}body{font-family:Arial,Helvetica,sans-serif;font-size:10.5px;color:#111}
  .hd{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #1f2937;padding-bottom:8px;margin-bottom:10px}
  .co{font-size:14px;font-weight:700}.ti{font-size:15px;font-weight:700;text-align:right;letter-spacing:.5px}
  .meta{display:grid;grid-template-columns:repeat(4,1fr);gap:4px 14px;margin-bottom:10px}.meta div span{display:block;color:#555;font-size:9px;text-transform:uppercase}
  table.t{width:100%;border-collapse:collapse}table.t th,table.t td{border:1px solid #9ca3af;padding:4px 5px;vertical-align:top}
  table.t thead{display:table-header-group}table.t th{background:#e5e7eb;font-size:9.5px;text-transform:uppercase}tr{page-break-inside:avoid}
  .c{text-align:center}.r{text-align:right;white-space:nowrap}.box{min-width:70px;height:18px}
  table.sum{margin-top:10px;border-collapse:collapse;width:60%}table.sum td{border:1px solid #9ca3af;padding:4px 6px}
  .sg{display:flex;gap:24px;margin-top:28px;page-break-inside:avoid}.sg div{flex:1;text-align:center}.sg .ln{margin-top:56px;border-top:1px solid #111;padding-top:3px}
  .ft{margin-top:12px;color:#666;font-size:9px}</style></head><body>
  <div class=hd><div>${company.logo_src ? `<img src="${esc(company.logo_src)}" style="height:38px"/><br/>` : ""}<div class=co>${esc(company.name || company.company_name || "")}</div><div>${esc(company.address || "")}</div></div><div class=ti>${title}<div style="font-size:11px;font-weight:400">${esc(doc.no)}</div></div></div>
  <div class=meta>${meta.map(([k, v]) => `<div><span>${k}</span>${esc(v)}</div>`).join("")}</div>
  ${doc.notes ? `<p><b>Catatan:</b> ${esc(doc.notes)}</p>` : ""}
  <table class=t><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>${sum}
  <div class=sg>${signs.map(([k, v]) => `<div>${k}<div class=ln>${esc(v || "(..............................)")}</div></div>`).join("")}</div>
  <div class=ft>Dicetak ${esc(doc.printed_by || "")} · ${esc(new Date(doc.printed_at || Date.now()).toLocaleString("id-ID"))}${showPrice ? "" : " · Informasi harga tidak ditampilkan (tanpa izin harga)"}</div>
  <script>window.onload=function(){setTimeout(function(){window.print()},450)}</script></body></html>`;
}

export async function printOpname(kind, id) {
  const w = window.open("", "_blank");
  let data, company;
  try {
    [{ data }, company] = await Promise.all([api.get(`/opname/${id}/print-data`), api.get("/settings/company").then((r) => r.data).catch(() => ({}))]);
  } catch (e) { if (w) w.close(); throw e; }
  const logo_src = company?.logo_path ? `${API}/company/logo?v=${encodeURIComponent(company.logo_version || "1")}` : "";
  const html = opnameHtml(kind, data, { ...(company || {}), logo_src });
  if (w) { w.document.write(html); w.document.close(); }
  return html;
}
