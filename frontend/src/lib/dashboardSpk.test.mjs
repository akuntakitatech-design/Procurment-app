// Node test (no deps): node frontend/src/lib/dashboardSpk.test.mjs — SPK & Budget Control + Kontrak Harga Vendor / Price Control
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  barPct, contractDetailLink, contractDrillParams, contractKpiCards, drillUrl, exceptionColumns, pctText, poDetailLink,
  priceDrillParams, priceKpiCards, spkDetailLink, spkDrillParams, spkKpiCards, spkSummaryCards, inventoryCards, SPK_LEVEL,
} from "./dashboard.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, p), "utf8");
let fail = 0, n = 0;
const check = (name, cond, info = "") => { n++; console.log(`${cond ? "PASS" : "FAIL"} ${name}${!cond && info ? " — " + JSON.stringify(info) : ""}`); if (!cond) fail++; };
const T = new Date(2026, 9, 7); // 7 Okt 2026
const f = { period: "this_month", division_id: "d1", project_id: "p1", supplier_id: "s1" };
const qp = (url) => new URLSearchParams(url.split("?")[1] || "");

// 1–2. Urutan section (urutan render JSX = urutan DOM): Layer 1 -> Layer 2 (Persediaan | SPK | Kontrak) -> Layer 3 -> Layer 4
const dash = src("../pages/Dashboard.jsx");
const pos = (id) => dash.indexOf(`data-testid="${id}"`);
const order = ["dash-layer-1", "dash-section-procurement", "dash-section-finance", "dash-section-activity",
  "dash-layer-2", "dash-section-inventory", "dash-section-spk", "dash-section-contract",
  "dash-layer-spk-detail", "dash-section-spk-detail", "dash-layer-3", "dash-layer-4", "dash-section-attention", "dash-layer-detail"].map((id) => [id, dash.indexOf(id === "dash-section-procurement" || id === "dash-section-finance" || id === "dash-section-activity" || id === "dash-section-attention" || id === "dash-section-spk-detail" ? `testid="${id}"` : `data-testid="${id}"`)]);
check("Semua section/layer ada di Dashboard", order.every(([, i]) => i > 0), order.filter(([, i]) => i < 0));
check("Urutan: Layer1 (Procurement, Finance, Aktivitas) -> Layer2 (Persediaan, SPK, Kontrak) -> Layer3 -> Layer4 -> detail",
  order.every(([, i], k) => k === 0 || i > order[k - 1][1]), order);
const l2 = pos("dash-layer-2"), l3 = pos("dash-layer-3");
check("Section SPK muncul setelah Persediaan (dalam Layer 2)", pos("dash-section-inventory") > l2 && pos("dash-section-spk") > pos("dash-section-inventory") && pos("dash-section-spk") < l3);
check("Section Kontrak Harga Vendor muncul setelah SPK (dalam Layer 2)", pos("dash-section-contract") > pos("dash-section-spk") && pos("dash-section-contract") < l3);
check("Pemakaian Budget SPK tepat setelah baris Persediaan | SPK | Kontrak (sebelum Analitik)", pos("dash-layer-spk-detail") > pos("dash-section-contract") && pos("dash-layer-spk-detail") < l3
  && /<SpkDetailPanel/.test(dash.slice(pos("dash-layer-spk-detail"), l3)));
const l1Block = dash.slice(pos("dash-layer-1"), l2);
check("Layer 1 gaya referensi: 3 panel berpita (Procurement navy, Finance & Aktivitas teal) satu baris di layar lebar",
  (l1Block.match(/<ControlSection/g) || []).length === 3 && /band="navy"/.test(l1Block) && (l1Block.match(/band="teal"/g) || []).length === 2
  && /min-\[1680px\]:grid-cols-\[11fr_7fr_6fr\]/.test(dash) && /data-testid="dash-layer-1"/.test(dash));
check("Layer 1: Procurement = RingStat, Finance = SoftStat, Aktivitas = ActivityStat; testid KPI existing dipertahankan",
  /<RingStat/.test(l1Block) && /<SoftStat/.test(l1Block) && /<ActivityStat/.test(l1Block) && (l1Block.match(/testid=\{`dash-kpi-\$\{c\.k\}`\}/g) || []).length === 3);
