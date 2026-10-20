// Cetak PO — template "REAL" (acuan: FORM PO PAKAI DP manual PT REAL). MURNI PRESENTASI:
// - nilai uang/pajak/DP dibaca dari nilai TERSIMPAN backend (Tax Engine v2 via poV2SummaryRows; PO lama v1 apa adanya);
// - watermark DRAFT + TTD/stempel mengikuti status PO (lolos Approval 1 + Approval 2 => Approved) — logika tidak diubah;
// - tidak ada request/tulis data. A4 formal hitam-putih, header tabel berulang per halaman, ringkasan tidak terulang.
import { num, fmtDate } from "@/lib/format";
import { dpRows, fmtPct } from "@/lib/poDp";
import { isPoV2, poV2SummaryRows, poTaxGroupRows, fmtIdr } from "@/lib/poTaxPrint";

const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nl2br = (v) => esc(v || "").replace(/\r?\n/g, "<br/>");
const idrPlain = (v) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(Number(v || 0));
const MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
export const longDateId = (v) => {
  if (!v) return "";
  const s = String(v).slice(0, 10).split("-");
  const [y, m, d] = s.map(Number);
  if (s.length !== 3 || !y || !m || !d) return fmtDate(v);
  return `${d} ${MONTHS_ID[m - 1] || ""} ${y}`;
};

/** Status yang dianggap final-approved untuk cetak (TIDAK DIUBAH dari logika existing). */
export const APPROVED_PO_STATUSES = new Set(["approved", "partially received", "fully received"]);
export const poApproved = (doc) => APPROVED_PO_STATUSES.has(String(doc?.status || "").trim().toLowerCase());

const PAGE_MM = { A4: [210, 297], A5: [148, 210], Letter: [215.9, 279.4] };
/** Margin minimum aman printer biasa (mm): kiri/kanan 15, atas/bawah 12. */
export const PRINT_SAFE_MM = { x: 15, y: 12 };
const uniq = (xs) => [...new Set((xs || []).map((x) => String(x || "").trim()).filter(Boolean))];

/** Referensi dokumen sumber baris PO: MRO (backend `mro_refs`, termasuk via RO) + RO (`ro_refs`). */
export function poLineRefs(l) {
  return { mro: uniq(l?.mro_refs), ro: uniq((l?.ro_refs || []).map((r) => r?.ro_no)) };
}
const withPrefix = (no, p) => (new RegExp(`^${p}\\b`, "i").test(no) ? no : `${p} ${no}`);
/** Label referensi cetak: HANYA nomor MRO (unik, urut kemunculan). Nomor RO tidak dicetak. */
export function poRefLabel(l) {
  return uniq(poLineRefs(l).mro.map((x) => withPrefix(x, "MRO"))).join(", ");
}

/** Kelompok baris berurutan dengan referensi MRO sama (seperti baris "MRO 2248" pada PO manual). */
export function poRefGroups(lines) {
  const groups = [];
  (lines || []).forEach((l, i) => {
    const label = poRefLabel(l);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.rows.push([l, i]);
    else groups.push({ label, rows: [[l, i]] });
  });
  const anyRef = groups.some((g) => g.label);
  return groups.map((g) => ({ ...g, label: g.label || (anyRef ? "Tanpa referensi MRO" : "") }));
}

/** Teks kolom "No. SPK" dari alokasi SPK tahap PO (endpoint existing /spk-allocations/po/doc). */
export function poSpkCell(summary) {
  const allocs = (summary?.allocations || []).filter((a) => Number(a.allocated_qty) > 0);
  if (!allocs.length) return "";
  const non = Number(summary?.non_spk_qty || 0);
  const name = (a) => a.spk_number || a.spk_id || "";
  if (allocs.length === 1 && non <= 1e-9) return name(allocs[0]);
  const parts = allocs.map((a) => `${name(a)} (${num(a.allocated_qty)})`);
  if (non > 1e-9) parts.push(`Non-SPK (${num(non)})`);
  return parts.join("\n");
}

