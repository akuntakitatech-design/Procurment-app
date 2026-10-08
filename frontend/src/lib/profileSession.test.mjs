// Node test (no deps): node frontend/src/lib/profileSession.test.mjs
// Integrasi frontend Profil Saya + Satu Sesi Aktif (pemeriksaan sumber, tanpa bundler).
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(join(here, "..", p), "utf8");
let pass = 0, fail = 0;
const t = (name, cond) => { if (cond) { pass += 1; console.log("PASS " + name); } else { fail += 1; console.log("FAIL " + name); } };

// Alur interceptor dipindah ke lib/authInterceptor.js (diuji perilakunya di authInterceptor.test.mjs).
const api = src("lib/api.js");
const ai = src("lib/authInterceptor.js");
t("api: deteksi pesan 401 sesi digantikan (sama dengan backend)", ai.includes('"Sesi Anda telah berakhir karena akun ini login di perangkat lain."'));
t("api: hapus token lokal saat sesi berakhir", /const terminate = \(reason\) => \{[\s\S]*?clearToken\(\);/.test(ai));
t("api: redirect ke /login?reason=<alasan sesi>", api.includes("window.location.assign(`/login?reason=${reason}`)") && ai.includes('SESSION_REPLACED_REASON = "session_replaced"'));
t("api: tidak loop redirect di halaman login", api.includes('window.location.pathname === "/login"'));
t("api: deteksi diperiksa sebelum auto refresh", ai.indexOf("isSessionReplaced(error) && !skipsSessionReplaced") < ai.indexOf("await refreshOnce()"));
const login = src("pages/Login.jsx");
t("Login: pesan Bahasa Indonesia sesi berakhir", login.includes("Sesi Anda berakhir karena akun ini telah digunakan untuk login di perangkat lain.") && login.includes('params.get("reason") === "session_replaced"'));
const app = src("App.js");
t("Route /profile terlindungi", app.includes('<Route path="/profile" element={<Protected><Profile /></Protected>} />'));
const layout = src("components/Layout.jsx");
t("Header: menu Profil Saya", layout.includes('data-testid="user-menu-profile"') && layout.includes("Profil Saya") && layout.includes('nav("/profile")'));
t("Header: tombol logout lama tetap ada", layout.includes('data-testid="logout-btn"'));
const prof = src("pages/Profile.jsx");
t("Profil: section Informasi Profil & Keamanan", prof.includes("Informasi Profil") && prof.includes("Keamanan / Ubah Password"));
t("Profil: hanya nama/email/telepon dikirim", prof.includes('["name", "email", "phone"].forEach'));
t("Profil: role tidak editable", !/profile-role[^>]*<Input/.test(prof) && !prof.includes('body.role'));
t("Profil: form password 3 field", ["profile-pw-current", "profile-pw-new", "profile-pw-confirm"].every((x) => prof.includes(x)));
t("Profil: token sesi baru disimpan setelah ganti password", prof.includes("replaceSessionToken(r.data?.token)"));
t("Profil: validasi konfirmasi Bahasa Indonesia", prof.includes("Konfirmasi password baru tidak sama."));

console.log(`\n${pass}/${pass + fail} passed`);
process.exit(fail ? 1 : 0);
