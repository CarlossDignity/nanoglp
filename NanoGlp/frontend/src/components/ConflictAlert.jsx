import React, { useState } from 'react';
import {
  ShieldAlert,
  Clock,
  Lock,
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CalendarClock,
  UserCheck,
  Loader2,
  Wrench,
} from 'lucide-react';
import { conflictTypeLabel } from '../utils/format';

const iconFor = (type, severity) => {
  if (severity === 'WARNING') return AlertTriangle;
  if (type === 'BIOLOGICAL_TIME_VIOLATION') return Lock;
  if (type === 'PERSONNEL_OVERLAP') return Clock;
  return AlertOctagon;
};

const actionIconFor = (action) => {
  if (action === 'APPROVE_WEEKEND_DUTY') return CheckCircle2;
  if (action === 'ALIGN_EXTRACTION_TO_FRIDAY') return CalendarClock;
  if (action === 'REASSIGN_TO_BACKUP_TECHNICIAN') return UserCheck;
  if (action === 'SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE') return CalendarClock;
  return Wrench;
};

/**
 * FAZ 6.2: GLP Çakışma ve Hafta Sonu Uyarılarını gösterir ve her kartın içinde
 * doğrudan "Tek Tık Çözüm Butonları (Actionable Resolutions)" sunar.
 */
export default function ConflictAlert({
  conflicts = [],
  title,
  onApplyResolution,
  isReadOnly = false,
}) {
  const [busyKey, setBusyKey] = useState(null);

  if (!conflicts.length) return null;
  const criticalCount = conflicts.filter((c) => c.severity === 'CRITICAL').length;
  const warningCount = conflicts.filter((c) => c.severity === 'WARNING').length;
  const hasCritical = criticalCount > 0;

  const handleAction = async (conflictId, resolution) => {
    if (!onApplyResolution || isReadOnly) return;
    const key = `${conflictId}-${resolution.action}`;
    setBusyKey(key);
    try {
      await onApplyResolution(conflictId, resolution);
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div
      role="alert"
      className={`rounded-xl border-2 overflow-hidden shadow-sm ${
        hasCritical ? 'border-red-600 bg-red-50/90' : 'border-amber-500 bg-amber-50/90'
      }`}
    >
      <div
        className={`${
          hasCritical ? 'bg-red-600' : 'bg-amber-600'
        } text-white px-5 py-3.5 flex items-center justify-between gap-3`}
      >
        <div className="flex items-center gap-3">
          {hasCritical ? (
            <ShieldAlert className="w-6 h-6 shrink-0" />
          ) : (
            <AlertTriangle className="w-6 h-6 shrink-0" />
          )}
          <div>
            <p className="font-bold tracking-wide text-sm">
              {title ||
                (hasCritical
                  ? 'GLP KRİTİK ÇAKIŞMASI TESPİT EDİLDİ'
                  : 'GLP HAFTA SONU / MESAİ UYARISI — KARAR DESTEK SEÇENEKLERİ')}
            </p>
            <p className="text-xs text-white/90">
              {criticalCount} CRITICAL · {warningCount} WARNING — Takvim kendiliğinden kaydırılmadı; aşağıdaki Tek Tık
              Çözüm Butonları ile kararınızı uygulayabilirsiniz.
            </p>
          </div>
        </div>
      </div>

      <ul className={`divide-y ${hasCritical ? 'divide-red-200' : 'divide-amber-200'}`}>
        {conflicts.map((c) => {
          const type = c.type || c.conflict_type;
          const isWarn = c.severity === 'WARNING';
          const Icon = iconFor(type, c.severity);
          const resolutions = c.resolutions || [];

          return (
            <li key={c.id} className="px-5 py-4 flex gap-3.5">
              <Icon
                className={`w-5 h-5 mt-0.5 shrink-0 ${
                  isWarn ? 'text-amber-700' : 'text-red-700'
                }`}
              />
              <div className="space-y-2 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`text-[11px] font-bold px-2 py-0.5 rounded text-white ${
                      isWarn ? 'bg-amber-600' : 'bg-red-700'
                    }`}
                  >
                    {c.severity}
                  </span>
                  <span
                    className={`text-[11px] font-semibold px-2 py-0.5 rounded border bg-white ${
                      isWarn
                        ? 'border-amber-300 text-amber-900'
                        : 'border-red-300 text-red-800'
                    }`}
                  >
                    {conflictTypeLabel[type] || type}
                  </span>
                </div>

                <p className={`text-sm font-bold ${isWarn ? 'text-amber-950' : 'text-red-950'}`}>
                  {c.title}
                </p>
                <p className={`text-xs leading-relaxed ${isWarn ? 'text-amber-900' : 'text-red-900'}`}>
                  {c.description}
                </p>

                {!isReadOnly && onApplyResolution && resolutions.length > 0 && (
                  <div className="pt-2 flex flex-wrap items-center gap-2">
                    {resolutions.map((res) => {
                      const ActionIcon = actionIconFor(res.action);
                      const key = `${c.id}-${res.action}`;
                      const isBusy = busyKey === key;
                      const btnTone =
                        res.style === 'emerald'
                          ? 'bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-700'
                          : 'bg-blue-700 hover:bg-blue-800 text-white border-blue-800';

                      return (
                        <button
                          key={res.action}
                          type="button"
                          disabled={Boolean(busyKey)}
                          onClick={() => handleAction(c.id, res)}
                          title={res.description}
                          className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-md border shadow-sm transition disabled:opacity-50 ${btnTone}`}
                        >
                          {isBusy ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <ActionIcon className="w-3.5 h-3.5" />
                          )}
                          <span>{res.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
