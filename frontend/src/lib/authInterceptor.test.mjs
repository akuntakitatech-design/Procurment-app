// Node test: node frontend/src/lib/authInterceptor.test.mjs
// Perilaku interceptor auth bersama memakai axios asli + adapter palsu (tanpa jaringan, tanpa kredensial nyata).
import axios, { AxiosError } from "axios";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { installAuthInterceptors, canRefreshFor, classifyRefreshFailure, SESSION_REPLACED_DETAIL } from "./authInterceptor.js";
import { createLookupFetcher } from "./lookupCore.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, "..", p), "utf8");
let pass = 0, fail = 0;
const check = (name, cond, info = "") => { if (cond) { pass++; console.log("PASS " + name); } else { fail++; console.log("FAIL " + name + (info ? " — " + JSON.stringify(info) : "")); } };

const ROWS = { divisions: [{ id: "d1" }], warehouses: [{ id: "w1" }, { id: "w2" }], projects: [{ id: "p1" }], units: [{ id: "u1" }], items: [{ id: "i1" }], uoms: [{ id: "m1" }] };

/** Backend palsu. srv.valid = access token yang masih berlaku; srv.refresh = mode /auth/refresh. */
function makeEnv({ token = "old", valid = "fresh-1", refresh = "ok", refreshDelay = 0, batch = "ok" } = {}) {
  const srv = { valid, refresh, refreshCalls: 0, calls: [], issued: 1, batch };
  const store = { token };
  const ended = [];
  let cacheClears = 0;
  const reply = (config, status, data) => {
    const response = { status, statusText: String(status), data, headers: {}, config, request: {} };
    if (status >= 200 && status < 300) return response;
    throw new AxiosError(`HTTP ${status}`, status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST, config, {}, response);
  };
  const adapter = async (config) => {
    const url = String(config.url).split("?")[0];
    const auth = config.headers?.Authorization || config.headers?.get?.("Authorization");
    srv.calls.push(`${config.method.toUpperCase()} ${url}`);
    if (url === "/auth/refresh") {
      srv.refreshCalls += 1;
      if (refreshDelay) await new Promise((r) => setTimeout(r, refreshDelay));
      if (srv.refresh === "ok") { srv.issued += 1; srv.valid = `fresh-${srv.issued}`; return reply(config, 200, { ok: true, token: srv.valid }); }
      if (srv.refresh === "no_refresh") return reply(config, 401, { detail: "No refresh token" });
      if (srv.refresh === "expired") return reply(config, 401, { detail: "Session expired" });
      if (srv.refresh === "invalid") return reply(config, 401, { detail: "Invalid token" });
      if (srv.refresh === "replaced") return reply(config, 401, { detail: SESSION_REPLACED_DETAIL });
      if (srv.refresh === "500") return reply(config, 500, { detail: "Internal Server Error" });
      if (srv.refresh === "network") throw new AxiosError("Network Error", AxiosError.ERR_NETWORK, config, {});
    }
    if (url === "/auth/login") return reply(config, 401, { detail: "Email atau password salah" });
    if (url === "/auth/change-password") return reply(config, 401, { detail: "Password lama salah" });
    if (auth !== `Bearer ${srv.valid}`) return reply(config, 401, { detail: auth ? "Token expired" : "Not authenticated" });
    if (url === "/auth/me") return reply(config, 200, { id: "u1", name: "QA" });
    if (url === "/lookup-batch") {
      if (srv.batch === "404") return reply(config, 404, { detail: "Not Found" });
      if (srv.batch === "403") return reply(config, 403, { detail: "Forbidden" });
      const names = config.params.names.split(",");
      return reply(config, 200, { data: Object.fromEntries(names.map((n) => [n, ROWS[n] || []])), denied: [] });
    }
    if (url.startsWith("/lookup/")) return reply(config, 200, ROWS[url.slice(8)] || []);
    return reply(config, 200, { ok: true, url });
  };
  const api = axios.create({ baseURL: "", adapter });
  const deps = {
    getToken: () => store.token,
    setToken: (t) => { if (t) { if (t !== store.token) cacheClears += 1; store.token = t; } },
    clearToken: () => { cacheClears += 1; store.token = null; },
    clearLookupCache: () => { cacheClears += 1; },
    endSession: (reason, info) => ended.push({ reason, ...info }),
  };
  const st = installAuthInterceptors(api, deps);
  return { api, srv, store, ended, st, cacheClears: () => cacheClears };
}
const settle = (p) => p.then((r) => ({ ok: true, r }), (e) => ({ ok: false, e }));