/** Label baris PPN: tarif tunggal dari snapshot kelompok pajak (mis. "PPN 12%" seperti PO manual). */
function ppnLabel(doc) {
  const rules = doc?.tax_rules_snapshot || [];
  const rates = uniq((doc?.tax_groups || []).filter((g) => !Number(g.ppn_facility)).map((g) => {
    const r = rules.find((x) => x.group === g.group) || {};
    return r.tax_rate ?? String(g.group || "").split("|")[2];
  }).map((r) => (r == null || r === "" ? "" : String(Number(r)).replace(".", ","))));
  return rates.length === 1 ? `PPN ${rates[0]}%` : "PPN";
}

/** Syarat & catatan dokumen: baris bernomor -> indentasi gantung, "*" -> butir, heading tebal. */
export function renderTermsMessage(text, spk) {
  const raw = String(text || "").replace(/\r/g, "").trim();
  if (!raw && !spk) return "";
  const spkLine = spk ? `<div class="term-spk">SPK : ${esc(spk)}</div>` : "";
  let spkShown = !spk;
  const parts = (raw ? raw.split("\n") : []).map((line) => {
    const t = line.trim();
    const low = t.toLowerCase().replace(/\s*:$/, "");
    if (!t) return { html: `<div class="term-gap"></div>` };
    if (low === "term and condition" || low === "term & condition" || low === "terms and conditions" || low.startsWith("catatan") || low === "syarat dan ketentuan") {
      const pre = spk && !spkShown && low.startsWith("catatan") ? ((spkShown = true), spkLine) : "";
      return { html: `${pre}<div class="term-heading">${esc(t)}</div>` };
    }
    const m = t.match(/^(\d{1,2})[.)]?(?:\s+(.*))?$/);
    if (m) return { html: `<div class="term-item"><span class="term-no">${esc(m[1])}</span><span class="term-text">${esc(m[2] || "")}</span></div>` };
    const b = t.match(/^[*•-]\s+(.*)$/);
    if (b) return { bullet: true, html: `<div class="term-item bullet"><span class="term-no">*</span><span class="term-text">${esc(b[1])}</span></div>` };
    return { html: `<div class="term-item"><span class="term-no"></span><span class="term-text">${esc(t)}</span></div>` };
  });
  // >= 4 butir "*" berurutan -> 2 kolom (urutan per kolom) agar hemat tinggi halaman; < 4 tetap 1 kolom.
  let html = "";
  for (let i = 0; i < parts.length;) {
    if (!parts[i].bullet) { html += parts[i].html; i += 1; continue; }
    let j = i;
    while (j < parts.length && parts[j].bullet) j += 1;
    const run = parts.slice(i, j).map((x) => x.html).join("");
    html += j - i >= 4 ? `<div class="term-bullets">${run}</div>` : run;
    i = j;
  }
  return html + (spkShown ? "" : spkLine);
}

