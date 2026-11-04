import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ClipboardList,
  Clock,
  Lock,
  CheckCircle2,
  Play,
  Calendar,
  RefreshCw,
  AlertTriangle,
  FlaskConical,
  Save,
} from 'lucide-react';
import { getMyTasks, updateStepStatus, extractError } from '../services/api';
import { useAuth } from '../state/AuthContext';
import { usePreferences } from '../state/PreferencesContext';
import { fmtDateTime, fmtTime, fmtMinutes, todayISO, ROLE_LABEL } from '../utils/format';

const STATUS_BADGE = {
  PENDING: { label: 'Bekliyor', cls: 'bg-slate-100 text-slate-700 border-slate-200' },
  IN_PROGRESS: { label: 'Devam Ediyor', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  COMPLETED: { label: 'Tamamlandı', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  DELAYED: { label: 'Gecikti', cls: 'bg-red-50 text-red-700 border-red-200' },
};

function toLocalInputValue(isoStr) {
  if (!isoStr) return '';
  return String(isoStr).slice(0, 16);
}

function buildCompatibleBounds(task, refIso, targetStatus) {
  if (!refIso) return {};
  const refNorm = refIso.length === 16 ? `${refIso}:00` : refIso;
  const pStart = task.actual_start || task.planned_start || refNorm;
  const pEnd = task.actual_end || task.planned_end || refNorm;
  const effStart = refNorm < pStart ? refNorm : pStart;
  const effEnd = refNorm > pEnd ? refNorm : pEnd;
  if (targetStatus === 'IN_PROGRESS') {
    return { actual_start: effStart };
  }
  return {
    actual_start: effStart,
    actual_end: effEnd < effStart ? effStart : effEnd,
  };
}

export default function MyTasks() {
  const { user, isReadOnly } = useAuth();
  const { t, tr, lang, formatStatusBadge } = usePreferences();
  const [targetDate, setTargetDate] = useState(todayISO());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState(null);
  const [error, setError] = useState(null);
  const [refInputs, setRefInputs] = useState({});
  const [noteInputs, setNoteInputs] = useState({});
  const [savedNoticeId, setSavedNoticeId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getMyTasks(targetDate);
      const payload = res.data;
      setData(payload);
      const all = payload?.all_assigned_tasks || [];
      setRefInputs((prev) => {
        const next = { ...prev };
        for (const step of all) {
          if (step.actual_reference_time) {
            next[step.id] = toLocalInputValue(step.actual_reference_time);
          } else if (!next[step.id]) {
            next[step.id] = toLocalInputValue(
              step.expected_reference_time || step.planned_reference_time || step.planned_start
            );
          }
        }
        return next;
      });
      setNoteInputs((prev) => {
        const next = { ...prev };
        for (const step of all) {
          if (step.deviation_notes != null) {
            next[step.id] = step.deviation_notes;
          }
        }
        return next;
      });
    } catch (err) {
      setError(extractError(err, 'Görev listesi alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, [targetDate]);

  useEffect(() => {
    load();
  }, [load]);

  const handleStatusChange = async (taskOrId, nextStatus) => {
    if (isReadOnly) return;
    const taskObj =
      typeof taskOrId === 'object' && taskOrId !== null
        ? taskOrId
        : (data?.all_assigned_tasks || []).find((x) => x.id === taskOrId) || { id: taskOrId };
    const stepId = taskObj.id;
    setUpdatingId(stepId);
    setError(null);
    try {
      const body = { status: nextStatus };
      const refVal = (refInputs[stepId] || '').trim();
      const noteVal = (noteInputs[stepId] || '').trim();
      if (taskObj.requires_reference_time && refVal && nextStatus !== 'PENDING') {
        const refIso = refVal.length === 16 ? `${refVal}:00` : refVal;
        body.actual_reference_time = refIso;
        Object.assign(body, buildCompatibleBounds(taskObj, refIso, nextStatus));
      }
      if (noteVal) {
        body.deviation_notes = noteVal;
      }
      await updateStepStatus(stepId, body);
      setSavedNoticeId(stepId);
      await load();
    } catch (err) {
      setError(extractError(err, 'Görev durumu güncellenemedi.'));
    } finally {
      setUpdatingId(null);
    }
  };

  const handleSaveReferenceTime = async (task) => {
    if (isReadOnly) return;
    const stepId = task.id;
    const refVal = (refInputs[stepId] || '').trim();
    if (!refVal) {
      setError('Lütfen geçerli bir biyolojik referans / gözlem saati girin.');
      return;
    }
    setUpdatingId(stepId);
    setError(null);
    try {
      const refIso = refVal.length === 16 ? `${refVal}:00` : refVal;
      const effectiveStatus = task.status === 'PENDING' ? 'COMPLETED' : task.status;
      const body = {
        status: effectiveStatus,
        actual_reference_time: refIso,
        ...buildCompatibleBounds(task, refIso, effectiveStatus),
      };
      const noteVal = (noteInputs[stepId] || '').trim();
      if (noteVal) {
        body.deviation_notes = noteVal;
      }
      await updateStepStatus(stepId, body);
      setSavedNoticeId(stepId);
      await load();
    } catch (err) {
      setError(extractError(err, 'Biyolojik referans saati kaydedilemedi.'));
    } finally {
      setUpdatingId(null);
    }
  };

  const todaysTasks = data?.todays_tasks || [];
  const allAssignedTasks = data?.all_assigned_tasks || [];
  const workload = data?.today_workload || { total_minutes: 0, limit_minutes: 540, exceeds_limit: false };
  const limit = workload.limit_minutes || 540;
  const barPct = Math.min((workload.total_minutes / limit) * 100, 100);

  // Atanmış görevlerin bulunduğu benzersiz tarihler (hızlı geçiş için)
  const scheduledDates = useMemo(() => {
    const set = new Set(allAssignedTasks.map((t) => t.planned_start.slice(0, 10)));
    return Array.from(set).sort();
  }, [allAssignedTasks]);

  const lockedCount = allAssignedTasks.filter((t) => t.is_biological_fixed_time).length;

  const renderReferenceTimePanel = (task) => {
    if (!task.requires_reference_time) return null;
    const busy = updatingId === task.id;
    const devMin = task.deviation_minutes ?? task.reference_deviation_minutes ?? 0;
    const exceedsTol = Boolean(task.exceeds_biological_tolerance);
    const roleLabel =
      task.reference_time_label ||
      (task.reference_time_role === 'SOURCE'
        ? 'Uygulama / Enjeksiyon Referans Saati'
        : 'Gerçekleşen Gözlem / Ölçüm Saati');

    return (
      <div
        data-testid={`ref-time-panel-${task.id}`}
        className="mt-2.5 p-3 rounded-md bg-slate-50 border border-slate-200 space-y-2 text-xs"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-800">{roleLabel}</span>
            {task.planned_reference_time && (
              <span className="text-slate-500">
                Planlanan: <strong className="font-mono text-slate-700">{fmtDateTime(task.planned_reference_time)}</strong>
              </span>
            )}
            {task.expected_start && task.expected_start !== task.planned_start && (
              <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 font-medium">
                Beklenen Pencere: {fmtDateTime(task.expected_start)} – {fmtTime(task.expected_end)}
              </span>
            )}
          </div>

          {task.actual_reference_time ? (
            <div className="flex flex-wrap items-center gap-1.5" data-testid={`recorded-ref-time-${task.id}`}>
              <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200 font-mono font-semibold">
                Kaydedilen: {fmtDateTime(task.actual_reference_time)}
              </span>
              <span
                data-testid={`ref-deviation-badge-${task.id}`}
                className={`px-2 py-0.5 rounded font-semibold border ${
                  exceedsTol
                    ? 'bg-red-50 text-red-700 border-red-200'
                    : devMin !== 0
                    ? 'bg-amber-50 text-amber-800 border-amber-200'
                    : 'bg-blue-50 text-blue-700 border-blue-200'
                }`}
              >
                Sapma: {devMin > 0 ? `+${devMin}` : devMin} dk{' '}
                {exceedsTol ? '(Tolerans Aşımı!)' : `(±${task.biological_tolerance_minutes} dk içinde)`}
              </span>
            </div>
          ) : (
            <span className="text-amber-700 font-medium">
              Henüz gerçekleşen biyolojik referans / gözlem saati girilmedi
            </span>
          )}
        </div>

        {task.deviation_notes && (
          <p className="text-[11px] text-slate-600">
            <strong>Sapma / GLP Notu:</strong> {task.deviation_notes}
          </p>
        )}

        {task.revision_suggestion && (
          <p className="text-[11px] text-amber-800 bg-amber-50/70 px-2 py-1 rounded border border-amber-200">
            {task.revision_suggestion}
          </p>
        )}

        {!isReadOnly && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <label className="text-[11px] font-medium text-slate-600">
              Gerçekleşen Saat:
              <input
                type="datetime-local"
                data-testid={`ref-time-input-${task.id}`}
                value={refInputs[task.id] || ''}
                onChange={(e) =>
                  setRefInputs((prev) => ({
                    ...prev,
                    [task.id]: e.target.value,
                  }))
                }
                className="ml-1.5 border border-slate-300 rounded px-2 py-1 text-xs font-mono bg-white"
              />
            </label>
            <input
              type="text"
              data-testid={`deviation-note-input-${task.id}`}
              placeholder="Sapma / GLP açıklama notu (opsiyonel)"
              value={noteInputs[task.id] || ''}
              onChange={(e) =>
                setNoteInputs((prev) => ({
                  ...prev,
                  [task.id]: e.target.value,
                }))
              }
              className="border border-slate-300 rounded px-2.5 py-1 text-xs bg-white min-w-[220px] flex-1"
            />
            <button
              type="button"
              disabled={busy}
              data-testid={`save-ref-time-btn-${task.id}`}
              onClick={() => handleSaveReferenceTime(task)}
              className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" /> Referans Saatini Kaydet
            </button>
            {savedNoticeId === task.id && (
              <span className="text-[11px] font-semibold text-emerald-700">✓ Kaydedildi</span>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold text-slate-900">Bugünkü Görevlerim</h2>
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-50 text-blue-800 border border-blue-200">
              {user?.full_name} · {ROLE_LABEL[user?.role] || user?.role}
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-0.5">
            GLP protokollerine göre şahsınıza atanmış günlük uygulama, ekstraksiyon ve gözlem adımları.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="border border-slate-300 rounded-md px-3 py-2 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
          />
          <button
            type="button"
            onClick={() => setTargetDate(todayISO())}
            className="text-xs font-medium text-slate-700 border border-slate-300 bg-white rounded-md px-3 py-2 hover:bg-slate-50"
          >
            Bugün
          </button>
          <button
            type="button"
            onClick={load}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-600 border border-slate-300 bg-white rounded-md px-3 py-2 hover:bg-slate-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Yenile
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>
      )}

      {/* Özet Kartları */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-xs flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
              Seçilen Gün Görevleri ({targetDate})
            </p>
            <p className="text-2xl font-bold text-slate-900 mt-1">{todaysTasks.length}</p>
            <p className="text-xs text-slate-500 mt-1">
              Toplam {allAssignedTasks.length} atanmış çalışma adımı
            </p>
          </div>
          <div className="text-slate-400">
            <ClipboardList className="w-5 h-5" />
          </div>
        </div>

        <div
          className={`bg-white border rounded-lg p-5 shadow-xs ${
            workload.exceeds_limit ? 'border-red-500 bg-red-50/40' : 'border-slate-200'
          }`}
        >
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Günlük İş Yükü (9 Saat Sınırı)</p>
              <p className={`text-2xl font-bold mt-1 ${workload.exceeds_limit ? 'text-red-700' : 'text-slate-900'}`}>
                {fmtMinutes(workload.total_minutes)}{' '}
                <span className="text-xs font-normal text-slate-500">/ {fmtMinutes(limit)}</span>
              </p>
            </div>
            <div className={workload.exceeds_limit ? 'text-red-600' : 'text-slate-400'}>
              <Clock className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full ${workload.exceeds_limit ? 'bg-red-600' : 'bg-blue-600'}`}
              style={{ width: `${barPct}%` }}
            />
          </div>
          {workload.exceeds_limit && (
            <p className="mt-1.5 text-[11px] font-semibold text-red-700 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5" /> 9 saatlik GLP üst sınırı aşıldı!
            </p>
          )}
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-5 shadow-xs flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Biyolojik Kilitli Adımlar</p>
            <p className="text-2xl font-bold text-blue-800 mt-1">{lockedCount}</p>
            <p className="text-xs text-slate-500 mt-1">Tolerans dışına çıkılamaz, saat kaydırılamaz</p>
          </div>
          <div className="text-slate-400">
            <Lock className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Hızlı Tarih Geçiş Çubuğu (görev olan günler) */}
      {scheduledDates.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg px-4 py-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-500 font-medium flex items-center gap-1.5 mr-1">
            <Calendar className="w-3.5 h-3.5 text-slate-500" />
            Görev bulunan tarihler:
          </span>
          {scheduledDates.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setTargetDate(d)}
              className={`px-2.5 py-1 rounded font-mono transition ${
                d === targetDate
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      )}

      {/* Seçilen Günün Görevleri */}
      <section className="bg-white border border-slate-200 rounded-lg shadow-xs">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-800">
              {targetDate === todayISO() ? 'Bugünkü Görev Programım' : `${targetDate} Tarihli Görev Programım`}
            </h3>
          </div>
          <span className="text-xs text-slate-500">{todaysTasks.length} görev</span>
        </div>

        {todaysTasks.length === 0 ? (
          <div className="p-8 text-center space-y-2">
            <p className="text-sm text-slate-500">
              {loading ? 'Görevler yükleniyor…' : `${targetDate} tarihinde şahsınıza atanmış görev bulunmuyor.`}
            </p>
            {!loading && scheduledDates.length > 0 && (
              <p className="text-xs text-blue-700">
                Yukarıdaki tarih kısayollarından veya aşağıdaki tüm görevler tablosundan planlı günlerinize geçebilirsiniz.
              </p>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {todaysTasks.map((task) => {
              const badge = STATUS_BADGE[task.status] || STATUS_BADGE.PENDING;
              const busy = updatingId === task.id;
              return (
                <li key={task.id} className="px-5 py-4 hover:bg-slate-50">
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-800 border border-blue-200">
                          {task.study_code}
                        </span>
                        <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                          Gün {task.study_day}
                        </span>
                        {task.study_status === 'DRAFT' && (
                          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                            TASLAK PLAN
                          </span>
                        )}
                        {task.is_biological_fixed_time && (
                          <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-50 text-indigo-800 border border-indigo-200">
                            <Lock className="w-3 h-3" /> Biyolojik Kilitli (±{task.biological_tolerance_minutes} dk)
                          </span>
                        )}
                        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded border ${badge.cls}`}>
                          {badge.label}
                        </span>
                      </div>
                      <p className="text-sm font-semibold text-slate-900">{task.step_name}</p>
                      <p className="text-xs text-slate-500">
                        Saat: <strong className="text-slate-700">{fmtTime(task.planned_start)} – {fmtTime(task.planned_end)}</strong>
                        {' · '}Süre: {fmtMinutes(task.duration_minutes)}
                        {' · '}Görevliler: {task.assignee_names?.join(', ')}
                      </p>
                    </div>

                    {!isReadOnly && (
                      <div className="flex items-center gap-2">
                        {task.status === 'PENDING' && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleStatusChange(task, 'IN_PROGRESS')}
                            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-slate-900 hover:bg-slate-800 text-white disabled:opacity-50"
                          >
                            <Play className="w-3.5 h-3.5" /> Başlat
                          </button>
                        )}
                        {task.status !== 'COMPLETED' && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleStatusChange(task, 'COMPLETED')}
                            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" /> Tamamla
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  {renderReferenceTimePanel(task)}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* Atanmış Tüm Çalışma Adımları */}
      <section className="bg-white border border-slate-200 rounded-lg shadow-xs">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-800">Atandığım Tüm Çalışma Adımları (Takvim Özeti)</h3>
          </div>
          <span className="text-xs text-slate-500">{allAssignedTasks.length} adım</span>
        </div>

        {allAssignedTasks.length === 0 ? (
          <p className="p-8 text-center text-sm text-slate-400">
            Şu anda üzerinize atanmış aktif bir GLP çalışma adımı bulunmuyor.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left px-5 py-3 font-semibold">Tarih / Saat</th>
                  <th className="text-left px-5 py-3 font-semibold">Çalışma</th>
                  <th className="text-left px-5 py-3 font-semibold">Gün / Adım</th>
                  <th className="text-left px-5 py-3 font-semibold">Süre & Kilit</th>
                  <th className="text-left px-5 py-3 font-semibold">Durum</th>
                  {!isReadOnly && <th className="text-right px-5 py-3 font-semibold">İşlem</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {allAssignedTasks.map((t) => {
                  const badge = STATUS_BADGE[t.status] || STATUS_BADGE.PENDING;
                  const busy = updatingId === t.id;
                  const stepDate = t.planned_start.slice(0, 10);
                  const devMin = t.deviation_minutes ?? t.reference_deviation_minutes ?? 0;
                  return (
                    <tr key={t.id} className="hover:bg-slate-50">
                      <td className="px-5 py-3 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => setTargetDate(stepDate)}
                          className="text-left font-medium text-blue-700 hover:underline"
                        >
                          {fmtDateTime(t.planned_start)}
                        </button>
                        {t.actual_reference_time && (
                          <div className="text-[11px] font-mono text-emerald-700 mt-0.5">
                            Ref: {fmtDateTime(t.actual_reference_time)} ({devMin > 0 ? `+${devMin}` : devMin} dk)
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3 font-mono text-xs text-slate-700">
                        {t.study_code}
                        {t.study_status === 'DRAFT' && (
                          <span className="ml-1.5 font-sans text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                            TASLAK
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-slate-800">
                        <span className="font-mono text-[10px] px-1.5 py-0.5 mr-1.5 rounded bg-slate-100 text-slate-600">
                          G{t.study_day}
                        </span>
                        {t.step_name}
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-600 whitespace-nowrap">
                        {fmtMinutes(t.duration_minutes)}
                        {t.is_biological_fixed_time && (
                          <span className="ml-2 inline-flex items-center gap-1 text-blue-700 font-medium">
                            <Lock className="w-3 h-3" /> ±{t.biological_tolerance_minutes} dk
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded border ${badge.cls}`}>
                          {badge.label}
                        </span>
                      </td>
                      {!isReadOnly && (
                        <td className="px-5 py-3 text-right whitespace-nowrap">
                          {t.status !== 'COMPLETED' ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                handleStatusChange(t, t.status === 'PENDING' ? 'IN_PROGRESS' : 'COMPLETED')
                              }
                              className="text-xs font-medium text-blue-700 hover:text-blue-900 disabled:opacity-40"
                            >
                              {t.status === 'PENDING' ? 'Başlat' : 'Tamamla'}
                            </button>
                          ) : (
                            <span className="text-xs text-emerald-600 font-medium">✓ Tamamlandı</span>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
