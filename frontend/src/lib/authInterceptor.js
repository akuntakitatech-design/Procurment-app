// Alur auth bersama axios (murni, tanpa alias "@/" agar bisa diuji di Node).
// - Bearer token dari storage dipasang pada setiap request (cookie access_token tetap dikirim via withCredentials).
// - 401 -> SATU refresh in-flight (POST /auth/refresh) -> retry request asli.
//   /auth/me BOLEH memicu refresh (bootstrap sesi); /auth/refresh, /auth/login, /auth/logout, /auth/register,
//   /auth/change-password TIDAK (hindari loop / ubah perilaku endpoint kredensial).
// - Refresh gagal:
//     session_replaced  -> alur existing (akhiri sesi, reason=session_replaced)
//     kredensial invalid (401/403: No refresh token / Session expired / Invalid token ...) -> akhiri sesi frontend
//                          (token + cache dibersihkan, AuthContext -> anonim, reason=session_expired)
//     5xx / network     -> gangguan sementara: JANGAN logout, error refresh dipropagasi (isAuthTransient)
export const SESSION_REPLACED_DETAIL = "Sesi Anda telah berakhir karena akun ini login di perangkat lain.";
export const SESSION_REPLACED_REASON = "session_replaced";
export const SESSION_EXPIRED_REASON = "session_expired";

export function isSessionReplaced(error) {
  return error?.response?.status === 401 && error?.response?.data?.detail === SESSION_REPLACED_DETAIL;
}

/** "replaced" | "invalid" | "transient" */
export function classifyRefreshFailure(error) {
  if (isSessionReplaced(error)) return "replaced";
  const s = error?.response?.status;
  if (s === 401 || s === 403) return "invalid";
  return "transient";
}

const pathOf = (cfg) => String(cfg?.url || "").split("?")[0];
const NO_REFRESH = ["/auth/refresh", "/auth/login", "/auth/logout", "/auth/register", "/auth/change-password"];
export function canRefreshFor(cfg) {
  const p = pathOf(cfg);
  if (NO_REFRESH.some((x) => p.includes(x))) return false;
  if (p.includes("/auth/")) return p.endsWith("/auth/me");
  return true;
}
// /auth/refresh ditangani oleh pemanggil refreshOnce (sekali), /auth/login & /auth/logout tidak mengakhiri sesi lain.
const skipsSessionReplaced = (cfg) => { const p = pathOf(cfg); return p.includes("/auth/login") || p.includes("/auth/logout") || p.includes("/auth/refresh"); };

/**
 * deps: { getToken, setToken, clearToken, clearLookupCache, endSession(reason, { hadToken }) }
 * endSession dipanggil SETELAH token & cache dibersihkan; bertanggung jawab atas notifikasi AuthContext + redirect.
 */
export function installAuthInterceptors(api, deps) {
  const { getToken, setToken, clearToken, clearLookupCache = () => {}, endSession = () => {} } = deps;
  let refreshing = null;
  const state = { refreshCount: 0 };

  const terminate = (reason) => {
    const hadToken = !!getToken();
    clearToken();
    endSession(reason, { hadToken });
  };

  const refreshOnce = () => {
    if (!refreshing) {
      state.refreshCount += 1;
      refreshing = api.post("/auth/refresh").then((res) => {
        if (res?.data?.token) setToken(res.data.token);
        return res;
      }).finally(() => { refreshing = null; });
    }
    return refreshing;
  };

  api.interceptors.request.use((config) => {
    const t = getToken();
    config.headers = config.headers || {};
    if (t) config.headers.Authorization = `Bearer ${t}`;
    else if (typeof config.headers.delete === "function") config.headers.delete("Authorization");
    else delete config.headers.Authorization;
    config._authToken = t || null;
    return config;
  });

  api.interceptors.response.use(
    (r) => { if (String(r.config?.method || "get").toLowerCase() !== "get") clearLookupCache(); return r; },
    async (error) => {
      const orig = error?.config || {};
      if (isSessionReplaced(error) && !skipsSessionReplaced(orig)) {
        terminate(SESSION_REPLACED_REASON);
        return Promise.reject(error);
      }
      if (error?.response?.status === 401 && !orig._retry && canRefreshFor(orig)) {
        orig._retry = true;
        // Token sudah diperbarui oleh refresh lain sejak request ini dikirim -> cukup ulangi tanpa refresh baru.
        const cur = getToken();
        if (cur && cur !== orig._authToken && !refreshing) return api(orig);
        try {
          await refreshOnce();
        } catch (e) {
          const kind = classifyRefreshFailure(e);
          if (kind === "replaced") { terminate(SESSION_REPLACED_REASON); return Promise.reject(e); }
          if (kind === "invalid") { terminate(SESSION_EXPIRED_REASON); error.sessionEnded = true; return Promise.reject(error); }
          if (e && typeof e === "object") e.isAuthTransient = true;
          return Promise.reject(e);
        }
        return api(orig);
      }
      return Promise.reject(error);
    }
  );
  return state;
}
