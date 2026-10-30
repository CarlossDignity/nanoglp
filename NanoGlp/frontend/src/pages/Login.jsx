import React, { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ShieldCheck, Lock, User, LogIn, Loader2, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../state/AuthContext';
import { extractError } from '../services/api';

export default function Login() {
  const { isAuthenticated, role, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (isAuthenticated) {
    const target = role === 'TECHNICIAN' ? '/my-tasks' : '/';
    return <Navigate to={target} replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const loggedUser = await login(username.trim(), password);
      if (loggedUser.role === 'TECHNICIAN') {
        navigate('/my-tasks', { replace: true });
      } else {
        const fromPath = location.state?.from?.pathname;
        const safeDest =
          fromPath && fromPath !== '/login' && fromPath !== '/my-tasks' ? fromPath : '/';
        navigate(safeDest, { replace: true });
      }
    } catch (err) {
      setError(extractError(err, 'Giriş yapılamadı. Kullanıcı adı veya şifreyi kontrol edin.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col justify-center items-center p-4 text-slate-900">
      <div className="w-full max-w-3xl grid grid-cols-1 md:grid-cols-2 bg-white rounded-xl shadow-2xl overflow-hidden border border-slate-800">
        {/* Sol Kurumsal Panel */}
        <div className="bg-gradient-to-br from-slate-900 via-slate-800 to-blue-950 text-white p-10 flex flex-col justify-center">
          <div className="bg-blue-600/90 w-12 h-12 rounded-xl flex items-center justify-center shadow-lg mb-6">
            <ShieldCheck className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight leading-snug text-white">
            Nanolab GLP Planlama Sistemi
          </h1>
          <p className="text-sm text-slate-300 mt-3 leading-relaxed">
            Nanolab Edirne Test Tesisi kurumsal çalışma ve kaynak yönetimi portalına hoş geldiniz.
          </p>
        </div>

        {/* Sağ Giriş Formu */}
        <div className="p-10 flex flex-col justify-center bg-white">
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold text-slate-900">Kullanıcı Girişi</h2>
              <p className="text-xs text-slate-500 mt-1">
                Devam etmek için kurumsal kullanıcı adınızı ve şifrenizi girin.
              </p>
            </div>

            {error && (
              <div role="alert" className="p-3 rounded-md bg-red-50 border border-red-200 text-xs text-red-700 font-medium">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="login-username" className="block text-xs font-medium text-slate-700 mb-1.5">
                  Kullanıcı Adı
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
                    placeholder="kullanici_adi"
                    className="w-full border border-slate-300 rounded-md pl-9 pr-3 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-600"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="login-password" className="block text-xs font-medium text-slate-700 mb-1.5">
                  Şifre
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
                    className="w-full border border-slate-300 rounded-md pl-9 pr-9 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    aria-label="Şifreyi Göster/Gizle"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting || !username.trim() || !password}
                className="w-full flex items-center justify-center gap-2 bg-blue-700 hover:bg-blue-800 disabled:bg-blue-400 text-white text-sm font-semibold rounded-md py-2.5 shadow-sm transition"
              >
                {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
                {submitting ? 'Giriş Yapılıyor…' : 'Giriş Yap'}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