/** Baris ringkasan (kolom Price+Discount = label, Amount = nilai) — nilai tersimpan, tanpa hitung ulang. */
function summaryRows(doc, lines) {
  if (isPoV2(doc)) {
    const rows = poV2SummaryRows(doc);
    const same = (a, b) => Math.round(Number(a || 0) * 100) === Math.round(Number(b || 0) * 100);
    const before = rows.find((r) => r.key === "before_ppn");
    const plain = !rows.some((r) => ["item_disc", "final_disc", "after_disc"].includes(r.key)) && before && same(before.value, doc.gross_total);
    return rows.filter((r) => !(plain && r.key === "gross")).map((r) => ({
      cls: r.grand ? "grand" : r.sub ? "sum-sub" : r.strong ? "sum-strong" : "", key: r.key,
      label: `${r.sub ? "&#8627; " : ""}${esc(r.key === "ppn" ? ppnLabel(doc) : r.label)}${r.hint && r.key !== "dpp_other" ? `<div class="sum-hint">${esc(r.hint)}</div>` : ""}`,
      value: `${r.neg && r.value ? "- " : ""}${r.key === "ppn_facility" ? `(${fmtIdr(r.value)})` : fmtIdr(r.value)}`,
    }));
  }
  // PO lama (v1): baris & angka identik dengan cetak sebelumnya.
  const taxAmount = lines.reduce((a, l) => a + Number(l.tax_amount || 0), 0);
  const grand = Number(doc.grand_total ?? taxAmount);
  const grossTotal = lines.reduce((a, l) => { const f = Number(l.conversion_factor) || 1; const q = l.display_qty ?? ((Number(l.qty) || 0) / f); const p = l.display_price ?? ((Number(l.price) || 0) * f); return a + Number(q || 0) * Number(p || 0); }, 0);
  const itemDisc = lines.reduce((a, l) => a + Number(l.discount || 0), 0);
  const finalDisc = Number(doc.final_discount_amount || 0);
  const afterDisc = Number(doc.subtotal_after_discount ?? (grossTotal - itemDisc - finalDisc));
  const rates = [...new Set(lines.map((l) => Number(l.tax || 0)).filter((x) => x > 0))];
  const taxLabel = rates.length === 1 ? `PPN ${num(rates[0])}%` : (taxAmount ? "Pajak" : "PPN");
  return [
    { key: "gross", label: "Total Harga Sebelum Diskon", value: idrPlain(grossTotal) },
    itemDisc ? { key: "item_disc", label: "Diskon Item", value: `- ${idrPlain(itemDisc)}` } : null,
    finalDisc ? { key: "final_disc", label: "Diskon Final", value: `- ${idrPlain(finalDisc)}` } : null,
    { key: "after_disc", label: "Total Setelah Diskon", value: idrPlain(afterDisc) },
    { key: "ppn", label: esc(taxLabel), value: idrPlain(taxAmount) },
    { key: "grand", cls: "grand", label: "Grand Total", value: idrPlain(grand) },
  ].filter(Boolean);
}

/** Baris DP pada ringkasan (format manual: "DP 40%" + "Sisa Pembayaran"); nilai tersimpan backend (compute_po_dp). */
function dpSummaryRows(doc, money) {
  return dpRows(doc).map((r) => r.key === "dp"
    ? { key: "dp", cls: "dp-row", label: doc.dp_type === "percentage" ? `DP ${esc(fmtPct(doc.dp_value))}%` : "DP", value: money(r.amount) }
    : { key: "remaining", cls: "dp-row sum-strong", label: "Sisa Pembayaran", value: money(r.amount) });
}

