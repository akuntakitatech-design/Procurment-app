import axios from "axios";
import { clearLookupCache } from "@/lib/lookupStore";
import { installAuthInterceptors, isSessionReplaced, SESSION_EXPIRED_REASON, SESSION_REPLACED_DETAIL, SESSION_REPLACED_REASON } from "@/lib/authInterceptor";

// In production the frontend nginx proxies /api to the backend container.
// A custom backend URL can still be supplied at build time when needed.
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, withCredentials: true });

export const getToken = () => localStorage.getItem("pf_token");
export const setToken = (t) => { if (t) { if (t !== getToken()) clearLookupCache(); localStorage.setItem("pf_token", t); } };
export const clearToken = () => { clearLookupCache(); localStorage.removeItem("pf_token"); };

// Satu sesi aktif per user: backend menolak token sesi lama dengan pesan ini.
export { SESSION_REPLACED_DETAIL, SESSION_REPLACED_REASON, SESSION_EXPIRED_REASON, isSessionReplaced };

// Pendengar akhir sesi (context auth berlangganan via onSessionEnd) — tanpa circular import.
const sessionListeners = new Set();
export const onSessionEnd = (fn) => { sessionListeners.add(fn); return () => sessionListeners.delete(fn); };

let redirecting = false;
function endSession(reason, { hadToken } = {}) {
  sessionListeners.forEach((fn) => { try { fn(reason); } catch { /* listener error tidak boleh memutus alur sesi */ } });
  if (redirecting || typeof window === "undefined") return;
  // Pengunjung tanpa sesi sebelumnya (mis. halaman publik / pertama kali buka) tidak perlu pesan "sesi berakhir".
  if (reason === SESSION_EXPIRED_REASON && !hadToken) return;
  if (window.location.pathname === "/login") return; // sudah di halaman login -> tidak redirect (hindari loop)
  redirecting = true;
  window.location.assign(`/login?reason=${reason}`);
}

installAuthInterceptors(api, { getToken, setToken, clearToken, clearLookupCache, endSession });

export function apiError(detail) {
  if (detail == null) return "Terjadi kesalahan. Coba lagi.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => e?.msg || JSON.stringify(e)).join(" ");
  if (detail?.msg) return detail.msg;
  return String(detail);
}

export default api;
