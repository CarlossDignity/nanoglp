import React from 'react';

const tones = {
  blue: 'bg-blue-50 text-blue-700',
  slate: 'bg-slate-100 text-slate-700',
  red: 'bg-red-50 text-red-700',
  indigo: 'bg-indigo-50 text-indigo-700',
};

export default function StatCard({ title, value, subtitle, icon: Icon, tone = 'blue', alert = false, loading }) {
  return (
    <div
      className={`bg-white rounded-lg p-5 border shadow-sm flex items-start justify-between ${
        alert ? 'border-red-300 ring-1 ring-red-200' : 'border-slate-200'
      }`}
    >
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</p>
        <p className={`text-3xl font-semibold mt-2 ${alert ? 'text-red-700' : 'text-slate-900'}`}>
          {loading ? <span className="inline-block w-10 h-7 bg-slate-100 rounded animate-pulse" /> : value}
        </p>
        {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
      </div>
      {Icon && (
        <div className={`p-2.5 rounded-md ${tones[alert ? 'red' : tone]}`}>
          <Icon className="w-5 h-5" />
        </div>
      )}
    </div>
  );
}
