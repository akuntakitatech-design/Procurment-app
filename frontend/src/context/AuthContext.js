import { createContext, useContext, useEffect, useState } from "react";
import api, { setToken, clearToken } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=checking, false=anon, obj=user

  useEffect(() => {
    api.get("/auth/me").then((r) => setUser(r.data)).catch(() => setUser(false));
  }, []);

  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    if (r.data?.token) setToken(r.data.token);
    setUser(r.data);
    return r.data;
  };
  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    clearToken();
    setUser(false);
  };
  const refreshUser = async () => {
    const r = await api.get("/auth/me");
    setUser(r.data);
  };

  const can = (perm) => {
    if (!user) return false;
    if (user.role === "admin") return true;
    return (user.permissions || []).includes(perm);
  };

  return <AuthCtx.Provider value={{ user, setUser, login, logout, refreshUser, can }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
