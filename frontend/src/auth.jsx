import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api/client.js";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (email, password) => {
    const { access_token, user } = await api.login(email, password);
    setToken(access_token);
    setUser(user);
  };
  const register = async (email, password, organisation, claimCode) => {
    const { access_token, user } = await api.register(email, password, organisation, claimCode);
    setToken(access_token);
    setUser(user);
  };
  const logout = () => {
    setToken(null);
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
