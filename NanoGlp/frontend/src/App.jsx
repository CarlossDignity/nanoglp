import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { RefreshCw, ShieldAlert, AlertTriangle, CheckCircle2 } from 'lucide-react';
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
import SampleTracking from './pages/SampleTracking';
import { useAuth, MANAGEMENT_VIEW_ROLES, USER_ADMIN_ROLES } from './state/AuthContext';
import { usePreferences } from './state/PreferencesContext';
import {
  getHealth,
  getStudies,
  getPersonnel,
  getConflicts,
  recomputeConflicts,
  applyConflictResolution,
  extractError,
} from './services/api';

function ConflictsPage({ conflicts, onRefresh }) {
  const { t } = usePreferences();
  const { isReadOnly } = useAuth();
  const [activeTab, setActiveTab] = useState('CONFIRMED');
  const [reasonFilter, setReasonFilter] = useState('ALL');
  const [recomputing, setRecomputing] = useState(false);
  const [banner, setBanner] = useState(null);
  const [errMsg, setErrMsg] = useState(null);

  const confirmedConflicts = useMemo(
    () => (conflicts || []).filter((c) => c.conflict_category !== 'MISSING_INFO'),
    [conflicts]
  );
  const missingInfoConflicts = useMemo(
    () => (conflicts || []).filter((c) => c.conflict_category === 'MISSING_INFO'),
    [conflicts]
  );

  const filteredMissingConflicts = useMemo(() => {
    if (reasonFilter === 'ALL') return missingInfoConflicts;
    return missingInfoConflicts.filter((c) => (c.missing_info_codes || []).includes(reasonFilter));
  }, [missingInfoConflicts, reasonFilter]);

  const reasonCounts = useMemo(() => {
    const counts = {
      ALL: missingInfoConflicts.length,
      MISSING_START_DATE: 0,
      DEFAULT_TECHNICIAN: 0,
      MISSING_TIIS_OR_EQUIPMENT: 0,
    };
    missingInfoConflicts.forEach((c) => {
      (c.missing_info_codes || []).forEach((code) => {
        if (counts[code] !== undefined) counts[code] += 1;
      });
    });
    return counts;
  }, [missingInfoConflicts]);

  const handleRecompute = async () => {
    setRecomputing(true);
    setBanner(null);
    setErrMsg(null);
    try {
      const res = await recomputeConflicts();
      const d = res.data || {};
      await onRefresh?.();
      setBanner(
        t(
          `Çakışmalar yeniden hesaplandı: ${d.confirmed_conflicts ?? 0} gerçek çakışma, ${d.missing_info_conflicts ?? 0} eksik bilgi kaynaklı olası çakışma (${d.total_completed_steps ?? 0} geçmiş adım TAMAMLANDI olarak kapatıldı).`,
          `Conflicts recomputed: ${d.confirmed_conflicts ?? 0} confirmed conflicts, ${d.missing_info_conflicts ?? 0} potential conflicts due to missing info (${d.total_completed_steps ?? 0} past steps marked COMPLETED).`
        )
      );
    } catch (err) {
      setErrMsg(extractError(err, t('Çakışmalar yeniden hesaplanamadı.', 'Failed to recompute conflicts.')));
    } finally {
      setRecomputing(false);
    }
  };

  const handleApplyResolution = async (conflictId, resolution) => {
    setErrMsg(null);
    try {
      await applyConflictResolution(conflictId, {
        action: resolution.action,
        target_user_id: resolution.target_user_id || null,
      });
      await onRefresh?.();
      setBanner(
        t(
          'Çözüm uygulandı ve çalışma çakışmaları güncellendi.',
          'Resolution applied and study conflicts updated.'
        )
      );
    } catch (err) {
      setErrMsg(extractError(err, t('Çözüm uygulanamadı.', 'Failed to apply resolution.')));
    }
  };

  const displayedList = activeTab === 'CONFIRMED' ? confirmedConflicts : filteredMissingConflicts;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            {t('Açık Çakışmalar', 'Open Conflicts')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t(
              'Tamamlanmış geçmiş görevler (03.11.2026 öncesi) kapatılmıştır; aktif çakışmalar Gerçek Çakışmalar ve Eksik Bilgi kaynaklı olarak ayrılmıştır.',
              'Completed historical tasks (prior to Nov 3, 2026) are closed; active conflicts are separated into Confirmed Conflicts and Missing Info.'
            )}
          </p>
        </div>

        {!isReadOnly && (
          <button
            type="button"
            disabled={recomputing}
            onClick={handleRecompute}
            className="inline-flex items-center gap-2 text-xs font-semibold px-3.5 py-2 rounded-lg border border-slate-900 bg-slate-900 text-white hover:bg-slate-800 shadow-xs transition disabled:opacity-60"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${recomputing ? 'animate-spin' : ''}`} />
            <span>{t('Çakışmaları Yeniden Hesapla', 'Recompute Conflicts')}</span>
          </button>
        )}
      </div>

      {banner && (
        <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-xs font-medium text-emerald-900 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span>{banner}</span>
        </div>
      )}
      {errMsg && (
        <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-xs font-medium text-red-800">
          {errMsg}
        </div>
      )}

      {/* 2 Ana Kategori Sekmesi */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white border border-slate-200 rounded-lg p-2 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('CONFIRMED')}
            className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-xs font-semibold transition ${
              activeTab === 'CONFIRMED'
                ? 'bg-slate-900 text-white shadow-xs'
                : 'text-slate-700 hover:bg-slate-100'
            }`}
          >
            <ShieldAlert className={`w-3.5 h-3.5 ${activeTab === 'CONFIRMED' ? 'text-red-300' : 'text-red-600'}`} />
            <span>
              {t('Gerçek Çakışmalar', 'Confirmed Conflicts')} ({confirmedConflicts.length})
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('MISSING_INFO')}
            className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-xs font-semibold transition ${
              activeTab === 'MISSING_INFO'
                ? 'bg-slate-900 text-white shadow-xs'
                : 'text-slate-700 hover:bg-slate-100'
            }`}
          >
            <AlertTriangle
              className={`w-3.5 h-3.5 ${activeTab === 'MISSING_INFO' ? 'text-amber-300' : 'text-amber-600'}`}
            />
            <span>
              {t('Eksik Bilgi Sebebiyle Çakışmalar', 'Conflicts Due to Missing Info')} ({missingInfoConflicts.length})
            </span>
          </button>
        </div>

        <span className="text-[11px] font-mono text-slate-500 px-2">
          {t(
            `Toplam Açık: ${conflicts.length} (${confirmedConflicts.length} Gerçek + ${missingInfoConflicts.length} Eksik Bilgi)`,
            `Total Open: ${conflicts.length} (${confirmedConflicts.length} Confirmed + ${missingInfoConflicts.length} Missing Info)`
          )}
        </span>
      </div>

      {activeTab === 'MISSING_INFO' && (
        <div className="bg-white border border-slate-200 rounded-lg p-3.5 space-y-2.5 shadow-xs">
          <p className="text-xs text-slate-600 leading-relaxed">
            {t(
              'Bu sekmedeki olası çakışmalar; Excel’de başlangıç tarihi girilmemiş olması, saha teknisyeninin henüz atanmamış olması (varsayılan teknisyen) veya TIIS / CoA PDF belgesinin henüz yüklenmemiş olmasından kaynaklanmaktadır. Eksik bilgileri tamamladıktan sonra üstteki "Çakışmaları Yeniden Hesapla" butonuna tıklayın.',
              'Potential conflicts in this tab are caused by missing start dates in Excel, unassigned field technicians (default technician), or unuploaded TIIS / CoA PDF documents. After completing the missing info, click "Recompute Conflicts" above.'
            )}
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            {[
              { code: 'ALL', label: t('Tümü', 'All') },
              { code: 'MISSING_START_DATE', label: t('Başlangıç Tarihi Eksik', 'Missing Start Date') },
              { code: 'DEFAULT_TECHNICIAN', label: t('Teknisyen Ataması Varsayılan', 'Default Technician Assignment') },
              { code: 'MISSING_TIIS_OR_EQUIPMENT', label: t('TIIS PDF / Cihaz Bilgisi Eksik', 'Missing TIIS PDF / Equipment Info') },
            ].map((f) => {
              const active = reasonFilter === f.code;
              return (
                <button
                  key={f.code}
                  type="button"
                  onClick={() => setReasonFilter(f.code)}
                  className={`px-2.5 py-1 rounded-md text-xs font-semibold border transition ${
                    active
                      ? 'bg-slate-900 text-white border-slate-900'
                      : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                  }`}
                >
                  {f.label} ({reasonCounts[f.code] ?? 0})
                </button>
              );
            })}
          </div>
        </div>
      )}

      {displayedList.length ? (
        <ConflictAlert
          conflicts={displayedList}
          onApplyResolution={handleApplyResolution}
          isReadOnly={isReadOnly}
          showNavigationLinks={true}
          title={
            activeTab === 'CONFIRMED'
              ? t(
                  `${displayedList.length} GERÇEK GLP ÇAKIŞMASI (ONAYLI BAŞLANGIÇ TARİHİ & ÇY)`,
                  `${displayedList.length} CONFIRMED GLP CONFLICTS (CONFIRMED START DATE & SD)`
                )
              : t(
                  `${displayedList.length} EKSİK BİLGİ SEBEBİYLE OLASI ÇAKIŞMA`,
                  `${displayedList.length} POTENTIAL CONFLICTS DUE TO MISSING INFO`
                )
          }
        />
      ) : (
        <p className="p-8 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg text-center text-sm text-slate-400">
          {t('Bu kategoride açık çakışma kaydı bulunmuyor.', 'No open conflict records found in this category.')}
        </p>
      )}
    </div>
  );
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, canViewManagement, isTechnician, defaultHomeRoute } = useAuth();
  const { lang } = usePreferences();

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

  const confirmedConflictsCount = useMemo(
    () => (conflicts || []).filter((c) => c.conflict_category !== 'MISSING_INFO').length,
    [conflicts]
  );

  if (location.pathname === '/login') {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
      </Routes>
    );
  }

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-slate-50 dark:bg-[#090d16] font-sans text-slate-900 dark:text-slate-100">
        <Header systemStatus={systemOnline} />
        <div key={lang} className="flex">
          <Sidebar badges={{ conflicts: confirmedConflictsCount }} />
          <main className="flex-1 p-6 lg:p-8 max-w-7xl">
            <Routes>
              <Route
                path="/"
                element={
                  <ProtectedRoute menuKey="dashboard" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Dashboard key={conflicts.length} onNavigate={(id) => navigate(`/${id}`)} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute menuKey="dashboard" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Dashboard key={conflicts.length} onNavigate={(id) => navigate(`/${id}`)} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/samples"
                element={
                  <ProtectedRoute menuKey="samples">
                    <SampleTracking />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/upload"
                element={
                  <ProtectedRoute menuKey="upload" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Upload personnel={personnel} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/planning"
                element={
                  <ProtectedRoute menuKey="planning" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Planning onScheduled={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/personnel"
                element={
                  <ProtectedRoute menuKey="personnel" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Personnel onChanged={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/studies"
                element={
                  <ProtectedRoute menuKey="studies" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Studies studies={studies} personnel={personnel} onRefresh={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/conflicts"
                element={
                  <ProtectedRoute menuKey="conflicts" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <ConflictsPage conflicts={conflicts} onRefresh={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/users"
                element={
                  <ProtectedRoute menuKey="users" allowedRoles={USER_ADMIN_ROLES}>
                    <UserManagement onChanged={refresh} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute menuKey="settings" allowedRoles={MANAGEMENT_VIEW_ROLES}>
                    <Settings personnel={personnel} />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/my-tasks"
                element={
                  <ProtectedRoute menuKey="my_tasks">
                    <MyTasks />
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to={defaultHomeRoute || (isTechnician ? '/my-tasks' : '/samples')} replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </ProtectedRoute>
  );
}
