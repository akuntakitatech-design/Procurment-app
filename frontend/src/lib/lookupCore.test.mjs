// Node test (no deps): node frontend/src/lib/lookupCore.test.mjs
// Regression shared lookup layer: error tidak boleh menjadi [] dan tidak boleh di-cache.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createLookupFetcher, classifyLookupError, isLookupFailure, LOOKUP_MESSAGES } from "./lookupCore.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, "..", p), "utf8");
let pass = 0, fail = 0;
const check = (name, cond, info = "") => { if (cond) { pass++; console.log("PASS " + name); } else { fail++; console.log("FAIL " + name + (info ? " — " + JSON.stringify(info) : "")); } };

const STOCK = ["divisions", "contacts", "warehouses", "projects", "units", "items", "uoms", "item_categories"];
const ROWS = { divisions: [{ id: "d1", name: "Teknik" }], contacts: [], warehouses: [{ id: "w1", name: "A" }, { id: "w2", name: "B" }],
  projects: [{ id: "p1", name: "P" }], units: [{ id: "u1", name: "EX01" }], items: [{ id: "i1", name: "Baut" }], uoms: [{ id: "m1", name: "PCS" }], item_categories: [{ id: "c1", name: "Umum" }] };
const httpErr = (status, detail) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });
const netErr = () => Object.assign(new Error("Network Error"), { code: "ERR_NETWORK" });

function setup(handler) {
  const calls = [];
  const cache = new Map(), inflight = new Map(), meta = { gen: 0 };
  let clock = 1000;
  const get = async (url, cfg) => { calls.push(url + (cfg?.params?.names ? `?${cfg.params.names}` : "")); return handler(url, cfg, calls); };
  const fetchLookups = createLookupFetcher({ get, cache, inflight, ttl: 60000, meta, now: () => clock });
  return { fetchLookups, calls, cache, inflight, meta, tick: (ms) => { clock += ms; } };
}
const batchOk = (denied = []) => (url, cfg) => {
  if (url !== "/lookup-batch") throw new Error("unexpected individual call " + url);
  const names = cfg.params.names.split(",");
  return { status: 200, data: { data: Object.fromEntries(names.filter((n) => !denied.includes(n)).map((n) => [n, ROWS[n]])), denied } };
};

// 1. batch 200 -> data terisi + cache terisi benar
{
  const t = setup(batchOk());
  const out = await t.fetchLookups(STOCK);
  check("1. batch 200: satu request /lookup-batch", t.calls.length === 1 && t.calls[0].startsWith("/lookup-batch"), t.calls);
  check("1. batch 200: data terisi", out.data.warehouses.length === 2 && out.data.items.length === 1 && out.data.divisions.length === 1);
  check("1. batch 200: status ready semua", STOCK.every((n) => out.status[n].state === "ready"));
  check("1. batch 200: cache berisi data asli", t.cache.get("warehouses").data.length === 2 && t.cache.size === STOCK.length);
  const again = await t.fetchLookups(STOCK);
  check("1. batch 200: request kedua memakai cache (tanpa request)", t.calls.length === 1 && again.data.uoms.length === 1);
}

// 2. batch 404 -> fallback /lookup/{name}
{
  const t = setup((url) => {
    if (url === "/lookup-batch") throw httpErr(404, "Not Found");
    const n = url.replace("/lookup/", ""); return { status: 200, data: ROWS[n] };
  });
  const out = await t.fetchLookups(STOCK);
  check("2. batch 404: fallback individual dipanggil untuk tiap nama", t.calls.filter((c) => c.startsWith("/lookup/")).length === STOCK.length, t.calls);
  check("2. batch 404: data terisi dari individual", out.data.warehouses.length === 2 && out.data.projects.length === 1);
  check("2. batch 404: status ready & cache terisi", STOCK.every((n) => out.status[n].state === "ready") && t.cache.get("items").data.length === 1);
}

// 3/4. batch 401 (setelah interceptor gagal refresh) -> tidak fallback, tidak [] di cache
{
  const t = setup((url) => { if (url === "/lookup-batch") throw httpErr(401, "Token expired"); throw new Error("fallback should not run"); });
  const out = await t.fetchLookups(STOCK);
  check("4. batch 401: fallback individual TIDAK dijalankan", t.calls.length === 1, t.calls);
  check("4. batch 401: status auth (bukan ready/empty)", STOCK.every((n) => out.status[n].state === "auth"), out.status);
  check("4. batch 401: tidak ada data [] palsu", Object.keys(out.data).length === 0, out.data);
  check("4. batch 401: cache tetap kosong", t.cache.size === 0);
}