// 1. Access token expired + refresh valid -> refresh sekali -> retry original -> sukses
{
  const env = makeEnv({ token: "expired" });
  const r = await settle(env.api.get("/transfers"));
  check("1. token expired + refresh valid: request asli sukses", r.ok && r.r.data.url === "/transfers");
  check("1. refresh dipanggil tepat sekali", env.srv.refreshCalls === 1);
  check("1. retry memakai token baru", env.store.token === env.srv.valid);
  check("1. sesi tidak diakhiri", env.ended.length === 0);
}

// 1b. Tanpa Bearer (Not authenticated) + refresh valid -> pulih
{
  const env = makeEnv({ token: null });
  const r = await settle(env.api.get("/lookup-batch", { params: { names: "divisions" } }));
  check("1b. Not authenticated + refresh valid -> pulih", r.ok && r.r.data.data.divisions.length === 1 && env.srv.refreshCalls === 1);
}

// 2/3. Refresh credential-invalid -> sesi frontend ditutup (token + cache dibersihkan, endSession)
for (const mode of ["no_refresh", "expired", "invalid"]) {
  const env = makeEnv({ token: "expired", refresh: mode });
  const r = await settle(env.api.get("/transfers"));
  check(`2. refresh ${mode}: request ditolak (bukan sukses palsu)`, !r.ok && r.e.response?.status === 401);
  check(`2. refresh ${mode}: token lokal dibersihkan`, env.store.token === null);
  check(`2. refresh ${mode}: cache lookup dibersihkan`, env.cacheClears() >= 1);
  check(`2. refresh ${mode}: endSession(session_expired, hadToken)`, env.ended.length === 1 && env.ended[0].reason === "session_expired" && env.ended[0].hadToken === true, env.ended);
  check(`2. refresh ${mode}: error ditandai sessionEnded`, r.e?.sessionEnded === true);
}

// 4. Refresh session_replaced -> flow session_replaced existing
{
  const env = makeEnv({ token: "expired", refresh: "replaced" });
  const r = await settle(env.api.get("/transfers"));
  check("4. refresh session_replaced: endSession(session_replaced)", env.ended.length === 1 && env.ended[0].reason === "session_replaced");
  check("4. refresh session_replaced: token dibersihkan", env.store.token === null && !r.ok);
}
// 4b. Request biasa 401 session_replaced -> langsung akhiri sesi, tanpa refresh
{
  const env = makeEnv({ token: "old" });
  env.api.interceptors.request.use((c) => c); // no-op
  env.srv.valid = "never";
  const api2 = env.api;
  // paksa backend menjawab session_replaced
  const r = await settle(api2.get("/x", { adapter: async (config) => { throw new AxiosError("401", "ERR_BAD_REQUEST", config, {}, { status: 401, data: { detail: SESSION_REPLACED_DETAIL }, headers: {}, config }); } }));
  check("4b. 401 session_replaced pada request -> tanpa refresh, sesi diakhiri", !r.ok && env.srv.refreshCalls === 0 && env.ended[0]?.reason === "session_replaced");
}

// 5/6. Refresh 500 / network -> tidak logout, error transient dipropagasi
for (const mode of ["500", "network"]) {
  const env = makeEnv({ token: "expired", refresh: mode });
  const r = await settle(env.api.get("/transfers"));
  check(`5/6. refresh ${mode}: tidak logout (token tetap)`, env.store.token === "expired" && env.ended.length === 0);
  check(`5/6. refresh ${mode}: error transient dipropagasi`, !r.ok && r.e?.isAuthTransient === true);
  env.srv.refresh = "ok";
  const again = await settle(env.api.get("/transfers"));
  check(`5/6. refresh ${mode}: request berikutnya boleh mencoba refresh lagi & pulih`, again.ok && env.srv.refreshCalls === 2);
}

// 7. Beberapa 401 bersamaan -> hanya satu refresh, semua menunggu hasil yang sama
{
  const env = makeEnv({ token: "expired", refreshDelay: 30 });
  const rs = await Promise.all(["/a", "/b", "/c", "/lookup-batch"].map((u) => settle(env.api.get(u, u === "/lookup-batch" ? { params: { names: "items" } } : undefined))));
  check("7. 4 request 401 bersamaan -> semua sukses", rs.every((x) => x.ok));
  check("7. hanya SATU refresh request", env.srv.refreshCalls === 1, env.srv.refreshCalls);
}
// 7b. Concurrent 401 + refresh invalid -> satu refresh, satu redirect ber-pesan
{
  const env = makeEnv({ token: "expired", refresh: "no_refresh", refreshDelay: 20 });
  const rs = await Promise.all(["/a", "/b", "/c"].map((u) => settle(env.api.get(u))));
  check("7b. concurrent + refresh invalid: satu refresh", env.srv.refreshCalls === 1 && rs.every((x) => !x.ok));
  check("7b. hanya pemanggil pertama hadToken=true (tanpa redirect ganda)", env.ended.filter((e) => e.hadToken).length === 1, env.ended);
}
// 7c. 401 terlambat setelah token sudah diperbarui -> retry tanpa refresh baru
{
  const env = makeEnv({ token: "expired" });
  await env.api.get("/warmup"); // refresh #1
  const late = await settle(env.api.get("/late", { adapter: undefined }));
  check("7c. token sudah segar -> tidak ada refresh tambahan", late.ok && env.srv.refreshCalls === 1);
}

