import axios from "axios";
import { clearLookupCache } from "@/lib/lookupStore";

// In production the frontend nginx proxies /api to the backend container.
// A custom backend URL can still be supplied at build time when needed.
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, withCredentials: true });

export const getToken = () => localStorage.getItem("pf_token");
export const setToken = (t) => { if (t) { if (t !== getToken()) clearLookupCache(); localStorage.setItem("pf_token", t); } };
export const clearToken = () => { clearLookupCache(); localStorage.removeItem("pf_token"); };

api.interceptors.request.use((config) => {
  const t = getToken();
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

// Satu sesi aktif per user: backend menolak token sesi lama dengan pesan ini.
export const SESSION_REPLACED_DETAIL = "Sesi Anda telah berakhir karena akun ini login di perangkat lain.";
export const SESSION_REPLACED_REASON = "session_replaced";
export function isSessionReplaced(error) {
  return error?.response?.status === 401 && error?.response?.data?.detail === SESSION_REPLACED_DETAIL;
}
let redirecting = false;
function endReplacedSession() {
  clearToken();
  if (redirecting || typeof window === "undefined") return;
  if (window.location.pathname === "/login" && window.location.search.includes(SESSION_REPLACED_REASON)) return;
  redirecting = true;
  window.location.assign(`/login?reason=${SESSION_REPLACED_REASON}`);
}

let refreshing = null;
api.interceptors.response.use(
  (r) => { if (String(r.config?.method || "get").toLowerCase() !== "get") clearLookupCache(); return r; },
  async (error) => {
    const orig = error.config || {};
    if (isSessionReplaced(error) && !String(orig.url || "").includes("/auth/login") && !String(orig.url || "").includes("/auth/logout")) {
      endReplacedSession();
      return Promise.reject(error);
    }
    if (error.response?.status === 401 && !orig._retry && !String(orig.url || "").includes("/auth/")) {
      orig._retry = true;
      try {
        refreshing = refreshing || api.post("/auth/refresh");
        const res = await refreshing;
        refreshing = null;
        if (res?.data?.token) setToken(res.data.token);
        return api(orig);
      } catch (e) {
        refreshing = null;
        if (isSessionReplaced(e)) { endReplacedSession(); return Promise.reject(e); }
      }
    }
    return Promise.reject(error);
  }
);

export function apiError(detail) {
  if (detail == null) return "Terjadi kesalahan. Coba lagi.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => e?.msg || JSON.stringify(e)).join(" ");
  if (detail?.msg) return detail.msg;
  return String(detail);
}

export default api;