// 5. batch 403 -> denied, tidak fallback, tidak cache
{
  const t = setup((url) => { if (url === "/lookup-batch") throw httpErr(403, "Forbidden"); throw new Error("fallback should not run"); });
  const out = await t.fetchLookups(["warehouses", "items"]);
  check("5. batch 403: tidak fallback", t.calls.length === 1);
  check("5. batch 403: status denied + pesan izin", out.status.warehouses.state === "denied" && out.status.items.message === LOOKUP_MESSAGES.denied);
  check("5. batch 403: tidak cache []", t.cache.size === 0 && !("warehouses" in out.data));
}

// 6. batch 5xx / network -> error jujur, tidak fallback, tidak cache
for (const [label, err] of [["500", httpErr(500, "Internal Server Error")], ["502", httpErr(502, "Bad Gateway")], ["network", netErr()]]) {
  const t = setup((url) => { if (url === "/lookup-batch") throw err; throw new Error("fallback should not run"); });
  const out = await t.fetchLookups(["divisions", "warehouses"]);
  check(`6. batch ${label}: tidak fallback`, t.calls.length === 1, t.calls);
  check(`6. batch ${label}: status error + pesan "Gagal memuat data referensi. Coba muat ulang."`,
    out.status.divisions.state === "error" && out.status.warehouses.message === "Gagal memuat data referensi. Coba muat ulang.");
  check(`6. batch ${label}: tidak cache []`, t.cache.size === 0 && Object.keys(out.data).length === 0);
}

// 7. individual lookup gagal (setelah 404 batch) -> tidak cache [], status per nama jujur
{
  const t = setup((url) => {
    if (url === "/lookup-batch") throw httpErr(404, "Not Found");
    if (url === "/lookup/warehouses") throw httpErr(401, "Not authenticated");
    if (url === "/lookup/items") throw httpErr(403, "Anda tidak memiliki izin");
    if (url === "/lookup/uoms") throw httpErr(500, "boom");
    return { status: 200, data: ROWS[url.replace("/lookup/", "")] };
  });
  const out = await t.fetchLookups(["divisions", "warehouses", "items", "uoms"]);
  check("7. individual 401: status auth, tidak []", out.status.warehouses.state === "auth" && !("warehouses" in out.data));
  check("7. individual 403: status denied", out.status.items.state === "denied" && !("items" in out.data));
  check("7. individual 500: status error", out.status.uoms.state === "error" && !("uoms" in out.data));
  check("7. individual sukses tetap dipakai (partial)", out.status.divisions.state === "ready" && out.data.divisions.length === 1);
  check("7. hanya hasil 200 yang masuk cache", t.cache.size === 1 && t.cache.has("divisions"));
}

// 8. request gagal lalu berikutnya berhasil -> cache terisi data sebenarnya
{
  let failNext = true;
  const t = setup((url, cfg) => { if (failNext) { failNext = false; throw httpErr(503, "unavailable"); } return batchOk()(url, cfg); });
  const first = await t.fetchLookups(["warehouses", "items"]);
  check("8. percobaan pertama gagal -> error, cache kosong", first.status.warehouses.state === "error" && t.cache.size === 0);
  const second = await t.fetchLookups(["warehouses", "items"]);
  check("8. percobaan kedua langsung request ulang (error tidak di-cache)", t.calls.length === 2, t.calls);
  check("8. percobaan kedua berhasil -> data & cache terisi", second.status.warehouses.state === "ready" && second.data.warehouses.length === 2 && t.cache.get("items").data.length === 1);
}

// 9. Error tidak menimpa cache valid lama
{
  let mode = "ok";
  const t = setup((url, cfg) => { if (mode === "fail") throw httpErr(500, "x"); return batchOk()(url, cfg); });
  await t.fetchLookups(["warehouses"]);
  mode = "fail"; t.tick(61000); // cache basi -> request ulang -> gagal
  const out = await t.fetchLookups(["warehouses"]);
  check("9. error: cache valid lama tidak ditimpa []", t.cache.get("warehouses").data.length === 2);
  check("9. error: data lama tetap tersedia + status error terlihat", out.data.warehouses.length === 2 && out.status.warehouses.state === "error");
}

// 10. denied parsial pada batch 200
{
  const t = setup(batchOk(["warehouses", "items"]));
  const out = await t.fetchLookups(["divisions", "projects", "warehouses", "items"]);
  check("10.1 batch 200 + denied parsial: allowed tetap terisi", out.status.divisions.state === "ready" && out.data.projects.length === 1);
  check("10.2 denied -> status denied + pesan izin (bukan empty)", out.status.warehouses.state === "denied" && out.status.items.message === LOOKUP_MESSAGES.denied);
  check("10.3 denied tidak memicu fallback individual", t.calls.length === 1, t.calls);
  check("10.4 denied tidak menulis [] ke cache", !t.cache.has("warehouses") && !t.cache.has("items") && t.cache.has("divisions"));
  check("10.4 denied tidak ada di data", !("warehouses" in out.data) && !("items" in out.data));
  const again = await t.fetchLookups(["divisions", "projects", "warehouses", "items"]);
  check("10.5 reload berikutnya: denied diminta ulang & tetap denied (bukan valid-empty)", t.calls.length === 2 && t.calls[1] === "/lookup-batch?items,warehouses" && again.status.warehouses.state === "denied", t.calls);
}

