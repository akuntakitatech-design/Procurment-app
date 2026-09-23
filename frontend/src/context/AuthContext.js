import { createContext, useContext, useEffect, useState } from "react";
import api, { setToken, clearToken } from "@/lib/api";

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

  useEffect(() => {
    api.get("/auth/me").then(async (r) => {
      setUser(r.data);
      await loadSubscription(r.data);
    }).catch(() => {
      setUser(false);
      setSubscription(false);
    });
  }, []);

  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    if (r.data?.token) setToken(r.data.token);
    setUser(r.data);
    await loadSubscription(r.data);
    return r.data;
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

  const can = (perm) => {
    if (!user) return false;
    if (user.role === "admin") return true;
    return (user.permissions || []).includes(perm);
  };

  return <AuthCtx.Provider value={{ user, setUser, login, logout, refreshUser, can, subscription, refreshSubscription }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