// 8. Setelah refresh credential-invalid: tidak ada kondisi "masih login tapi terus 401"
{
  const env = makeEnv({ token: "expired", refresh: "no_refresh" });
  await settle(env.api.get("/transfers"));
  const before = env.srv.refreshCalls;
  await settle(env.api.get("/loans"));
  check("8. sesi diakhiri sekali saat kredensial invalid (frontend anonim, token null)", env.ended[0]?.reason === "session_expired" && env.store.token === null);
  check("8. request berikutnya tanpa token -> refresh dicoba lagi tanpa loop (maks 1 per request)", env.srv.refreshCalls === before + 1);
  check("8. request berikutnya: endSession hadToken=false (tanpa redirect ulang)", env.ended[1]?.hadToken === false);
}

// Startup /auth/me
{
  const env = makeEnv({ token: "fresh-1" });
  const r = await settle(env.api.get("/auth/me"));
  check("S1. startup token valid: /auth/me sukses tanpa refresh", r.ok && env.srv.refreshCalls === 0);
}
{
  const env = makeEnv({ token: "expired" });
  const r = await settle(env.api.get("/auth/me"));
  check("S2. startup token expired + refresh valid: refresh sekali + /auth/me retry sukses", r.ok && r.r.data.id === "u1" && env.srv.refreshCalls === 1 &&
    env.srv.calls.join("|") === "GET /auth/me|POST /auth/refresh|GET /auth/me", env.srv.calls);
}
{
  const env = makeEnv({ token: null });
  const r = await settle(env.api.get("/auth/me"));
  check("S3. startup tanpa access token + refresh cookie valid: pulih", r.ok && env.srv.refreshCalls === 1);
}
{
  const env = makeEnv({ token: "expired", refresh: "expired" });
  const r = await settle(env.api.get("/auth/me"));
  check("S4. startup refresh expired: anonim bersih (401, token null, session_expired)", !r.ok && r.e.response.status === 401 && env.store.token === null && env.ended[0]?.reason === "session_expired");
}
{
  const env = makeEnv({ token: null, refresh: "no_refresh" });
  await settle(env.api.get("/auth/me"));
  check("S4b. pengunjung pertama (tanpa token): endSession hadToken=false -> tanpa pesan sesi berakhir", env.ended[0]?.hadToken === false);
}
{
  const env = makeEnv({ token: "expired", refresh: "replaced" });
  await settle(env.api.get("/auth/me"));
  check("S5. startup session_replaced: flow session_replaced", env.ended[0]?.reason === "session_replaced");
}
{
  const env = makeEnv({ token: "expired", refresh: "500" });
  const r = await settle(env.api.get("/auth/me"));
  check("S6. startup refresh 500: error transient (bukan anonim permanen)", !r.ok && r.e.isAuthTransient === true && env.ended.length === 0 && env.store.token === "expired");
}
{
  const env = makeEnv({ token: "expired", refresh: "ok" });
  env.srv.refresh = "ok";
  // backend selalu menolak /auth/me walau refresh sukses -> harus berhenti (tanpa loop)
  const r = await settle(env.api.get("/auth/me", { adapter: async (config) => { env.srv.calls.push("ME"); throw new AxiosError("401", "ERR_BAD_REQUEST", config, {}, { status: 401, data: { detail: "Token expired" }, headers: {}, config }); } }));
  check("S7. tidak ada infinite refresh loop (/auth/me selalu 401 -> berhenti)", !r.ok && env.srv.refreshCalls === 1 && env.srv.calls.filter((c) => c === "ME").length === 2, env.srv.calls);
}

// Endpoint kredensial tidak memicu refresh
{
  const env = makeEnv({ token: "fresh-1" });
  await settle(env.api.post("/auth/login", {}));
  await settle(env.api.post("/auth/change-password", {}));
  check("Login/ganti password 401 tidak memicu refresh/logout", env.srv.refreshCalls === 0 && env.ended.length === 0 && env.store.token === "fresh-1");
}
check("canRefreshFor rules", canRefreshFor({ url: "/auth/me" }) && !canRefreshFor({ url: "/auth/refresh" }) && !canRefreshFor({ url: "/auth/login" }) &&
  !canRefreshFor({ url: "/auth/logout" }) && canRefreshFor({ url: "/lookup-batch?names=x" }) && canRefreshFor({ url: "/lookup/items" }));