const ctl = src("../components/dashboard/ControlPanels.jsx");
check("Panel Layer 1: count/sub testid existing (-count, -sub) dan tombol Lihat Detail", (ctl.match(/`\$\{testid\}-count`/g) || []).length === 3 && (ctl.match(/`\$\{testid\}-sub`/g) || []).length === 3 && /Lihat Detail/.test(ctl));
check("Bar mini Aktivitas dari seri tren existing (tanpa data sintetis 'periode lalu')", /d\?\.charts\?\.trend\?\.series/.test(dash) && !/periode lalu/.test(ctl + dash));
const l3Block = dash.slice(l3, pos("dash-layer-4"));
check("Layer 3 = Tren · Komposisi · Top 5 Supplier", /<TrendChart/.test(l3Block) && /<StatusDonut/.test(l3Block) && /<TopSuppliers/.test(l3Block));
const l4Block = dash.slice(pos("dash-layer-4"), pos("dash-layer-detail"));
check("Layer 4 = Perlu Ditindaklanjuti + Monitoring Finance", /<AttentionTable/.test(l4Block) && /<FinanceMonitor/.test(l4Block));
const l2Block = dash.slice(l2, l3);
check("Layer 2: desktop lebar 3 kolom, laptop 2 (Kontrak melebar), tablet/mobile 1", /grid grid-cols-1 gap-4 pt-1 xl:grid-cols-2 2xl:grid-cols-3" data-testid="dash-layer-2"/.test(dash)
  && /xl:col-span-2 2xl:col-span-1" data-testid="dash-section-contract"/.test(dash));
check("Layer 2 berisi InventoryPanel, SpkSummaryCard, ContractStatusPanel", /<InventoryPanel/.test(l2Block) && /<SpkSummaryCard/.test(l2Block) && /<ContractStatusPanel/.test(l2Block));
check("Price Control & Price Exception tetap ada (detail lanjutan)", /<PriceControlPanel/.test(dash.slice(pos("dash-layer-detail"))) && /<PriceExceptionTable/.test(dash.slice(pos("dash-layer-detail"))));
check("Kartu SPK Layer 2: subtitle posisi s/d SP.as_of", /dash-spk-asof">Posisi s\/d \{asOfLabel\(SP\.as_of\)\}/.test(dash));
check("Judul SPK memakai tanggal posisi backend (as_of)", /SPK &amp; Budget Control — Posisi s\/d \{asOfLabel\(SP\.as_of\)\}/.test(dash));

// 3. SPK memakai date_to saja
const sp = new URLSearchParams(spkDrillParams("2026-09-30", f, "over"));
check("Drill SPK: date_to = cut-off", sp.get("date_to") === "2026-09-30");
check("Drill SPK: date_from TIDAK ada", !sp.has("date_from"));
check("Drill SPK: kind + Divisi + Project ikut; Supplier tidak dipaksakan", sp.get("kind") === "over" && sp.get("division_id") === "d1" && sp.get("project_id") === "p1" && !sp.has("supplier_id"));
check("Dashboard: drill SPK dibangun dari SP.as_of (bukan periode)", /spkDrillParams\(SP\?\.as_of, f, kind\)/.test(dash));
const su = qp(drillUrl("spk", spkDrillParams("2026-09-30", { period: "last_month" }, "active")));
check("URL drill SPK (parse query): date_to ada, date_from tidak ada", su.get("date_to") === "2026-09-30" && !su.has("date_from") && su.get("kind") === "active");

// 4. Status kontrak memakai date_to saja
const cp = new URLSearchParams(contractDrillParams("2026-06-30", f, "expiring"));
check("Drill kontrak: date_to ada, date_from tidak ada", cp.get("date_to") === "2026-06-30" && !cp.has("date_from"));
check("Drill kontrak: Supplier ikut, Divisi/Project tidak (kontrak tanpa divisi)", cp.get("supplier_id") === "s1" && !cp.has("division_id") && cp.get("kind") === "expiring");
check("Dashboard: drill kontrak dibangun dari VC.as_of", /contractDrillParams\(VC\?\.as_of, f, kind\)/.test(dash));

// 5. Price Control memakai date_from + date_to
const pp = qp(drillUrl("price", priceDrillParams(f, "over", T)));
check("Drill Price Control: date_from & date_to ada (periode)", pp.get("date_from") === "2026-10-01" && pp.get("date_to") === "2026-10-31");
check("Drill Price Control: status + Divisi/Project/Supplier ikut", pp.get("status") === "over" && pp.get("division_id") === "d1" && pp.get("project_id") === "p1" && pp.get("supplier_id") === "s1");
const pl = new URLSearchParams(priceDrillParams({ period: "last_month" }, "ok", T));
check("Drill Price Control bulan lalu: 01/09–30/09", pl.get("date_from") === "2026-09-01" && pl.get("date_to") === "2026-09-30");
const pa = new URLSearchParams(priceDrillParams({ period: "all" }, "all", T));
check("Drill Price Control semua periode: period=all, tanpa tanggal", pa.get("period") === "all" && !pa.has("date_from") && !pa.has("date_to"));

// 6–7. Drill-down ke detail existing
const app = src("../App.js");
check("Detail SPK existing /spk/:id", spkDetailLink("abc") === "/spk/abc" && app.includes('path="/spk/:id"'));
check("Detail PO existing /po/:id", poDetailLink("p9") === "/po/p9" && app.includes('path="/po/:id"'));
check("Detail kontrak existing /vendor-contracts/:id", contractDetailLink("k1") === "/vendor-contracts/k1" && app.includes('path="/vendor-contracts/:id"'));
const spkPanel = src("../components/dashboard/SpkBudgetPanel.jsx"), vcPanel = src("../components/dashboard/VendorContractPanel.jsx");
const drillDlg = src("../components/dashboard/DashboardDrillDialog.jsx");
check("Top 5 & Perlu Perhatian membuka detail SPK existing", (spkPanel.match(/nav\(spkDetailLink\(x\.id\)\)/g) || []).length === 2);
check("Price Exception membuka detail PO existing", /nav\(poDetailLink\(r\.po_id\)\)/.test(vcPanel));
check("Dialog drill membuka detail existing (SPK/Kontrak/PO)", /spkDetailLink\(x\.id\)/.test(drillDlg) && /contractDetailLink\(x\.id\)/.test(drillDlg) && /poDetailLink\(r\.po_id\)/.test(drillDlg));

// 8. Permission nominal SPK
const noVal = spkKpiCards({ with_value: false, kpi: { active: 12, over_budget: 2, critical: 1, attention: 4, expiring: 1 } });
check("Tanpa spk:view: hanya kartu count (tanpa nominal)", noVal.every((c) => !c.money) && noVal.map((c) => c.key).join() === "active,over_budget,critical,attention");
check("Tanpa spk:view: tidak ada placeholder Rp / nominal di kartu", !JSON.stringify(noVal).includes("Rp") && noVal.find((c) => c.key === "active").value === 12);
const withVal = spkKpiCards({ with_value: true, kpi: { active: 3, budget: 1000, commitment: 800, realization: 500, open_commitment: 300, remaining: 200, usage_pct: 80, realization_pct: 62.5 } });
check("Dengan spk:view: 6 KPI (SPK Aktif, Budget, Commitment, Realisasi, Open, Sisa)", withVal.map((c) => c.key).join() === "active,budget,commitment,realization,open_commitment,remaining");
check("Sisa Budget = nilai backend (Budget − Commitment = 200), bukan dihitung ulang frontend", withVal.find((c) => c.key === "remaining").value === 200);
check("Panel SPK: daftar Top/Perhatian hanya dirender bila with_value", /if \(!spk\?\.with_value\) return null;/.test(spkPanel));
check("Frontend tidak menghitung Budget − Commitment − Realisasi", !/budget\s*-\s*k\.commitment\s*-|remaining\s*=.*realization/.test(spkPanel + src("./dashboard.js")));

// 8b. Kartu ringkas Layer 2 = nilai backend yang sama (tanpa formula baru)
const kv = { with_value: true, kpi: { active: 3, budget: 1000, commitment: 800, realization: 500, open_commitment: 300, remaining: 200, usage_pct: 80, realization_pct: 62.5 } };
const sum = spkSummaryCards(kv);
check("Ringkasan SPK Layer 2: SPK Aktif · Budget · Commitment · Sisa Budget", sum.map((c) => c.key).join() === "active,budget,commitment,remaining");
check("Ringkasan SPK: nilai identik dengan KPI backend (Sisa 200 = Budget − Commitment)", sum.find((c) => c.key === "remaining").value === 200 && sum.find((c) => c.key === "commitment").value === 800 && sum.find((c) => c.key === "commitment").sub === "realisasi 62,5%");
check("Ringkasan SPK tanpa spk:view: 4 kartu count, tanpa nominal", spkSummaryCards({ with_value: false, kpi: { active: 2 } }).every((c) => !c.money));
const ic = inventoryCards({ stock: { total: 40, out_of_stock: 4, low_stock: 2, overstock: 1 } });
check("Kartu Persediaan: Jumlah Item, Stok Habis, Stok Menipis, Overstock (angka backend apa adanya)", ic.map((c) => `${c.key}:${c.value}`).join() === "total:40,out_of_stock:4,low_stock:2,overstock:1" && ic[1].pct === 10);
const invPanel = src("../components/dashboard/InventoryPanel.jsx");
check("Persediaan: Nilai Persediaan + tombol Lihat Detail + drill existing inventoryLink", /Nilai Persediaan/.test(invPanel) && /dash-inventory-detail/.test(invPanel) && /nav\(inventoryLink\(c\.key, f\)\)/.test(invPanel));

// 9. Permission harga
const pc = { kpi: { po_ok: 41, po_over: 2, po_no_contract: 7, po_evaluated: 50, diff_value: 125000 } };
check("Price Control dengan izin harga: kartu Nilai Selisih tampil", priceKpiCards(pc, true).some((c) => c.key === "diff"));
check("Price Control tanpa izin harga: hanya count (tanpa Nilai Selisih)", priceKpiCards(pc, false).every((c) => !c.money) && priceKpiCards(pc, false).length === 3);
check("Kolom harga Price Exception hanya bila nominal dikirim", exceptionColumns(true).includes("Harga PO") && !exceptionColumns(false).some((c) => /Harga|Selisih|Tolerance/.test(c)));
check("Tabel exception & dialog drill memakai flag with_value backend", /exceptionColumns\(wv\)/.test(vcPanel) && /data\?\.with_value/.test(drillDlg));
check("Status kontrak selalu count", contractKpiCards({ active: 12, expiring: 3, expired: 5, items_active: 40 }).map((c) => c.value).join() === "12,3,5,40");

// 10. Responsive / rendering dasar
check("Tabel exception scroll horizontal di dalam card", /overflow-x-auto" data-testid="dash-price-exceptions-scroll"/.test(vcPanel));
check("Grid KPI SPK mobile-first 1 kolom", /grid grid-cols-1 gap-2\.5 sm:grid-cols-2/.test(spkPanel));
check("Grid kontrak: 1 kolom mobile, 5/7 di desktop", /xl:col-span-5/.test(dash) && /xl:col-span-7/.test(dash) && /grid gap-4 xl:grid-cols-12" data-testid="dash-contract-grid"/.test(dash));
check("Dialog drill tidak melebihi viewport mobile", /w-\[calc\(100vw-1\.5rem\)\]/.test(drillDlg) && /overflow-auto/.test(drillDlg));
check("Level SPK: < 80 Normal · 80–90 Perhatian · > 90 Kritis · > 100 Over", ["normal", "warning", "critical", "over"].every((k) => SPK_LEVEL[k]?.label));
check("Bar progress dipotong 0–100", barPct(140) === 100 && barPct(-5) === 0 && barPct(null) === 0 && barPct(55) === 55);
check("Persentase id-ID", pctText(92.35) === "92,4%" && pctText(null) === "–");
check("Tidak ada gradient / warna neon di panel baru", !/gradient|#00FF|#FF00|#0000FF/i.test(spkPanel + vcPanel + drillDlg));

console.log(`\n${n - fail}/${n} passed`);
process.exit(fail ? 1 : 0);
