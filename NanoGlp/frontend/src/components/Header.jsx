import React from 'react';
import { ShieldCheck, LogOut, UserCheck, Eye } from 'lucide-react';
import { useAuth } from '../state/AuthContext';
import { ROLE_LABEL } from '../utils/format';

export default function Header({ systemStatus }) {
  const { user, isReadOnly, logout } = useAuth();

  return (
    <header className="bg-slate-900 text-white px-6 h-14 flex items-center justify-between sticky top-0 z-30 border-b border-slate-800">
      <div className="flex items-center gap-3">
        <div className="bg-blue-600 p-1.5 rounded">
          <ShieldCheck className="w-5 h-5" />
        </div>
        <div className="leading-tight">
          <h1 className="text-sm font-semibold tracking-wide">NANOLAB Edirne · GLP Test Tesisi</h1>
          <p className="text-[11px] text-slate-400">Operasyonel Planlama ve Çakışma Yönetimi</p>
        </div>
      </div>

      <div className="flex items-center gap-4 text-xs">
        <div className="hidden sm:flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${systemStatus ? 'bg-green-400' : 'bg-red-500'}`} />
          <span className="text-slate-300">{systemStatus ? 'API bağlı' : 'API bağlantısı yok'}</span>
        </div>

        {user && (
          <div className="flex items-center gap-3 pl-3 border-l border-slate-700">
            {isReadOnly && (
              <span className="hidden md:inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/20 border border-amber-400/40 text-amber-300 text-[11px] font-semibold">
                <Eye className="w-3 h-3" /> SALT OKUNUR (QA)
              </span>
            )}
            <div className="flex items-center gap-1.5 text-slate-200">
              <UserCheck className="w-3.5 h-3.5 text-blue-400" />
              <span className="font-semibold">{user.full_name}</span>
              <span className="text-[11px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                {ROLE_LABEL[user.role] || user.role}
              </span>
            </div>
            <button
              type="button"
              onClick={logout}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-slate-800 hover:bg-red-600/90 text-slate-200 hover:text-white border border-slate-700 transition text-[11px] font-medium"
              title="Güvenli Çıkış Yap"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>Çıkış</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