// 11. HTTP 200 + [] = valid empty (berbeda dari denied)
{
  const t = setup(() => ({ status: 200, data: { data: { contacts: [], warehouses: [] }, denied: ["items"] } }));
  const out = await t.fetchLookups(["contacts", "warehouses", "items"]);
  check("11. 200 + [] -> ready dengan array kosong (UI: Belum ada data)", out.status.contacts.state === "ready" && Array.isArray(out.data.contacts) && out.data.contacts.length === 0);
  check("11. valid-empty di-cache, denied tidak", t.cache.has("contacts") && t.cache.get("warehouses").data.length === 0 && !t.cache.has("items"));
  check("11. valid-empty != denied", out.status.warehouses.state !== out.status.items.state && out.status.items.state === "denied");
}

// 12. Respons batch tidak valid / nama hilang -> error, bukan []
{
  const t = setup(() => ({ status: 200, data: { data: { divisions: ROWS.divisions } } }));
  const out = await t.fetchLookups(["divisions", "warehouses"]);
  check("12. nama tidak ada di respons batch -> error (bukan [])", out.status.warehouses.state === "error" && !t.cache.has("warehouses"));
  const t2 = setup(() => ({ status: 200, data: "<html>" }));
  const out2 = await t2.fetchLookups(["divisions"]);
  check("12. respons batch bukan JSON objek -> error, tanpa fallback", out2.status.divisions.state === "error" && t2.calls.length === 1);
}

// 13. In-flight dedupe + generation guard (logout/ganti token saat request berjalan)
{
  let release; const gate = new Promise((r) => { release = r; });
  const t = setup(async (url, cfg) => { await gate; return batchOk()(url, cfg); });
  const a = t.fetchLookups(["warehouses"]); const b = t.fetchLookups(["warehouses"]);
  t.meta.gen += 1; t.cache.clear(); // clearLookupCache() saat request berjalan
  release(); const [ra, rb] = await Promise.all([a, b]);
  check("13. dua pemanggil bersamaan -> satu request", t.calls.length === 1);
  check("13. hasil tetap dikembalikan ke pemanggil", ra.data.warehouses.length === 2 && rb.status.warehouses.state === "ready");
  check("13. hasil generasi lama tidak ditulis ke cache baru", !t.cache.has("warehouses"));
}

// 14. force reload satu nama
{
  const t = setup(batchOk());
  await t.fetchLookups(["warehouses", "items"]);
  await t.fetchLookups(["warehouses"], true);
  check("14. force: request ulang meskipun cache segar", t.calls.length === 2 && t.calls[1] === "/lookup-batch?warehouses");
}

// Klasifikasi
check("classify 401 -> auth", classifyLookupError(httpErr(401)).state === "auth");
check("classify 403 -> denied", classifyLookupError(httpErr(403)).state === "denied");
check("classify 500/network -> error", classifyLookupError(httpErr(500)).state === "error" && classifyLookupError(netErr()).state === "error");
check("isLookupFailure", isLookupFailure({ state: "denied" }) && !isLookupFailure({ state: "ready" }) && !isLookupFailure({ state: "loading" }));

// Wiring sumber (shared): pola lama yang menelan error sudah tidak ada
const um = src("hooks/useMasters.js");
check("useMasters: tidak ada .catch(() => ({ data: [] }))", !/catch\(\(\) => \(\{ data: \[\] \}\)\)/.test(um));
check("useMasters: memakai createLookupFetcher bersama", um.includes("createLookupFetcher(") && um.includes("lookupMeta"));
check("useMasters: STOCK_REFS tetap sama", um.includes('export const STOCK_REFS = ["divisions", "contacts", "warehouses", "projects", "units", "items", "uoms", "item_categories"];'));
check("useMasters: expose status/errors/retry", /return \{ data, opts, map, reload: load, upsert, status: lookupState, errors, loading, retry \}/.test(um));
const cb = src("components/Combobox.jsx");
check("Combobox: state loading/error/izin/empty jujur", cb.includes("LOOKUP_MESSAGES.loading") && cb.includes("LOOKUP_MESSAGES.empty") && cb.includes("list.__lookup") && cb.includes('"Tidak ada izin"'));
for (const [page, tid] of [["Transfer", "trf"], ["Loan", "loan"], ["Adjustment", "adj"], ["Opname", "opn"]]) {
  const s = src(`pages/${page}.jsx`);
  check(`${page}: tetap memakai useMasters(STOCK_REFS) bersama + LookupStatusAlert`, s.includes("STOCK_REFS") && s.includes(`testid="${tid}-lookup-status"`));
}
const store = src("lib/lookupStore.js");
check("lookupStore: clearLookupCache menaikkan generasi", store.includes("lookupMeta.gen += 1"));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
