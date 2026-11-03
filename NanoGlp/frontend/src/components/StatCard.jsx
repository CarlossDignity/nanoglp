import React from 'react';
import { usePreferences } from '../state/PreferencesContext';

/**
 * FAZ 8.2 — Kurumsal KPI kartı (Linear / shadcn stili):
 * ikon kutusu yok; küçük gri ikon başlıkla aynı satırda, değer mono rakamlarla.
 */
export default function StatCard({ title, value, subtitle, icon: Icon, alert = false, loading }) {
  const { t } = usePreferences();
  return (
    <div
      className={`bg-white rounded-lg p-4 border shadow-xs h-full transition-colors hover:bg-slate-50/60 ${
        alert ? 'border-red-300' : 'border-slate-200'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-slate-500">
          {alert && <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />}
          {typeof title === 'string' ? t(title) : title}
        </p>
        {Icon && <Icon className="w-4 h-4 text-slate-400 shrink-0" />}
      </div>
      <p className={`text-2xl font-semibold mt-2 font-mono tabular-nums ${alert ? 'text-red-700' : 'text-slate-900'}`}>
        {loading ? <span className="inline-block w-10 h-7 bg-slate-100 rounded animate-pulse" /> : value}
      </p>
      {subtitle && <p className="text-xs text-slate-500 mt-1.5 leading-snug">{typeof subtitle === 'string' ? t(subtitle) : subtitle}</p>}
    </div>
  );
}