check("classifyRefreshFailure", classifyRefreshFailure({ response: { status: 401, data: { detail: "No refresh token" } } }) === "invalid" &&
  classifyRefreshFailure({ response: { status: 401, data: { detail: SESSION_REPLACED_DETAIL } } }) === "replaced" &&
  classifyRefreshFailure({ response: { status: 502 } }) === "transient" && classifyRefreshFailure({ code: "ERR_NETWORK" }) === "transient");

// Integrasi lookup + auth (shared): batch 401 + refresh -> retry -> data, tanpa fallback
{
  const env = makeEnv({ token: "expired" });
  const cache = new Map(), inflight = new Map();
  const fetchLookups = createLookupFetcher({ get: (u, c) => env.api.get(u, c), cache, inflight, ttl: 60000 });
  const out = await fetchLookups(["divisions", "warehouses", "projects", "units", "items", "uoms"]);
  check("L3. batch 401 + refresh berhasil -> refresh dipanggil", env.srv.refreshCalls === 1);
  check("L3. request batch asli di-retry -> data terisi", out.data.warehouses.length === 2 && out.status.items.state === "ready");
  check("L3. fallback individual TIDAK dijalankan", !env.srv.calls.some((c) => c.startsWith("GET /lookup/")), env.srv.calls);
}
{
  const env = makeEnv({ token: "expired", refresh: "no_refresh" });
  const cache = new Map(), inflight = new Map();
  const fetchLookups = createLookupFetcher({ get: (u, c) => env.api.get(u, c), cache, inflight, ttl: 60000 });
  const out = await fetchLookups(["divisions", "warehouses"]);
  check("L4. batch 401 + refresh gagal -> status auth, bukan []", out.status.warehouses.state === "auth" && !("warehouses" in out.data));
  check("L4. tidak fallback & tidak cache []", !env.srv.calls.some((c) => c.startsWith("GET /lookup/")) && cache.size === 0);
  check("L4. sesi frontend diakhiri (session_expired)", env.ended[0]?.reason === "session_expired");
}
{
  const env = makeEnv({ token: "fresh-1", batch: "404" });
  const fetchLookups = createLookupFetcher({ get: (u, c) => env.api.get(u, c), cache: new Map(), inflight: new Map(), ttl: 60000 });
  const out = await fetchLookups(["divisions", "warehouses"]);
  check("L2. batch 404 -> fallback individual via axios", out.data.warehouses.length === 2 && env.srv.calls.filter((c) => c.startsWith("GET /lookup/")).length === 2);
}
{
  const env = makeEnv({ token: "fresh-1", batch: "403" });
  const cache = new Map();
  const fetchLookups = createLookupFetcher({ get: (u, c) => env.api.get(u, c), cache, inflight: new Map(), ttl: 60000 });
  const out = await fetchLookups(["warehouses"]);
  check("L5. batch 403 -> denied tetap terlihat, tanpa fallback/cache", out.status.warehouses.state === "denied" && cache.size === 0 && env.srv.calls.length === 1);
}

// Wiring sumber
const apiSrc = src("lib/api.js"), ctx = src("context/AuthContext.js"), app = src("App.js"), login = src("pages/Login.jsx");
check("api.js memakai installAuthInterceptors + withCredentials", apiSrc.includes("installAuthInterceptors(api,") && apiSrc.includes("withCredentials: true"));
check("api.js: tidak mengimpor AuthContext (tanpa circular)", !apiSrc.includes("AuthContext"));
check("AuthContext: subscribe onSessionEnd -> setUser(false)", ctx.includes("onSessionEnd(() => { setUser(false); setSubscription(false); })"));
check("AuthContext: transient bootstrap tidak dianggap anonim", ctx.includes("e?.isAuthTransient || !e?.response || s >= 500") && ctx.includes("setAuthError("));
check("App: layar coba lagi untuk gangguan pemulihan sesi", app.includes('data-testid="auth-bootstrap-retry"'));
check("Login: pesan session_expired", login.includes('params.get("reason") === "session_expired"') && login.includes('data-testid="login-session-expired"'));
const be = readFileSync(join(here, "..", "..", "..", "backend", "server.py"), "utf8");
check("Backend /auth/refresh: cookie params mengikuti request (Secure/SameSite konsisten dgn login)", /A\.create_refresh_token\(u\["id"\], u\.get\("token_version", 0\)\), request\)/.test(be));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
