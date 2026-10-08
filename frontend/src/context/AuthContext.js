import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api, { setToken, clearToken, onSessionEnd } from "@/lib/api";
import { resolveCan } from "@/lib/access";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=user
  const [subscription, setSubscription] = useState(null); // null=checking, false=n/a, obj=status

  const loadSubscription = async (nextUser) => {
    if (!nextUser || nextUser?.is_platform_admin) {
      setSubscription(false);
      return false;
    }
    try {
      const r = await api.get("/subscription/status");
      setSubscription(r.data || false);
      return r.data || false;
    } catch {
      setSubscription(false);
      return false;
    }
  };

  const [authError, setAuthError] = useState(null); // gangguan sementara saat memulihkan sesi

  // Bootstrap sesi: /auth/me 401 -> interceptor refresh sekali -> retry /auth/me.
  // Kredensial invalid -> anonim; gangguan 5xx/network -> JANGAN dianggap anonim (tampilkan coba lagi).
  const bootstrap = useCallback(() => {
    setAuthError(null);
    api.get("/auth/me").then(async (r) => {
      setUser(r.data);
      await loadSubscription(r.data);
    }).catch((e) => {
      const s = e?.response?.status;
      if (e?.isAuthTransient || !e?.response || s >= 500) {
        setAuthError("Tidak dapat memulihkan sesi karena gangguan koneksi/server. Coba lagi.");
        return;
      }
      setUser(false);
      setSubscription(false);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { bootstrap(); }, [bootstrap]);

  // Sesi diakhiri oleh interceptor (refresh invalid / sesi digantikan) -> state frontend ikut anonim (tanpa zombie session).
  useEffect(() => onSessionEnd(() => { setUser(false); setSubscription(false); }), []);

  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    if (r.data?.token) setToken(r.data.token);
    setAuthError(null);
    let me = r.data;
    try { me = (await api.get("/auth/me")).data; } catch {}
    setUser(me);
    await loadSubscription(me);
    return me;
  };
  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    clearToken();
    setUser(false);
    setSubscription(false);
  };
  const refreshUser = async () => {
    const r = await api.get("/auth/me");
    setUser(r.data);
    await loadSubscription(r.data);
  };
  const refreshSubscription = async () => loadSubscription(user);
  // Ganti password merotasi sesi: simpan token baru untuk sesi ini (token lama sudah tidak berlaku).
  const replaceSessionToken = (t) => { if (t) setToken(t); };

  // module optional: defaults to the module of the current page (e.g. /po -> po.*)
  const can = (perm, module) => resolveCan(user, perm, module);

  return <AuthCtx.Provider value={{ user, setUser, login, logout, refreshUser, can, subscription, refreshSubscription, replaceSessionToken, authError, retryBootstrap: bootstrap }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
