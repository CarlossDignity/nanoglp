import React, { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ShieldCheck, Lock, User, LogIn, Loader2, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../state/AuthContext';
import { ThemeLanguageControls, usePreferences } from '../state/PreferencesContext';
import { extractError } from '../services/api';

export default function Login() {
  const { isAuthenticated, role, login, defaultHomeRoute } = useAuth();
  const { t, syncUserLanguagePreference } = usePreferences();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (isAuthenticated) {
    const target = role === 'TECHNICIAN' ? '/my-tasks' : defaultHomeRoute || '/';
    return <Navigate to={target} replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const loggedUser = await login(username.trim(), password);
      if (loggedUser?.username) {
        syncUserLanguagePreference(loggedUser.username);
      }
      if (loggedUser.role === 'TECHNICIAN') {
        navigate('/my-tasks', { replace: true });
      } else {
        const fromPath = location.state?.from?.pathname;
        const safeDest =
          fromPath && fromPath !== '/login' && fromPath !== '/my-tasks' ? fromPath : '/';
        navigate(safeDest, { replace: true });
      }
    } catch (err) {
      setError(
        extractError(
          err,
          t(
            'Giriş yapılamadı. Kullanıcı adı veya şifreyi kontrol edin.',
            'Sign in failed. Please check your username and password.'
          )
        )
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 dark:bg-[#090d16] flex flex-col justify-center items-center p-4 text-slate-900 dark:text-slate-100 relative">
      {/* Sağ üst: TR | EN + Açık / Koyu Tema */}
      <div className="fixed top-4 right-4 z-30">
        <ThemeLanguageControls variant="login" />
      </div>

      <div className="w-full max-w-3xl grid grid-cols-1 md:grid-cols-2 bg-white dark:bg-slate-900 rounded-lg shadow-2xl overflow-hidden border border-slate-800">
        {/* Sol Kurumsal Panel */}
        <div className="bg-slate-900 dark:bg-slate-950 text-white p-10 flex flex-col justify-center border-b md:border-b-0 md:border-r border-slate-800">
          <div className="bg-white rounded-lg px-5 py-3 shadow-xs ring-1 ring-white/20 mb-8 self-start">
            <img
              src="/nanolab-logo.png"
              alt="NanoLab Laboratuvarlar Grubu"
              className="h-14 w-auto object-contain select-none"
              draggable={false}
            />
          </div>
          <div className="inline-flex items-center gap-1.5 self-start text-[11px] font-semibold uppercase tracking-wider text-blue-200 bg-blue-500/15 border border-blue-400/30 rounded-full px-2.5 py-1 mb-3">
            <ShieldCheck className="w-3.5 h-3.5" /> {t('GLP · Edirne Test Tesisi', 'GLP · Edirne Test Facility')}
          </div>
          <h1 className="text-3xl font-bold tracking-tight leading-snug text-white">
            {t('Nanolab GLP Planlama Sistemi', 'Nanolab GLP Planning System')}
          </h1>
          <p className="text-sm text-slate-300 mt-3 leading-relaxed">
            {t(
              'Nanolab Edirne Test Tesisi kurumsal çalışma ve kaynak yönetimi portalına hoş geldiniz.',
              'Welcome to the Nanolab Edirne Test Facility enterprise study and resource management portal.'
            )}
          </p>
        </div>

        {/* Sağ Giriş Formu */}
        <div className="p-10 flex flex-col justify-center bg-white dark:bg-slate-900">
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">
                {t('Kullanıcı Girişi', 'User Sign In')}
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t(
                  'Devam etmek için kurumsal kullanıcı adınızı ve şifrenizi girin.',
                  'Enter your corporate username and password to continue.'
                )}
              </p>
            </div>

            {error && (
              <div role="alert" className="p-3 rounded-md bg-red-50 border border-red-200 text-xs text-red-700 font-medium">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="login-username" className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  {t('Kullanıcı Adı', 'Username')}
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    id="login-username"
                    type="text"
                    required
                    autoFocus
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder={t('kullanici_adi', 'username')}
                    className="w-full border border-slate-300 dark:border-slate-700 rounded-md pl-9 pr-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-600"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="login-password" className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                  {t('Şifre', 'Password')}
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    id="login-password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full border border-slate-300 dark:border-slate-700 rounded-md pl-9 pr-9 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                    aria-label={t('Şifreyi Göster/Gizle', 'Show/Hide Password')}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting || !username.trim() || !password}
                className="w-full flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 disabled:bg-blue-400 text-white text-sm font-semibold rounded-md py-2.5 shadow-xs transition"
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
                {submitting ? t('Giriş Yapılıyor…', 'Signing In…') : t('Giriş Yap', 'Sign In')}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
