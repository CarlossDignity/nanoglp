import React, { useEffect, useState } from 'react';
import { CheckCircle2, KeyRound, LogOut, X } from 'lucide-react';
import { changePasswordApi } from '../services/api';
import { useAuth } from '../state/AuthContext';
import { ThemeLanguageControls, usePreferences } from '../state/PreferencesContext';
import { ROLE_LABEL } from '../utils/format';

export default function Header({ systemStatus }) {
  const { user, isReadOnly, isExecutive, roleLabel, logout } = useAuth();
  const { t, syncUserLanguagePreference } = usePreferences();

  const [showPwModal, setShowPwModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [pwLoading, setPwLoading] = useState(false);
  const [pwError, setPwError] = useState('');
  const [pwSuccess, setPwSuccess] = useState('');

  useEffect(() => {
    if (user?.username) {
      syncUserLanguagePreference(user.username);
    }
  }, [user?.username, syncUserLanguagePreference]);

  const displayedRole = t(roleLabel || ROLE_LABEL[user?.role] || user?.role || '');

  const openPwModal = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setPwError('');
    setPwSuccess('');
    setShowPwModal(true);
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setPwError('');
    setPwSuccess('');
    if (!currentPassword || !newPassword) {
      setPwError(t('Mevcut şifre ve yeni şifre alanları zorunludur.', 'Current password and new password are required.'));
      return;
    }
    if (newPassword.length < 8) {
      setPwError(t('Yeni şifre en az 8 karakter uzunluğunda olmalıdır.', 'New password must be at least 8 characters long.'));
      return;
    }
    if (newPassword !== confirmPassword) {
      setPwError(t('Yeni şifre ve şifre tekrarı eşleşmiyor.', 'New password and confirmation do not match.'));
      return;
    }
    setPwLoading(true);
    try {
      await changePasswordApi(currentPassword, newPassword);
      setPwSuccess(t('Şifreniz başarıyla güncellendi.', 'Your password has been updated successfully.'));
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setTimeout(() => {
        setShowPwModal(false);
        setPwSuccess('');
      }, 1500);
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        t('Şifre değiştirilirken bir hata oluştu.', 'An error occurred while changing password.');
      setPwError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setPwLoading(false);
    }
  };

  return (
    <>
      <header className="bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 px-6 h-14 flex items-center justify-between sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-4">
          <div className="dark:bg-white/95 dark:px-2 dark:py-0.5 dark:rounded">
            <img
              src="/nanolab-logo.png"
              alt="NanoLab Laboratuvarlar Grubu"
              className="h-8 w-auto object-contain select-none"
              draggable={false}
            />
          </div>
          <div className="hidden md:block h-6 w-px bg-slate-200 dark:bg-slate-800" />
          <div className="hidden md:block leading-tight">
            <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {t('Edirne — GLP Test Tesisi', 'Edirne — GLP Test Facility')}
            </h1>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              {t('Operasyonel Planlama ve Çakışma Yönetimi', 'Operational Planning & Conflict Management')}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <div className="hidden sm:flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
            <span className={`w-1.5 h-1.5 rounded-full ${systemStatus ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <span>{systemStatus ? t('API bağlı', 'API Connected') : t('API bağlantısı yok', 'API Disconnected')}</span>
          </div>

          <div className="pl-2 border-l border-slate-200 dark:border-slate-800">
            <ThemeLanguageControls variant="header" />
          </div>

          {user && (
            <div className="flex items-center gap-2.5 pl-3 border-l border-slate-200 dark:border-slate-800">
              {isReadOnly && (
                <span className="hidden md:inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-600 dark:text-slate-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  {isExecutive ? t('İZLEME MODU', 'VIEW ONLY') : t('SALT OKUNUR', 'READ ONLY')}
                </span>
              )}
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-900 dark:text-slate-100">{user.full_name}</span>
                <span className="text-[11px] px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                  {displayedRole}
                </span>
              </div>
              <button
                type="button"
                onClick={openPwModal}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition text-[11px] font-medium"
                title={t('Hesap şifrenizi değiştirin', 'Change your account password')}
              >
                <KeyRound className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
                <span className="hidden sm:inline">{t('Şifre Değiştir', 'Change Password')}</span>
              </button>
              <button
                type="button"
                onClick={logout}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition text-[11px] font-medium"
                title={t('Güvenli çıkış yap', 'Sign out securely')}
              >
                <LogOut className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400" />
                <span>{t('Çıkış', 'Sign Out')}</span>
              </button>
            </div>
          )}
        </div>
      </header>

      {showPwModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 shadow-xl">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-slate-600 dark:text-slate-300" />
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {t('Şifre Değiştir', 'Change Password')}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setShowPwModal(false)}
                className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handlePasswordSubmit} className="p-5 space-y-3.5 text-xs">
              <div className="text-[11px] text-slate-500 dark:text-slate-400">
                {t(
                  `Aktif hesap: ${user?.full_name || ''} (${user?.username || ''}). Yeni şifreniz en az 8 karakter olmalıdır.`,
                  `Active account: ${user?.full_name || ''} (${user?.username || ''}). Your new password must be at least 8 characters.`
                )}
              </div>

              {pwError && (
                <div className="p-2.5 rounded border border-red-200 dark:border-red-800/70 bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 text-[11px] font-medium">
                  {pwError}
                </div>
              )}

              {pwSuccess && (
                <div className="p-2.5 rounded border border-emerald-200 dark:border-emerald-800/70 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 text-[11px] font-medium flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                  <span>{pwSuccess}</span>
                </div>
              )}

              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  {t('Mevcut Şifre', 'Current Password')}
                </label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  autoComplete="current-password"
                  className="w-full px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="••••••••"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  {t('Yeni Şifre (En az 8 karakter)', 'New Password (Min. 8 characters)')}
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  className="w-full px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="••••••••"
                  required
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  {t('Yeni Şifre (Tekrar)', 'Confirm New Password')}
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  className="w-full px-3 py-2 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="••••••••"
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-200 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowPwModal(false)}
                  className="px-3 py-1.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-medium"
                >
                  {t('İptal', 'Cancel')}
                </button>
                <button
                  type="submit"
                  disabled={pwLoading}
                  className="px-3.5 py-1.5 rounded bg-slate-900 dark:bg-blue-600 hover:bg-slate-800 dark:hover:bg-blue-500 text-white font-semibold disabled:opacity-50"
                >
                  {pwLoading ? t('Kaydediliyor...', 'Saving...') : t('Şifreyi Güncelle', 'Update Password')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
