import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../state/AuthContext';

const MENU_KEY_TO_PATH = {
  dashboard: '/',
  samples: '/samples',
  upload: '/upload',
  planning: '/planning',
  personnel: '/personnel',
  studies: '/studies',
  conflicts: '/conflicts',
  my_tasks: '/my-tasks',
  users: '/users',
  settings: '/settings',
};

export default function ProtectedRoute({ allowedRoles, menuKey, children }) {
  const { isAuthenticated, authChecking, role, allowedMenus } = useAuth();
  const location = useLocation();

  if (authChecking) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center text-sm text-slate-500 gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-blue-700" />
        <span>GLP oturum yetkisi doğrulanıyor…</span>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  const firstAllowedPath = MENU_KEY_TO_PATH[allowedMenus?.[0]] || (role === 'TECHNICIAN' ? '/my-tasks' : '/');

  if (menuKey && Array.isArray(allowedMenus) && !allowedMenus.includes(menuKey)) {
    return <Navigate to={firstAllowedPath} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(role) && !(menuKey && allowedMenus?.includes(menuKey))) {
    return <Navigate to={firstAllowedPath} replace />;
  }

  return children;
}
