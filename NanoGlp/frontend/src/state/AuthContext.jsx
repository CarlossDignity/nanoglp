import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import {
  getMe,
  loginApi,
  TOKEN_STORAGE_KEY,
  USER_STORAGE_KEY,
} from '../services/api';

const AuthContext = createContext(null);

export const USER_ADMIN_ROLES = ['SYSADMIN', 'TFM'];
export const MANAGEMENT_WRITE_ROLES = ['SYSADMIN', 'TFM', 'STUDY_DIRECTOR', 'PLANNING_COORDINATOR', 'ADMIN'];
export const MANAGEMENT_VIEW_ROLES = [...MANAGEMENT_WRITE_ROLES, 'QA'];

function readStoredUser() {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY));
  const [user, setUser] = useState(() => readStoredUser());
  const [authChecking, setAuthChecking] = useState(() => Boolean(localStorage.getItem(TOKEN_STORAGE_KEY)));

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(USER_STORAGE_KEY);
    setToken(null);
    setUser(null);
    setAuthChecking(false);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => logout();
    window.addEventListener('nanolab:unauthorized', onUnauthorized);
    return () => window.removeEventListener('nanolab:unauthorized', onUnauthorized);
  }, [logout]);

  useEffect(() => {
    if (!token) {
      setAuthChecking(false);
      return;
    }
    let active = true;
    getMe()
      .then((res) => {
        if (!active) return;
        setUser(res.data);
        localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(res.data));
      })
      .catch(() => {
        if (!active) return;
        logout();
      })
      .finally(() => {
        if (active) setAuthChecking(false);
      });
    return () => {
      active = false;
    };
  }, [token, logout]);

  const login = useCallback(async (username, password) => {
    const res = await loginApi(username, password);
    const { access_token: newToken, user: loggedUser } = res.data;
    localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(loggedUser));
    setToken(newToken);
    setUser(loggedUser);
    return loggedUser;
  }, []);

  const value = useMemo(() => {
    const role = user?.role || null;
    const isAuthenticated = Boolean(token && user);
    const isReadOnly = role === 'QA';
    const isTechnician = role === 'TECHNICIAN';
    const canWriteManagement = MANAGEMENT_WRITE_ROLES.includes(role);
    const canViewManagement = MANAGEMENT_VIEW_ROLES.includes(role);
    const canManageUsers = USER_ADMIN_ROLES.includes(role);

    return {
      token,
      user,
      role,
      isAuthenticated,
      authChecking,
      isReadOnly,
      isTechnician,
      canWriteManagement,
      canViewManagement,
      canManageUsers,
      login,
      logout,
    };
  }, [token, user, authChecking, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
