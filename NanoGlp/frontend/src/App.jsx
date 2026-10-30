import React, { useCallback, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import ConflictAlert from './components/ConflictAlert';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Planning from './pages/Planning';
import Personnel from './pages/Personnel';
import Studies from './pages/Studies';
import Settings from './pages/Settings';
import Upload from './pages/Upload';
import MyTasks from './pages/MyTasks';
import UserManagement from './pages/UserManagement';
import { useAuth, MANAGEMENT_VIEW_ROLES, USER_ADMIN_ROLES } from './state/AuthContext';
import { getHealth, getStudies, getPersonnel, getConflicts } from './services/api';

function ConflictsPage({ conflicts }) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Açık Çakışmalar</h2>
        <p className="text-sm text-slate-500">Çözülmemiş tüm GLP çakışma kayıtları (en yeni üstte).</p>
      </div>
      {conflicts.length ? (
        <ConflictAlert conflicts={conflicts} title={`${conflicts.length} AÇIK GLP ÇAKIŞMASI`} />
      ) : (
        <p className="p-8 bg-white border border-slate-200 rounded-lg text-center text-sm text-slate-400">
          Açık çakışma kaydı bulunmuyor.
        </p>
      )}
    </div>
  );
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, canViewManagement, isTechnician } = useAuth();

  const [systemOnline, setSystemOnline] = useState(false);
  const [studies, setStudies] = useState([]);
  const [personnel, setPersonnel] = useState([]);
  const [conflicts, setConflicts] = useState([]);

  const refresh = useCallback(async () => {
    const h = await getHealth().then(() => true).catch(() => false);
    setSystemOnline(h);

    if (!isAuthenticated || !canViewManagement) {
      setStudies([]);
      setPersonnel([]);
      setConflicts([]);
      return;
    }

    const [s, p, c] = await Promise.allSettled([
      getStudies(),
      getPersonnel(),
      getConflicts({ unresolved_only: true }),
    ]);
    if (s.status === 'fulfilled') setStudies(s.value.data);
    if (p.status === 'fulfilled') setPersonnel(p.value.data);
    if (c.status === 'fulfilled') setConflicts(c.value.data);
  }, [isAuthenticated, canViewManagement]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (location.pathname === '/login') {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
      </Routes>
    );
  }

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-slate-50 font-sans text-slate-900">
        <Header systemStatus={systemOnline} />
        <div className="flex">
          <Sidebar badges={{ conflicts: conflicts.length }} />
          <main className="flex-1 p-6 lg:p-8 max-w-7xl">
            <Routes>
              <Route
                path="/"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Dashboard key={conflicts.length} onNavigate={(id) => navigate(`/${id}`)} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/upload"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Upload personnel={personnel} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/planning"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Planning onScheduled={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/personnel"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Personnel onChanged={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/studies"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Studies studies={studies} personnel={personnel} onRefresh={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/conflicts"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <ConflictsPage conflicts={conflicts} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/users"
                element={
                  <ProtectedRoute allowedRoles={USER_ADMIN_ROLES}>
                    <UserManagement onChanged={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Settings personnel={personnel} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/my-tasks"
                element={
                  <ProtectedRoute>
                    <MyTasks />
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to={isTechnician ? '/my-tasks' : '/'} replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </ProtectedRoute>
  );
}