export function realPoHtml({ doc, company, layout, logoImg, code, supplier, project, signatureImg, showPrice, internal, autoPrint = true }) {
  company = company || {};
  layout = layout || {};
  const font = layout.font_family || "Arial";
  const fs = Math.max(8, Number(layout.font_size) || 11);
  const small = Math.max(7, fs - 3);
  const marginBase = Math.max(5, Number(layout.margin_mm) || 10);
  const marginX = Math.max(PRINT_SAFE_MM.x, marginBase);
  const marginY = Math.max(PRINT_SAFE_MM.y, marginBase);
  const logoWidth = Number(layout.logo_width_mm) || 24;
  const paper = PAGE_MM[layout.paper_size] ? layout.paper_size : "A4";
  const orientation = layout.orientation === "landscape" ? "landscape" : "portrait";
  const pageH = (orientation === "landscape" ? PAGE_MM[paper][0] : PAGE_MM[paper][1]) - 2 * marginY - 0.6;
  const lines = doc.lines || [];
  const approved = poApproved(doc);
  const v2 = isPoV2(doc);
  const money = v2 ? fmtIdr : idrPlain;

  const contacts = supplier?.contacts || [];
  const marketing = contacts.find((x) => x.is_primary) || contacts[0] || {};
  const banks = supplier?.banks || [];
  const bank = banks.find((x) => x.id === doc.supplier_bank_id) || banks.find((x) => x.is_primary) || banks[0] || {};
  const bankName = doc.supplier_bank_name || bank.bank_name || "";
  const bankNo = doc.supplier_bank_account_no || bank.account_no || "";
  const bankAccountName = doc.supplier_bank_account_name || bank.account_name || supplier?.legal_name || supplier?.name || doc.supplier_name || "";

  const deliveryCompany = layout.po_delivery_company_name || company.name || "";
  const billCompany = layout.po_bill_company_name || company.name || "";
  const billAddress = layout.po_bill_address || company.address || "";
  const deliveryProject = project?.name ? `Project ${project.name}` : "";
  const deliveryAddress = company.address || "";

  // ---- tabel barang
  const cols = showPrice ? 8 : 6;
  const itemRow = (l, i) => {
    const f = Number(l.conversion_factor) || 1;
    const q = l.display_qty ?? ((Number(l.qty) || 0) / f);
    const p = l.display_price ?? ((Number(l.price) || 0) * f);
    const amount = Number(l.dpp ?? (Number(q || 0) * Number(p || 0) - Number(l.discount || 0)));
    const disc = Number(l.discount || 0);
    const sub = showPrice && l.notes ? `<div class="line-note">Ket: ${esc(l.notes)}</div>` : "";
    const fin = showPrice ? `<td class="r price">${idrPlain(p)}</td><td class="r discount">${disc ? idrPlain(disc) : "-"}</td><td class="r amount">${money(amount)}</td>` : "";
    return `<tr class="item"><td class="c no">${i + 1}</td><td class="desc"><div class="item-name">${esc(l.item_name || l.item_code || "")}</div>${sub}</td><td class="c spk">${nl2br(l._spk_label || "")}</td><td class="r qty">${num(q)}</td><td class="c unit">${esc(l.display_unit || l.unit || "")}</td>${showPrice ? fin : `<td class="ket">${esc(l.notes || "")}</td>`}</tr>`;
  };
  const emptyCells = (n) => Array.from({ length: n }, () => "<td></td>").join("");
  const body = lines.length ? poRefGroups(lines).map((g) => `${g.label ? `<tr class="grp"><td></td><td class="grp-label" colspan="2">${esc(g.label)}</td>${emptyCells(cols - 3)}</tr>` : ""}${g.rows.map(([l, i]) => itemRow(l, i)).join("")}`).join("") + `<tr class="filler">${emptyCells(cols)}</tr>`
    : `<tr><td colspan="${cols}" class="c">Tidak ada item</td></tr>`;
  const colgroup = showPrice
    ? `<colgroup><col style="width:4.5%"><col style="width:28.5%"><col style="width:14%"><col style="width:6.5%"><col style="width:5.5%"><col style="width:13%"><col style="width:11%"><col style="width:17%"></colgroup>`
    : `<colgroup><col style="width:5%"><col style="width:39%"><col style="width:15%"><col style="width:8%"><col style="width:8%"><col style="width:25%"></colgroup>`;
  const head = showPrice
    ? `<thead><tr><th>No</th><th>Description</th><th>No. SPK</th><th colspan="2">Qty</th><th>Price</th><th>Discount</th><th>Amount${v2 ? `<div class="th-sub">sebelum PPN</div>` : ""}</th></tr></thead>`
    : `<thead><tr><th>No</th><th>Description</th><th>No. SPK</th><th colspan="2">Qty</th><th>Keterangan</th></tr></thead>`;
  const sums = showPrice ? [...summaryRows(doc, lines), ...dpSummaryRows(doc, money)] : [];
  // ---- rincian pajak per kelompok: hanya untuk kombinasi (lebih dari 1 kelompok / fasilitas / campur Tanpa PPN)
  const groups = showPrice && v2 ? poTaxGroupRows(doc) : [];
  const nonPpn = Number(doc.non_ppn_total || 0);
  const combo = groups.length > 1 || groups.some((g) => g.facility) || (groups.length && nonPpn);
  const taxGroups = combo ? `<div class="tax-groups keep" data-section="tax-groups"><div class="sec-title">Rincian Pajak per Kelompok</div><table><thead><tr><th>Kelompok</th><th class="r">DPP</th><th class="r">DPP Nilai Lain</th><th class="r">PPN</th></tr></thead><tbody>${groups.map((x) => `<tr><td>${esc(x.label)}${x.facility ? " — tidak ditagih" : ""}</td><td class="r">${fmtIdr(x.dpp)}</td><td class="r">${fmtIdr(x.dpp_other)}</td><td class="r">${x.facility ? `0 (${fmtIdr(x.facility)})` : fmtIdr(x.ppn)}</td></tr>`).join("")}${nonPpn ? `<tr><td>Barang Tanpa PPN</td><td class="r">${fmtIdr(nonPpn)}</td><td class="r">–</td><td class="r">–</td></tr>` : ""}</tbody></table></div>` : "";
  // Garis penutup tabel barang: <tfoot> kosong berulang di dasar SETIAP halaman (tabel tidak "terbuka" saat terpotong halaman).
  const pageClose = `<tfoot class="page-close"><tr>${emptyCells(cols)}</tr></tfoot>`;
  // Ringkasan = tabel terpisah (kolom sama) -> tidak ikut berulang per halaman & tidak terbelah.
  const sumTable = sums.length ? `<table class="items sums keep" data-section="summary">${colgroup}<tbody>${sums.map((r, i) => `<tr class="sum ${r.cls || ""}" data-sum="${esc(r.key)}">${i === 0 ? `<td class="sum-spacer" colspan="5" rowspan="${sums.length}">${taxGroups}</td>` : ""}<td class="sum-label" colspan="2">${r.label}</td><td class="sum-value">${r.value}</td></tr>`).join("")}</tbody></table>` : "";
  // Penanda halaman lanjutan (hal. 2 dst.): "PO No. · Halaman n" di margin atas; halaman 1 tetap bersih seperti PO manual.
  const pageMark = String(doc.no || "PO").replace(/["\\\n\r]/g, "");


  // ---- ketentuan pembayaran: catatan pembayaran (nilai DP sudah di ringkasan); tanpa izin harga -> hanya syarat DP
  const payLines = [doc.dp_enabled && !showPrice ? "Uang Muka (DP) disyaratkan" : "", doc.payment_notes || ""].filter(Boolean);
  const payment = payLines.length ? `<div class="terms payment-notes keep" data-section="payment-terms"><div class="term-heading">Ketentuan Pembayaran</div>${payLines.map((t) => `<div class="term-item"><span class="term-no"></span><span class="term-text">${esc(t)}</span></div>`).join("")}</div>` : "";

  const terms = layout.show_message ? renderTermsMessage(doc.document_message, doc.spk) : "";

  // ---- catatan perubahan harga (INTERNAL ONLY, tidak pernah di salinan supplier)
  const overrideLines = internal ? lines.filter((l) => String(l.price_status || "") === "Price Override" || String(l.price_change_reason || "").trim()) : [];
  const reasonSection = overrideLines.length ? `<div class="price-reason keep"><div class="sec-title">Catatan Perubahan Harga (Internal)</div><table class="reason-table"><thead><tr><th>Barang</th><th>No. Kontrak</th><th class="r">Harga Kontrak</th><th class="r">Harga PO</th><th class="r">Selisih</th><th>Alasan</th></tr></thead><tbody>${overrideLines.map((l) => {
    const cp = Number(l.contract_price_snapshot || 0);
    const pp = Number(l.display_price ?? ((Number(l.price) || 0) * (Number(l.conversion_factor) || 1)));
    const varRp = pp - cp;
    const varPct = cp ? ` (${varRp >= 0 ? "+" : ""}${(varRp / cp * 100).toFixed(2)}%)` : "";
    return `<tr><td>${esc(l.item_name || l.item_code || "")}</td><td>${esc(l.contract_number_snapshot || "-")}</td><td class="r">${cp ? idrPlain(cp) : "-"}</td><td class="r">${idrPlain(pp)}</td><td class="r">${varRp >= 0 ? "+" : "-"}${idrPlain(Math.abs(varRp))}${esc(varPct)}</td><td>${esc(l.price_change_reason || "-")}</td></tr>`;
  }).join("")}</tbody></table></div>` : "";

  // ---- tanda tangan (logika existing: TTD/stempel hanya bila PO Approved)
  const approvedTask = [...(doc.approvals || [])].reverse().find((a) => String(a.status || "").toLowerCase() === "approved" && a.acted_by);
  const approvedName = layout.po_approved_name || approvedTask?.acted_by || "";
  const approvedCompany = layout.po_approved_company || company.name || "";
  const signedName = marketing.name || "";
  const supplierCompany = supplier?.legal_name || supplier?.name || doc.supplier_name || "";
  const approvedSignature = approved && signatureImg ? `<img class="approved-signature" src="${signatureImg}" alt=""/>` : "";
  const labels = layout.signature_labels || [];
  const signatures = layout.show_signatures ? `<div class="signatures keep"><div><div class="sign-label">${esc(labels[0] || "Approved by,")}</div><div class="sign-space">${approvedSignature}</div><div class="sign-name">${esc(approvedName)}</div><div class="sign-company">${esc(approvedCompany)}</div></div><div><div class="sign-label">${esc(labels[1] || "Signed by,")}</div><div class="sign-space"></div><div class="sign-name">${esc(signedName)}</div><div class="sign-company">${esc(supplierCompany)}</div></div></div>` : "";
  const qrHtml = layout.show_qr && code ? `<div class="verify">Verification Code: ${esc(code)}</div>` : "";
  const footer = String(layout.footer_text || "").trim() ? `<div class="page-footer">${nl2br(String(layout.footer_text).trim())}</div>` : "";
  const meta = (lab, val) => `<div class="meta-row"><span class="lab">${lab}</span><span>:</span><span class="val">${esc(val)}</span></div>`;

  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(doc.no || "PO")}</title>
  <style>
    @page{size:${paper} ${orientation};margin:${marginY}mm ${marginX}mm}
    @page{@top-right{content:"${pageMark}  ·  Halaman " counter(page);font-family:${font},Arial,sans-serif;font-size:${small}px;color:#4b5563;vertical-align:bottom;padding-bottom:2mm;padding-right:.6mm}}
    @page:first{@top-right{content:none}}
    *{box-sizing:border-box}
    html,body{margin:0;padding:0;background:#fff}
    @media screen{body{padding:${marginY}mm ${marginX}mm}}
    body{color:#000;font-family:${font},Arial,Helvetica,sans-serif;font-size:${fs}px;line-height:1.26;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    .sheet{min-height:${pageH.toFixed(1)}mm;display:flex;flex-direction:column;padding:0 .5mm}
    .draft-watermark{position:fixed;left:50%;top:48%;transform:translate(-50%,-50%) rotate(-32deg);font-size:74px;font-weight:900;letter-spacing:8px;color:#6b7280;opacity:.14;z-index:9999;pointer-events:none;user-select:none}
    .top{position:relative;min-height:15mm;margin-bottom:1.2mm}.real-logo{width:${logoWidth}mm;max-height:15mm;object-fit:contain;object-position:left center;display:block}.brand-name{font-weight:700;font-size:${fs + 1}px;margin-top:.5mm}
    .po-title{position:absolute;top:2mm;left:0;right:0;text-align:center;font-size:${fs + 7}px;font-weight:700;letter-spacing:.2px;pointer-events:none}
    .info-grid{display:grid;grid-template-columns:47% 50%;column-gap:3%;align-items:start}.address-block .label{font-weight:700}.address-block{line-height:1.24}.address-block .label.bill{margin-top:2.2mm}.address-block .kv{display:grid;grid-template-columns:9mm 1fr}
    .meta-box{border:.3mm solid #000;padding:.7mm 1.4mm}.meta-row{display:grid;grid-template-columns:30% 4% 66%;line-height:1.24}.meta-row .lab{white-space:nowrap}.meta-row .val{overflow-wrap:anywhere}.meta-note{line-height:1.24}
    table.items{width:100%;border-collapse:collapse;margin-top:3mm;table-layout:fixed;line-height:1.2}
    .items thead{display:table-header-group}.items tfoot.page-close{display:table-footer-group}
    .items tfoot.page-close td{border:none;border-top:.25mm solid #000;padding:0;height:0;line-height:0;font-size:0}
    table.items.sums{margin-top:-.25mm}
    .items th,.items td{border:.25mm solid #000;padding:.35mm 1.3mm;vertical-align:top}
    .items th{text-align:center;font-weight:700;vertical-align:middle}.items th .th-sub{font-weight:400;font-size:${small}px}
    .items .c{text-align:center}.items .r{text-align:right}.items td.price,.items td.amount,.items td.discount,.items td.qty{white-space:nowrap}
    .items td.spk{font-size:${Math.max(7, fs - 1)}px;overflow-wrap:anywhere}.items td.ket{font-size:${Math.max(7, fs - 1)}px}
    .items tr.grp td{border-top:.25mm solid #000;border-bottom:none}.items tr.grp + tr.item td{border-top:none}
    .items .grp-label{font-weight:700;font-style:italic}
    .items tr.item td{border-top:none;border-bottom:none}.items tr.filler td{border-top:none;height:1.6mm}
    .items .item-name{overflow-wrap:anywhere}.items .line-note{font-size:${small}px;font-style:italic;color:#374151}
    .items tbody tr{break-inside:avoid}
    .sums tr{break-inside:avoid}.sums td{padding:.3mm 1.3mm}.sums .sum-label,.sums .sum-value{font-size:${Math.max(8, fs - 1)}px}
    .sums .sum-spacer{border:none!important;border-left:.25mm solid transparent!important;background:transparent}
    .sums .sum-label{font-weight:700;text-align:left;white-space:nowrap}.sums .sum-value{text-align:right;white-space:nowrap}
    .sums .grand .sum-label,.sums .grand .sum-value,.sums .sum-strong .sum-value{font-weight:700}
    .sums .sum-sub .sum-label,.sums .sum-sub .sum-value{font-weight:400;font-size:${Math.max(7, fs - 2)}px}.sums .sum-hint{font-weight:400;font-size:${small}px}
    .sec-title{font-weight:700;margin-bottom:1mm}
    .tax-groups{margin:1.2mm 3.5mm 0 0}.tax-groups .sec-title{margin-bottom:.6mm}.tax-groups table,.reason-table{width:100%;border-collapse:collapse}.tax-groups th,.tax-groups td{padding:.3mm 1.2mm!important;border:.25mm solid #000!important}.tax-groups th,.tax-groups td,.reason-table th,.reason-table td{border:.25mm solid #000;padding:.6mm 1.4mm;font-size:${Math.max(7, fs - 1)}px;vertical-align:top}.tax-groups th,.reason-table th{text-align:left}.tax-groups .r,.reason-table .r{text-align:right;white-space:nowrap}
    .price-reason{margin-top:3mm}
    .terms{margin-top:3mm;line-height:1.2;font-size:${Math.max(7, fs - 1)}px}.terms .term-heading{font-size:${fs}px}.term-heading{font-weight:700;margin-top:1.2mm}.term-heading:first-child{margin-top:0}.term-spk{margin-top:1mm}
    .term-item{display:grid;grid-template-columns:9mm 1fr}.term-item .term-no{text-align:center}.term-item.bullet{grid-template-columns:9mm 1fr}.term-item.bullet .term-no{text-align:right;padding-right:1.2mm}.term-gap{height:.6mm}.term-bullets{columns:2;column-gap:4mm}.term-bullets .term-item{break-inside:avoid}
    .bank-wrap{margin-top:2.5mm}.bank-title{font-weight:700;margin-bottom:.8mm}.bank-table{width:100%;border-collapse:collapse;text-align:center}.bank-table th,.bank-table td{border-top:.25mm solid #000;border-bottom:.25mm solid #000;padding:.35mm 1.5mm;font-weight:400}
    .signatures{display:grid;grid-template-columns:1fr 1fr;column-gap:30mm;text-align:center;margin-top:2.5mm;margin-bottom:1.5mm}.sign-label{font-weight:700}.sign-space{height:14mm;display:flex;align-items:center;justify-content:center}.approved-signature{max-width:40mm;max-height:13.8mm;object-fit:contain}.sign-name{font-weight:700;text-decoration:underline}.sign-company{font-weight:700}
    .keep{break-inside:avoid;page-break-inside:avoid}
    .verify{font-size:${small}px;text-align:right;margin-top:2mm;color:#4b5563}
    .closing{flex:1 0 auto;display:flex;flex-direction:column;break-inside:avoid;page-break-inside:avoid}
    .page-footer{margin-top:auto;padding-top:1mm;border-top:.35mm solid #000;text-align:center;font-size:${Math.max(7, fs - 1)}px;line-height:1.35}
    
  </style></head><body>
    ${!approved ? `<div class="draft-watermark">DRAFT</div>` : ""}
    <div class="sheet">
    <div class="top">
      <div class="brand">${layout.show_logo !== false && logoImg ? `<img class="real-logo" src="${logoImg}" alt=""/>` : ""}<div class="brand-name">${esc(deliveryCompany)}</div></div>
      <div class="po-title">${esc(layout.title || "PURCHASE ORDER")}</div>
    </div>
    <div class="info-grid">
      <div class="address-block">
        <div class="label">Please Delivery to :</div>
        ${deliveryCompany ? `<div>${esc(deliveryCompany)}</div>` : ""}
        ${deliveryProject ? `<div>${esc(deliveryProject)}</div>` : ""}
        ${deliveryAddress ? `<div>${nl2br(deliveryAddress)}</div>` : ""}
        <div class="label bill">Please Bill to :</div>
        ${billCompany ? `<div>${esc(billCompany)}</div>` : ""}
        ${billAddress ? `<div>${nl2br(billAddress)}</div>` : ""}
        ${layout.po_bill_contact ? `<div class="kv"><span>Up.</span><span>${esc(layout.po_bill_contact)}</span></div>` : ""}
        ${layout.po_bill_phone ? `<div class="kv"><span>Hp.</span><span>${esc(layout.po_bill_phone)}</span></div>` : ""}
      </div>
      <div class="meta-box">
        ${meta("PO No.", doc.no || "")}${meta("PO Date", longDateId(doc.date))}${meta("Supplier", doc.supplier_name || supplier?.name || "")}${meta("Supplier ref", doc.supplier_ref || doc.supplier_notes || "")}
        <div class="meta-note">This PO Number must appear on all invoices.</div><div class="meta-note">Packing list delivery orders.</div>
        ${meta("Buyer's Contact", doc.buyer_contact_name || "")}${meta("Phone", doc.buyer_contact_phone || "")}${meta("Marketing Contact", marketing.name || "")}${meta("Phone", marketing.phone || "")}${meta("Payment terms", doc.payment_term || "")}${meta("Delivery terms", doc.delivery_term || "")}
      </div>
    </div>
    <table class="items main">${colgroup}${head}<tbody>${body}</tbody>${pageClose}</table>${sumTable}
    ${reasonSection}
    ${terms ? `<div class="terms">${terms}</div>` : ""}
    ${payment}
    ${bankName || bankNo || bankAccountName ? `<div class="bank-wrap keep"><div class="bank-title">Pembayaran dilakukan ke Rekening :</div><table class="bank-table"><thead><tr><th>Nama Bank</th><th>No. Rekening</th><th>Atas Nama</th></tr></thead><tbody><tr><td>${esc(bankName)}</td><td>${esc(bankNo)}</td><td>${esc(bankAccountName)}</td></tr></tbody></table></div>` : ""}
    <div class="closing" data-section="closing">${signatures}${qrHtml}${footer}</div>
    </div>
    ${autoPrint ? `<script>window.onload=function(){setTimeout(function(){window.print()},550)}</script>` : ""}
  </body></html>`;
}

/** Rakit cetak PO REAL: label No. SPK per baris dari alokasi tahap PO, lalu realPoHtml. Tidak memodifikasi `doc` asal. */
export function buildPoPrintHtml({ doc, allocLines, ...rest }) {
  const amap = Object.fromEntries((allocLines || []).map((l) => [l.item_line_id, l]));
  const lines = (doc?.lines || []).map((l) => ({ ...l, _spk_label: poSpkCell(amap[l.id]) }));
  return realPoHtml({ ...rest, doc: { ...doc, lines } });
}
