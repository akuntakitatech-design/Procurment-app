import axios from "axios";

// In production the frontend nginx proxies /api to the backend container.
// A custom backend URL can still be supplied at build time when needed.
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
export const API = `${BACKEND_URL}/api`;

const api = axios.create({ baseURL: API, withCredentials: true });

export const getToken = () => localStorage.getItem("pf_token");
export const setToken = (t) => { if (t) localStorage.setItem("pf_token", t); };
export const clearToken = () => localStorage.removeItem("pf_token");

api.interceptors.request.use((config) => {
  const t = getToken();
  if (t) config.headers.Authorization = `Bearer ${t}`;
  return config;
});

let refreshing = null;
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const orig = error.config;
    if (error.response?.status === 401 && !orig._retry && !orig.url.includes("/auth/")) {
      orig._retry = true;
      try {
        refreshing = refreshing || api.post("/auth/refresh");
        const res = await refreshing;
        refreshing = null;
        if (res?.data?.token) setToken(res.data.token);
        return api(orig);
      } catch (e) {
        refreshing = null;
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
