import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api/client.js";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);

  const loadMe = () => {
    setUnreachable(false);
    setLoading(true);
    return api
      .me()
      .then((u) => {
        setUser(u);
        return u;
      })
      .catch((e) => {
        // Only a 401 means the session is actually invalid. A timeout or a 5xx (the API waking
        // from idle takes a few seconds) used to delete a perfectly good token and bounce the
        // user to the login page.
        if (e.status === 401) setToken(null);
        else setUnreachable(true);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    loadMe();
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
    <AuthCtx.Provider
      value={{ user, loading, unreachable, retry: loadMe, login, register, logout, updateUser: setUser }}
    >
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
