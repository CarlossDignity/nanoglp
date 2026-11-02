import React, { useMemo, useState } from 'react';
import {
  ShieldAlert,
  Lock,
  AlertTriangle,
  CheckCircle2,
  CalendarClock,
  UserCheck,
  Loader2,
  Wrench,
  Users,
  Clock,
} from 'lucide-react';
import { conflictTypeLabel, fmtDateWeekday } from '../utils/format';

/** Çakışma tipi + önem derecesine göre net kategori rozeti metni */
const categoryLabel = (type, severity) => {
  if (type === 'EQUIPMENT_OVERLAP') return 'CİHAZ KAPASİTE KİLİDİ';
  if (type === 'BIOLOGICAL_TIME_VIOLATION') {
    return severity === 'WARNING' ? 'HAFTA SONU NÖBET ONAYI GEREKLİ' : 'BİYOLOJİK ZAMAN KİLİDİ İHLALİ';
  }
  if (type === 'PERSONNEL_OVERLAP') return 'PERSONEL İŞ YÜKÜ / ÇAKIŞMA';
  if (type === 'QUALIFICATION_MISMATCH') return 'ATANACAK PERSONEL YOK';
  return (conflictTypeLabel[type] || type || 'ÇAKIŞMA').toUpperCase();
};

/** Yumuşak renkli ikon dairesi için ikon seçimi */
const iconFor = (type, severity) => {
  if (severity === 'WARNING') return CalendarClock;
  if (type === 'EQUIPMENT_OVERLAP') return Wrench;
  if (type === 'BIOLOGICAL_TIME_VIOLATION') return Lock;
  if (type === 'PERSONNEL_OVERLAP') return Users;
  return Clock;
};

const actionIconFor = (action) => {
  if (action === 'APPROVE_WEEKEND_DUTY') return CheckCircle2;
  if (action === 'ALIGN_EXTRACTION_TO_FRIDAY') return CalendarClock;
  if (action === 'REASSIGN_TO_BACKUP_TECHNICIAN') return UserCheck;
  if (action === 'SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE') return CalendarClock;
  if (action === 'SHIFT_TO_NEXT_AVAILABLE_CAPACITY_DATE') return CalendarClock;
  return Wrench;
};

/**
 * FAZ 7 — "Important Alerts Card" tasarım dili:
 * sol ikon dairesi · kategori + etkilenen adım rozetleri · açıklama · hiyerarşik tek tık çözüm butonları.
 * `steps` verilirse etkilenen adım rozeti (örn. "G9 • 08.08.2026 Cmt") gösterilir.
 */
export default function ConflictAlert({
  conflicts = [],
  title,
  onApplyResolution,
  isReadOnly = false,
  steps = [],
}) {
  const [busyKey, setBusyKey] = useState(null);
  const stepMap = useMemo(() => new Map((steps || []).map((s) => [s.id, s])), [steps]);

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
      className={`rounded-lg border bg-white shadow-xs overflow-hidden ${
        hasCritical ? 'border-red-200' : 'border-amber-200'
      }`}
    >
      {/* Başlık şeridi */}
      <div
        className={`px-5 py-3.5 flex flex-wrap items-center justify-between gap-3 border-b ${
          hasCritical ? 'bg-red-50/70 border-red-100' : 'bg-amber-50/70 border-amber-100'
        }`}
      >
        <div className="flex items-center gap-3">
          <span className={hasCritical ? 'text-red-600' : 'text-amber-600'}>
            {hasCritical ? <ShieldAlert className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          </span>
          <div>
            <p className={`text-sm font-semibold tracking-tight ${hasCritical ? 'text-red-900' : 'text-amber-900'}`}>
              {title ||
                (hasCritical ? 'GLP kritik çakışması tespit edildi' : 'GLP hafta sonu / mesai uyarısı — karar destek seçenekleri')}
            </p>
            <p className="text-xs text-slate-500">
              Takvim kendiliğinden kaydırılmadı; kararınızı aşağıdaki tek tık çözüm seçenekleriyle uygulayın.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px] font-semibold">
          {criticalCount > 0 && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-red-200 bg-white text-red-800">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
              <span className="font-mono">{criticalCount}</span> CRITICAL
            </span>
          )}
          {warningCount > 0 && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border border-amber-200 bg-white text-amber-800">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="font-mono">{warningCount}</span> WARNING
            </span>
          )}
        </div>
      </div>

      {/* Uyarı kartları */}
      <ul className="p-3 space-y-3 bg-slate-50/50">
        {conflicts.map((c) => {
          const type = c.type || c.conflict_type;
          const isWarn = c.severity === 'WARNING';
          const Icon = iconFor(type, c.severity);
          const resolutions = c.resolutions || [];
          const stepIds = c.step_ids && c.step_ids.length ? c.step_ids : c.step_id ? [c.step_id] : [];
          const affected = stepIds.map((id) => stepMap.get(id)).filter(Boolean);
          const showActions = !isReadOnly && onApplyResolution && resolutions.length > 0;

          return (
            <li
              key={c.id}
              className={`bg-white rounded-lg border shadow-xs p-4 flex gap-3 border-l-2 ${
                isWarn ? 'border-slate-200 border-l-amber-400' : 'border-slate-200 border-l-red-500'
              }`}
            >
              <span className={`shrink-0 mt-0.5 ${isWarn ? 'text-amber-600' : 'text-red-600'}`}>
                <Icon className="w-4 h-4" />
              </span>

              <div className="flex-1 min-w-0 space-y-2.5">
                {/* Rozetler */}
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-slate-700">
                    <span className={`w-1.5 h-1.5 rounded-full ${isWarn ? 'bg-amber-400' : 'bg-red-500'}`} />
                    {c.severity}
                  </span>
                  <span
                    className={`text-[11px] font-semibold tracking-wide px-2 py-0.5 rounded-md border ${
                      isWarn
                        ? 'bg-amber-50 text-amber-800 border-amber-200'
                        : 'bg-red-50 text-red-800 border-red-200'
                    }`}
                  >
                    {categoryLabel(type, c.severity)}
                  </span>
                  {affected.map((s) => (
                    <span
                      key={s.id}
                      className="text-[11px] font-mono font-medium px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 border border-slate-200"
                    >
                      G{s.study_day} • {fmtDateWeekday(s.planned_start)}
                    </span>
                  ))}
                </div>

                <div>
                  <p className="text-sm font-semibold text-slate-900 leading-snug">{c.title}</p>
                  <p className="text-xs text-slate-600 leading-relaxed mt-1">{c.description}</p>
                </div>

                {showActions && (
                  <div className="pt-1">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                      Tek tık çözüm seçenekleri
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      {resolutions.map((res, idx) => {
                        const ActionIcon = actionIconFor(res.action);
                        const key = `${c.id}-${res.action}`;
                        const isBusy = busyKey === key;
                        const primary = idx === 0;
                        const tone = primary
                          ? res.style === 'emerald'
                            ? 'bg-slate-900 hover:bg-slate-800 text-white border-slate-900'
                            : 'bg-slate-900 hover:bg-slate-800 text-white border-slate-900'
                          : 'bg-white hover:bg-slate-50 text-slate-700 border-slate-300';

                        return (
                          <button
                            key={res.action}
                            type="button"
                            disabled={Boolean(busyKey)}
                            onClick={() => handleAction(c.id, res)}
                            title={res.description}
                            className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded border transition disabled:opacity-50 ${tone}`}
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
