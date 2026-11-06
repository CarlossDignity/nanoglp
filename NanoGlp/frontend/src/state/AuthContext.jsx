import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  getMe,
  loginApi,
  logoutApi,
  TOKEN_STORAGE_KEY,
  USER_STORAGE_KEY,
} from '../services/api';

const AuthContext = createContext(null);

export const USER_ADMIN_ROLES = ['SYSADMIN', 'TFM'];
export const MANAGEMENT_WRITE_ROLES = ['SYSADMIN', 'TFM', 'STUDY_DIRECTOR', 'PLANNING_COORDINATOR', 'ADMIN'];
export const MANAGEMENT_VIEW_ROLES = [...MANAGEMENT_WRITE_ROLES, 'QA', 'EXECUTIVE'];

export const DEFAULT_ALLOWED_MENUS_BY_ROLE = {
  EXECUTIVE: ['dashboard', 'samples', 'planning', 'personnel', 'studies', 'conflicts'],
  SALES: ['samples'],
  TRM_KABUL: ['samples', 'upload'],
  TRM_ACCEPTANCE: ['samples', 'upload'],
  SYSADMIN: ['dashboard', 'samples', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'my_tasks', 'users', 'settings'],
  ADMIN: ['dashboard', 'samples', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'my_tasks', 'users', 'settings'],
  TFM: ['dashboard', 'samples', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'my_tasks', 'users', 'settings'],
  STUDY_DIRECTOR: ['samples', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'my_tasks', 'settings'],
  PLANNING_COORDINATOR: ['samples', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'my_tasks', 'settings'],
  QA: ['samples', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'settings'],
  TECHNICIAN: ['my_tasks'],
  TECH: ['my_tasks'],
  VET: ['my_tasks', 'studies'],
  ANALYST: ['my_tasks'],
};

export function getDefaultRouteForRole(roleCode, allowedMenus = []) {
  const r = String(roleCode || '').toUpperCase();
  if (['SYSADMIN', 'ADMIN', 'EXECUTIVE', 'TFM'].includes(r) && (!Array.isArray(allowedMenus) || allowedMenus.includes('dashboard'))) {
    return '/';
  }
  if (['TECHNICIAN', 'TECH', 'VET', 'ANALYST'].includes(r)) {
    return '/my-tasks';
  }
  if (['STUDY_DIRECTOR', 'PLANNING_COORDINATOR', 'SALES', 'TRM_KABUL', 'TRM_ACCEPTANCE', 'QA'].includes(r)) {
    return '/samples';
  }
  if (Array.isArray(allowedMenus) && allowedMenus.includes('dashboard')) return '/';
  if (Array.isArray(allowedMenus) && allowedMenus.includes('samples')) return '/samples';
  if (Array.isArray(allowedMenus) && allowedMenus.includes('my_tasks')) return '/my-tasks';
  return '/samples';
}

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

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(USER_STORAGE_KEY);
    setToken(null);
    setUser(null);
    setAuthChecking(false);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => clearSession();
    window.addEventListener('nanolab:unauthorized', onUnauthorized);
    return () => window.removeEventListener('nanolab:unauthorized', onUnauthorized);
  }, [clearSession]);

  const logoutRequest = useRef(null);
  const logout = useCallback(async () => {
    if (logoutRequest.current) return logoutRequest.current;
    const request = (async () => {
      try {
        if (localStorage.getItem(TOKEN_STORAGE_KEY)) await logoutApi();
      } catch {
        // Explicit local logout always completes, even offline or after expiry.
      } finally {
        clearSession();
      }
    })();
    logoutRequest.current = request;
    try { await request; } finally { logoutRequest.current = null; }
  }, [clearSession]);

  const refreshUser = useCallback(async () => {
    if (!token) return null;
    try {
      const res = await getMe();
      setUser(res.data);
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(res.data));
      return res.data;
    } catch {
      return null;
    }
  }, [token]);

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
        clearSession();
      })
      .finally(() => {
        if (active) setAuthChecking(false);
      });
    return () => {
      active = false;
    };
  }, [token, clearSession]);

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
    const allowedMenus =
      Array.isArray(user?.allowed_menus) && user.allowed_menus.length > 0
        ? user.allowed_menus
        : DEFAULT_ALLOWED_MENUS_BY_ROLE[role] || ['dashboard'];
    const isReadOnly =
      user?.is_read_only !== undefined && user?.is_read_only !== null
        ? Boolean(user.is_read_only)
        : role === 'QA' || role === 'EXECUTIVE';
    const isExecutive = role === 'EXECUTIVE';
    const isSysAdmin = role === 'SYSADMIN' || role === 'ADMIN';
    const isTechnician = ['TECHNICIAN', 'TECH', 'VET', 'ANALYST'].includes(role) || (allowedMenus.length === 1 && allowedMenus[0] === 'my_tasks');
    const defaultHomeRoute = getDefaultRouteForRole(role, allowedMenus);
    const hasManagementMenu = allowedMenus.some((m) =>
      ['dashboard', 'upload', 'planning', 'personnel', 'studies', 'conflicts', 'settings'].includes(m)
    );
    const canWriteManagement = !isReadOnly && (MANAGEMENT_WRITE_ROLES.includes(role) || hasManagementMenu);
    const canViewManagement = MANAGEMENT_VIEW_ROLES.includes(role) || hasManagementMenu;
    const canManageUsers = USER_ADMIN_ROLES.includes(role) || allowedMenus.includes('users');

    return {
      token,
      user,
      role,
      roleLabel: user?.role_label || role,
      allowedMenus,
      defaultHomeRoute,
      isAuthenticated,
      authChecking,
      isReadOnly,
      isExecutive,
      isSysAdmin,
      isTechnician,
      canWriteManagement,
      canViewManagement,
      canManageUsers,
      login,
      logout,
      refreshUser,
    };
  }, [token, user, authChecking, login, logout, refreshUser]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
