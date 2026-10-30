import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../state/AuthContext';

export default function ProtectedRoute({ allowedRoles, children }) {
  const { isAuthenticated, authChecking, role } = useAuth();
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

  if (allowedRoles && !allowedRoles.includes(role)) {
    const fallbackPath = role === 'TECHNICIAN' ? '/my-tasks' : '/';
    return <Navigate to={fallbackPath} replace />;
  }

  return children;
}
