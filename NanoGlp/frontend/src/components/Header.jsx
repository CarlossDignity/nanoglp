import React from 'react';
import { LogOut } from 'lucide-react';
import { useAuth } from '../state/AuthContext';
import { ROLE_LABEL } from '../utils/format';

export default function Header({ systemStatus }) {
  const { user, isReadOnly, isExecutive, roleLabel, logout } = useAuth();

  return (
    <header className="bg-white text-slate-900 px-6 h-14 flex items-center justify-between sticky top-0 z-30 border-b border-slate-200">
      <div className="flex items-center gap-4">
        <img
          src="/nanolab-logo.png"
          alt="NanoLab Laboratuvarlar Grubu"
          className="h-8 w-auto object-contain select-none"
          draggable={false}
        />
        <div className="hidden md:block h-6 w-px bg-slate-200" />
        <div className="hidden md:block leading-tight">
          <h1 className="text-sm font-semibold text-slate-900">Edirne — GLP Test Tesisi</h1>
          <p className="text-[11px] text-slate-500">Operasyonel Planlama ve Çakışma Yönetimi</p>
        </div>
      </div>

      <div className="flex items-center gap-4 text-xs">
        <div className="hidden sm:flex items-center gap-1.5 text-slate-600">
          <span className={`w-1.5 h-1.5 rounded-full ${systemStatus ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <span>{systemStatus ? 'API bağlı' : 'API bağlantısı yok'}</span>
        </div>

        {user && (
          <div className="flex items-center gap-3 pl-4 border-l border-slate-200">
            {isReadOnly && (
              <span className="hidden md:inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-600">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                {isExecutive ? 'İZLEME MODU' : 'SALT OKUNUR'}
              </span>
            )}
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-900">{user.full_name}</span>
              <span className="text-[11px] px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-slate-600">
                {roleLabel || ROLE_LABEL[user.role] || user.role}
              </span>
            </div>
            <button
              type="button"
              onClick={logout}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 transition text-[11px] font-medium"
              title="Güvenli çıkış yap"
            >
              <LogOut className="w-3.5 h-3.5 text-slate-500" />
              <span>Çıkış</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
