// Node test (no deps): node frontend/src/lib/dashboard.test.mjs
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { ATTENTION_TABS, attentionRows, ccParams, compactRupiah, drillLink, inventoryLink, isBacklog, asOfLabel, monthLabel, periodRange, statusLabel, STATUS_META } from "./dashboard.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, p), "utf8");
let fail = 0, n = 0;
const check = (name, cond, info = "") => { n++; console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };
const T = new Date(2026, 9, 7); // 7 Okt 2026

check("Default periode = bulan berjalan", JSON.stringify(periodRange("this_month", T)) === JSON.stringify({ date_from: "2026-10-01", date_to: "2026-10-31" }));
check("Bulan lalu", periodRange("last_month", T).date_from === "2026-09-01" && periodRange("last_month", T).date_to === "2026-09-30");
check("3 bulan terakhir", periodRange("last_3", T).date_from === "2026-08-01");
check("Tahun ini", periodRange("this_year", T).date_to === "2026-12-31");
check("Semua periode -> period=all", ccParams({ period: "all" }, T).period === "all" && !("date_from" in ccParams({ period: "all" }, T)));
check("ccParams membuang filter kosong", JSON.stringify(ccParams({ period: "this_month", division_id: "d1", project_id: "", supplier_id: "" }, T)) ===
  JSON.stringify({ date_from: "2026-10-01", date_to: "2026-10-31", division_id: "d1" }));
check("Rupiah ringkas M / jt / rb", compactRupiah(3_420_000_000) === "Rp 3,42 M" && compactRupiah(985_000_000) === "Rp 985 jt" && compactRupiah(12_000) === "Rp 12 rb");
check("Nilai tanpa izin = ***", compactRupiah(null) === "***");
check("Label bulan", monthLabel("2026-10") === "Okt 26");
for (const [k, l] of [["Waiting Approval 1", "Menunggu Approval 1"], ["Ready Approval 2", "Siap Diajukan Approval 2"], ["Waiting Approval 2", "Menunggu Approval 2"],
  ["Approved", "Disetujui"], ["Closed", "Ditutup"], ["Rejected", "Ditolak"], ["Cancelled", "Dibatalkan"], ["Draft", "Draft"]])
  check(`Label donut ${k} -> ${l}`, statusLabel(k) === l);
check("Warna donut tidak neon (semua hex muted terdefinisi)", Object.values(STATUS_META).every((m) => /^#[0-9A-F]{6}$/i.test(m.color)));

const f = { period: "this_month", division_id: "d1", project_id: "p1", supplier_id: "s1" };
const q = (u) => new URLSearchParams(u.split("?")[1] || "");
const a1 = drillLink("waiting_a1", f, {}, T);
check("Drill Menunggu Approval 1 -> PO list rf_kind + filter global, posisi: date_to tanpa date_from", a1.startsWith("/po?") && q(a1).get("rf_kind") === "waiting_a1" && q(a1).get("rf_division_id") === "d1"
  && q(a1).get("rf_project_id") === "p1" && q(a1).get("rf_supplier_id") === "s1" && q(a1).get("date_to") === "2026-10-31" && !q(a1).has("date_from") && !q(a1).has("rf_asof"), a1);
// Kelompok A (posisi s/d cut-off): date_to = cut-off, TANPA date_from; historis -> rf_asof = cut-off.
const LM = { ...f, period: "last_month" }; // cut-off 30/09/2026 (lampau terhadap T)
const A_KINDS = ["mro_open", "ro_open", "waiting_a1", "ready_a2", "waiting_a2", "waiting_approval", "not_received", "partial", "late", "invoice_unbilled", "unpaid", "payable", "due_soon", "overdue"];
for (const k of A_KINDS) {
  const u = drillLink(k, LM, {}, T);
  check(`Kelompok A ${k}: date_to=cut-off, tanpa date_from, rf_asof=cut-off`, q(u).get("date_to") === "2026-09-30" && !q(u).has("date_from") && q(u).get("rf_asof") === "2026-09-30", u);
  const c = drillLink(k, f, {}, T);
  check(`Kelompok A ${k} (bulan berjalan): date_to ada, tanpa date_from/rf_asof`, q(c).get("date_to") === "2026-10-31" && !q(c).has("date_from") && !q(c).has("rf_asof"), c);
}
// Kelompok B (aktivitas periode): date_from + date_to.
for (const k of ["approved", "po_all", "valid"]) {
  const u = drillLink(k, LM, {}, T);
  check(`Kelompok B ${k}: date_from + date_to periode`, q(u).get("date_from") === "2026-09-01" && q(u).get("date_to") === "2026-09-30" && !q(u).has("rf_asof"), u);
}
check("isBacklog: A vs B", ["waiting_a1", "late", "payable", "dp_unallocated"].every(isBacklog) && !["approved", "po_all", "valid", "dp_paid"].some(isBacklog));
check("Drill Siap Approval 2 (berhak A2) -> PO list rf_kind (count = kartu)", q(drillLink("ready_a2", f, { approval2: true }, T)).get("rf_kind") === "ready_a2" && drillLink("ready_a2", f, { approval2: true }, T).startsWith("/po?"));
check("Drill Siap Approval 2 tanpa hak Approval 2 -> PO list", q(drillLink("ready_a2", f, {}, T)).get("rf_kind") === "ready_a2");
check("Drill Menunggu Approval 2 -> PO list rf_kind=waiting_a2", q(drillLink("waiting_a2", f, { approval2: true }, T)).get("rf_kind") === "waiting_a2" && drillLink("waiting_a2", f, { approval2: true }, T).startsWith("/po?"));
check("Drill PO Belum Diterima", q(drillLink("not_received", f, {}, T)).get("rf_kind") === "not_received");
check("Drill PO Terlambat", q(drillLink("late", f, {}, T)).get("rf_kind") === "late");
check("Drill Invoice Belum Dibayar -> Vendor Invoice rf_kind=unpaid", drillLink("unpaid", f, {}, T).startsWith("/invoice?") && q(drillLink("unpaid", f, {}, T)).get("rf_kind") === "unpaid");
check("Drill Sisa Hutang -> monitoring hutang (invoice sisa > 0)", q(drillLink("payable", f, {}, T)).get("rf_kind") === "unpaid");
check("Drill Jatuh Tempo / Lewat Jatuh Tempo", q(drillLink("due_soon", f, {}, T)).get("rf_kind") === "due_soon" && q(drillLink("overdue", f, {}, T)).get("rf_kind") === "overdue");
check("Drill Invoice Belum Diterima -> tab Status Penagihan DO", q(drillLink("invoice_unbilled", f, {}, T)).get("tab") === "do" && q(drillLink("invoice_unbilled", f, {}, T)).get("rf_kind") === "unbilled");
check("Drill MRO Belum Diproses (supplier tidak relevan)", drillLink("mro_open", f, {}, T).startsWith("/mro?") && !q(drillLink("mro_open", f, {}, T)).get("rf_supplier_id"));
check("Drill DP -> DP Supplier", drillLink("dp_unallocated", f, {}, T) === "/dp-supplier");
const att = { rows: [{ key: "a", tabs: ["unpaid", "due"] }, { key: "b", tabs: ["approval"] }] };
check("Tab attention memfilter baris", attentionRows(att, "due").length === 1 && attentionRows(att, "all").length === 2);
check("Tab finance ditandai (disembunyikan tanpa izin)", ATTENTION_TABS.filter((t) => t.finance).map((t) => t.key).join() === "unbilled,unpaid,due");

const dash = src("../pages/Dashboard.jsx");
check("Dashboard memakai satu endpoint control-center (bukan dashboard kedua)", dash.includes('api.get("/dashboard/control-center"') && !dash.includes('api.get("/dashboard-premium")'));
check("Filter Periode/Divisi/Project/Supplier/Reset ada", ["dash-filter-period", "dash-filter-division", "dash-filter-project", "dash-filter-supplier", "dash-filter-reset"].every((t) => dash.includes(t)));
check("Section Finance hanya bila backend mengirim finance", /\{F && <>/.test(dash));
check("Animasi hanya opacity/transform", !/transition-all/.test(dash + src("../components/dashboard/KpiCard.jsx")));
const chip = src("../components/dashboard/ReportFilterChip.jsx");
check("Drill-down list membaca rf_* dari URL", ["rf_kind", "rf_division_id", "rf_project_id", "rf_supplier_id"].every((k) => chip.includes(k)));
for (const p of ["../pages/Po.jsx", "../pages/Mro.jsx", "../pages/Ro.jsx", "../pages/InvoiceMonitoring.jsx"])
  check(`List ${p.split("/").pop()} mendukung filter drill-down`, src(p).includes("useReportParams()"));

// KPI Persediaan: summary canonical backend; frontend tidak menghitung dari item_warehouse.
check("Link Jumlah Item -> /inventory (tanpa status)", inventoryLink("total", {}) === "/inventory");
check("Link Stok Habis -> stock_status=Out of Stock + division", (() => { const u = new URLSearchParams(inventoryLink("out_of_stock", { division_id: "d1" }).split("?")[1]); return u.get("stock_status") === "Out of Stock" && u.get("division_id") === "d1"; })());
check("Link Menipis/Overstock", inventoryLink("low_stock").includes("Low+Stock") && inventoryLink("overstock").includes("stock_status=Overstock"));
const inv = src("../pages/Inventory.jsx");
check("Inventory memakai /inventory/item-stock (bukan agregasi /inventory/position)", inv.includes("/inventory/item-stock") && !inv.includes("/inventory/position") && !/function stockStatus/.test(inv));
check("Inventory menampilkan 'Belum ada stok' untuk sel tanpa record", inv.includes("Belum ada stok"));
// Persediaan dirender oleh InventoryPanel (Layer 2) dengan kartu dari inventoryCards (lib) — sumber data tetap d.inventory.
const invp = src("../components/dashboard/InventoryPanel.jsx") + src("./dashboard.js");
check("Dashboard KPI Persediaan dari d.inventory.stock (Jumlah Item/Habis/Menipis/Overstock)", dash.includes("inv={d.inventory}") && ["\"total\"", "\"out_of_stock\"", "\"low_stock\"", "\"overstock\""].every((k) => invp.includes(k)) && invp.includes("inventory_value != null"));

check("asOfLabel format tanggal per", asOfLabel("2026-09-30") === "30/09/2026" && asOfLabel(null) === "hari ini");
check("UI memisahkan 'Persediaan saat ini' (snapshot) dari 'Nilai Persediaan per' (tanggal akhir filter)", invp.includes("Persediaan saat ini") && invp.includes("snapshot hari ini") && invp.includes("Nilai Persediaan") && invp.includes("<>per <span"));
check("Dashboard menampilkan tanggal per & info belum bernilai", invp.includes("inventory_value_as_of") && invp.includes("unvalued_items") && invp.includes("belum bernilai") && dash.includes("unvalued_items > 0"));
check("Label kelompok: 'Posisi s/d' (Procurement/Finance/Perlu Ditindaklanjuti) vs 'Transaksi periode ini' (Aktivitas)", dash.includes("Posisi s/d ${asOfLabel(d?.as_of)}") && dash.includes('"Transaksi periode ini"')
  && ["Procurement — {posLabel}", "Finance — {posLabel}", "Aktivitas Pembelian — {actLabel}", "Perlu Ditindaklanjuti — {posLabel}"].every((t) => dash.includes(t)));
check("Kartu aktivitas: Total PO, PO Disetujui, DP Sudah Dibayar", ['k: "po_all"', 'k: "approved"', 'k: "dp_paid"'].every((t) => dash.includes(t)));
check("Peringatan pool historis belum dapat direkonstruksi", invp.includes("unreconstructable_pools") && invp.includes("pool persediaan historis belum dapat direkonstruksi"));
const unv = readFileSync(new URL("../components/dashboard/UnvaluedStockDialog.jsx", import.meta.url), "utf8");
const oc = readFileSync(new URL("../components/OpeningCorrection.jsx", import.meta.url), "utf8");
check("Label 'belum bernilai' clickable membuka detail", dash.includes("setUnvaluedOpen(true)") && dash.includes("<UnvaluedStockDialog"));
check("Detail belum bernilai: kolom Kode|Barang|Gudang|Qty|Avg Cost|Nilai Saat Ini|Kandidat Opening|Status",
  ["Kode", "Barang", "Gudang", "Qty", "Avg Cost", "Nilai Saat Ini", "Kandidat Opening", "Status"].every((t) => unv.includes(`>${t}</th>`)) && unv.includes("/valuation/opening-status"));
check("Tetapkan Massal preview: Item|Gudang|Qty Awal|Harga Awal|Nilai Awal|Status + ringkasan", ["Item", "Gudang", "Qty Awal", "Harga Awal", "Nilai Awal", "Status"].every((t) => oc.includes(`>${t}</th>`))
  && ["Bisa ditetapkan", "Perlu Revaluasi (tidak ikut)", "Tidak Ada Nilai Sumber"].every((t) => oc.includes(t)));
check("Revaluasi: Dry Run wajib sebelum apply + frasa konfirmasi", oc.includes("/valuation/replay/dry-run") && oc.includes("fingerprint: dry.fingerprint") && oc.includes("confirm_phrase")
  && ["Nilai persediaan sebelum", "Nilai opening dimasukkan", "Nilai sesudah replay", "Transaksi terdampak", "Transaksi keluar terdampak", "HPP terdampak"].every((t) => oc.includes(t)));
check("Chip drill-down meneruskan rf_asof & label Posisi s/d", chip.includes('"rf_asof"') && chip.includes("Posisi s/d"));

console.log(fail ? `\n${fail} FAILED` : `\n${n}/${n} passed`);
process.exit(fail ? 1 : 0);
