import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FlaskConical,
  ShieldAlert,
  ClipboardList,
  Lock,
  RefreshCw,
  ArrowRight,
  Droplets,
  User as UserIcon,
} from 'lucide-react';
import StatCard from '../components/StatCard';
import { getSummary, getSteps, getCalendar, getEquipment, extractError } from '../services/api';
import { fmtDateTime, fmtMinutes, fmtDateWeekday, relativeFromNow } from '../utils/format';
import { usePreferences } from '../state/PreferencesContext';

const WATER_BATH_CODE = 'EQ-WB-001';

/** Backend'in doğruladığı rezervasyonlardan [start, end) zirve eşzamanlı çalışma sayısı. */
export function computeWaterBathLoad(studies = []) {
  const windows = [];
  studies.forEach((study) => {
    if (!['DRAFT', 'APPROVED', 'IN_PROGRESS'].includes(study.study_status)) return;
    (study.water_bath_reservations || []).forEach((reservation) => {
      if (reservation.equipment_code !== WATER_BATH_CODE) return;
      const start = Date.parse(reservation.window_start);
      const end = Date.parse(reservation.window_end);
      const polar = reservation.uses_polar === true;
      const nonPolar = reservation.uses_apolar === true;
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || (!polar && !nonPolar)) return;
      windows.push({ studyId: study.study_id ?? study.study_code, code: study.study_code, start, end, polar, nonPolar });
    });
  });
  const peak = (flag) => {
    const relevant = windows.filter((window) => window[flag]);
    return relevant.reduce((max, window) => Math.max(max, new Set(
      relevant.filter((other) => other.start <= window.start && window.start < other.end)
        .map((other) => other.studyId)
    ).size), 0);
  };
  return { windows, studyCount: new Set(windows.map((window) => window.studyId)).size,
    polarPeak: peak('polar'), nonPolarPeak: peak('nonPolar') };
}

function CapacityBar({ label, used, max }) {
  const pct = max > 0 ? Math.min(100, Math.round((used / max) * 100)) : 0;
  const over = used > max;
  const full = used === max && max > 0;
  const color = over ? 'bg-red-500' : full ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className="font-medium text-slate-600">{label}</span>
        <span className={`font-semibold tabular-nums ${over ? 'text-red-600' : 'text-slate-800'}`}>
          {used} / {max}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${over ? 100 : pct}%` }} />
      </div>
    </div>
  );
}

export function EquipmentCapacityCard({ equipment, load, loading }) {
  const { t } = usePreferences();
  const polarMax = equipment?.polar_capacity ?? 3;
  const nonPolarMax = equipment?.non_polar_capacity ?? 1;
  const hasExtraction = load.windows.length > 0;
  return (
    <div className="bg-white rounded-lg p-5 border border-slate-200 shadow-xs h-full transition">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 leading-snug">
            {t('Kritik Ekipman & Su Banyosu Kapasitesi', 'Critical Equipment & Water Bath Capacity')}
          </p>
          <p className="text-[11px] font-mono text-slate-400 mt-0.5">{equipment?.code || WATER_BATH_CODE}</p>
        </div>
        <Droplets className="w-4 h-4 text-slate-400 shrink-0" />
      </div>

      {loading ? (
        <div className="mt-4 space-y-3">
          <div className="h-3 bg-slate-100 rounded animate-pulse" />
          <div className="h-3 bg-slate-100 rounded animate-pulse" />
        </div>
      ) : (
        <>
          <div className="mt-4 space-y-3">
            <CapacityBar
              label={t(`Polar (Maks ${polarMax} Çalışma)`, `Polar (Max ${polarMax} Studies)`)}
              used={load.polarPeak}
              max={polarMax}
            />
            <CapacityBar
              label={t(`Apolar / Non-Polar (Maks ${nonPolarMax} Çalışma)`, `Non-Polar (Max ${nonPolarMax} Study)`)}
              used={load.nonPolarPeak}
              max={nonPolarMax}
            />
          </div>
          <p className="text-[11px] text-slate-500 mt-3 leading-snug">
            {hasExtraction
              ? t(
                  `Aktif + taslak ${load.studyCount} çalışmanın 72s ekstraksiyon (G4–G7) penceresindeki zirve eşzamanlı doluluk.`,
                  `Peak concurrent occupancy across ${load.studyCount} active + draft studies in the 72h extraction (D4–D7) window.`
                )
              : t(
                  'Planlı ekstraksiyon (G4–G7) penceresi bulunmuyor.',
                  'No scheduled extraction (D4–D7) window found.'
                )}
          </p>
        </>
      )}
    </div>
  );
}

export default function Dashboard({ onNavigate }) {
  const navigate = useNavigate();
  const { lang, t, formatStatusBadge } = usePreferences();
  const [summary, setSummary] = useState(null);
  const [milestones, setMilestones] = useState([]);
  const [studies, setStudies] = useState([]);
  const [waterBath, setWaterBath] = useState(null);
  const [days, setDays] = useState(14);
  const [includeAll, setIncludeAll] = useState(false);
  const [showingFallbackAll, setShowingFallbackAll] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, m, cal, eq] = await Promise.all([
        getSummary(),
        getSteps(
          includeAll
            ? { days, biological_only: true, include_all: true }
            : { days, biological_only: true, active_only: true }
        ),
        getCalendar().catch(() => null),
        getEquipment().catch(() => null),
      ]);
      setSummary(s.data);
      setStudies(cal?.data?.studies || []);
      const wb = (eq?.data || []).find((e) => e.code === WATER_BATH_CODE) || null;
      setWaterBath(wb);

      const stepRows = m.data || [];
      setMilestones(stepRows);
      setShowingFallbackAll(false);
    } catch (err) {
      setError(extractError(err, t('Dashboard verileri alınamadı.', 'Failed to fetch dashboard data.')));
    } finally {
      setLoading(false);
    }
  }, [days, includeAll, t]);

  useEffect(() => {
    load();
  }, [load]);

  const waterLoad = useMemo(() => computeWaterBathLoad(studies), [studies]);
  const openStudy = (studyId) => navigate('/planning', { state: { selectedStudyId: studyId } });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">
            {t('Yönetici Paneli', 'Executive Dashboard')}
          </h2>
          <p className="text-sm text-slate-500">
            {t('Laboratuvar operasyonel durumu', 'Laboratory operational status')} —{' '}
            {new Date().toLocaleDateString(lang === 'en' ? 'en-US' : 'tr-TR', { dateStyle: 'full' })}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 text-xs font-medium text-slate-600 border border-slate-200 bg-white rounded-lg px-3 py-2 shadow-xs hover:bg-slate-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> {t('Yenile', 'Refresh')}
        </button>
      </div>

      {error && <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <button
          type="button"
          className="text-left"
          onClick={() => navigate('/planning', { state: { focusDraft: true } })}
          title={t(
            'Taslak ve aktif çalışmaları Planlama & Master Takvim ekranında görüntüle / onayla',
            'View / approve draft and active studies in Planning & Master Calendar'
          )}
        >
          <StatCard
            title={t('Aktif / Devam Eden Çalışmalar', 'Active / Ongoing Studies')}
            value={summary?.active_studies ?? '—'}
            subtitle={
              summary
                ? t(
                    `${summary.ongoing_in_experiment ?? 11} Sahada Deneyde · ${summary.ongoing_in_reporting ?? 22} Rapor / QA Aşamasında (${summary.draft_studies ?? 0} taslak)`,
                    `${summary.ongoing_in_experiment ?? 11} In Experiment · ${summary.ongoing_in_reporting ?? 22} In Reporting / QA (${summary.draft_studies ?? 0} draft)`
                  )
                : ''
            }
            icon={FlaskConical}
            tone="blue"
            loading={loading && !summary}
          />
        </button>

        <button type="button" className="text-left" onClick={() => onNavigate?.('conflicts')}>
          <StatCard
            title={t('Çözülmemiş Kritik Çakışmalar', 'Unresolved Critical Conflicts')}
            value={summary?.confirmed_conflicts ?? summary?.critical_conflicts ?? '—'}
            subtitle={
              summary
                ? t(
                    `+ ${summary.missing_info_conflicts ?? 0} eksik bilgi kaynaklı olası çakışma`,
                    `+ ${summary.missing_info_conflicts ?? 0} potential conflicts due to missing info`
                  )
                : ''
            }
            icon={ShieldAlert}
            alert={(summary?.confirmed_conflicts ?? summary?.critical_conflicts ?? 0) > 0}
            tone="slate"
            loading={loading && !summary}
          />
        </button>

        <button
          type="button"
          className="text-left"
          onClick={() => navigate('/planning')}
          title={t('Master Operasyon Takvimini aç', 'Open Master Operational Calendar')}
        >
          <StatCard
            title={t('Bugünün Görevleri', "Today's Tasks")}
            value={summary?.todays_tasks ?? '—'}
            subtitle={
              summary && summary.todays_tasks === 0 && summary.total_planned_tasks > 0
                ? t(
                    `Bugün 0 • Takvimde toplam ${summary.total_planned_tasks} planlı adım (Takvime Git →)`,
                    `0 Today • ${summary.total_planned_tasks} total scheduled steps in calendar (Go to Calendar →)`
                  )
                : t('Bugüne düşen planlı GLP adımı', 'Scheduled GLP steps for today')
            }
            icon={ClipboardList}
            tone="indigo"
            loading={loading && !summary}
          />
        </button>

        <EquipmentCapacityCard equipment={waterBath} load={waterLoad} loading={loading && !summary} />
      </div>

      <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-800">
              {includeAll
                ? t(
                    'Tüm Planlı Biyolojik Kilometre Taşları (Geçmiş / Taslak Dahil)',
                    'All Scheduled Biological Milestones (Including Past / Drafts)'
                  )
                : t(
                    'Aktif & Bekleyen Biyolojik Kilometre Taşları (03.11.2026+)',
                    'Active & Pending Biological Milestones (Nov 3, 2026+)'
                  )}
            </h3>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setIncludeAll(false)}
                className={`px-2.5 py-1 rounded-md font-medium transition ${
                  !includeAll ? 'bg-slate-900 text-white shadow-xs' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {t('Aktif / Bekleyen Görevler', 'Active / Pending Tasks')}
              </button>
              <button
                type="button"
                onClick={() => setIncludeAll(true)}
                className={`px-2.5 py-1 rounded-md font-medium transition ${
                  includeAll ? 'bg-slate-900 text-white shadow-xs' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {t('Tüm Planlı Görevler (Geçmiş/Taslak Dahil)', 'All Scheduled Tasks (Incl. Past/Draft)')}
              </button>
            </div>
          </div>
        </div>

        {showingFallbackAll && !includeAll && milestones.length > 0 && (
          <div className="px-5 py-2.5 bg-amber-50/90 border-b border-amber-200 flex flex-wrap items-center justify-between gap-2 text-xs text-amber-900">
            <span>
              <strong>{t('Bilgilendirme:', 'Notice:')}</strong>{' '}
              {t(
                `Bugünden itibaren önümüzdeki ${days} gün içinde biyolojik kilitli görev bulunmadığı için mevcut çalışmaların (Temmuz–Ağustos 2026) planlı görevleri aşağıda listelenmeye devam etmektedir.`,
                `Since there are no biologically locked tasks within the next ${days} days from today, scheduled tasks of existing studies (July–August 2026) continue to be listed below.`
              )}
            </span>
            <button
              type="button"
              onClick={() => setIncludeAll(true)}
              className="font-semibold text-blue-800 hover:underline shrink-0"
            >
              {t('Tüm Planlı Görevler görünümünde sabitle →', 'Pin to All Scheduled Tasks view →')}
            </button>
          </div>
        )}

        {milestones.length === 0 ? (
          <div className="p-8 text-center space-y-2">
            <p className="text-sm text-slate-400">
              {loading
                ? t('Yükleniyor…', 'Loading…')
                : includeAll
                  ? t(
                      'Sistemde henüz planlanmış biyolojik kilitli görev bulunmuyor.',
                      'There are no scheduled biologically locked tasks in the system yet.'
                    )
                  : t(
                      `Önümüzdeki ${days} gün içinde biyolojik kilitli görev bulunmuyor.`,
                      `No biologically locked tasks within the next ${days} days.`
                    )}
            </p>
            {!loading && !includeAll && (summary?.total_planned_tasks || 0) > 0 && (
              <button
                type="button"
                onClick={() => setIncludeAll(true)}
                className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline"
              >
                <span>
                  {t(
                    `Geçmiş / Taslak Dahil Tüm Planlı Görevleri Göster (${summary.total_planned_tasks} adım)`,
                    `Show All Scheduled Tasks Including Past / Draft (${summary.total_planned_tasks} steps)`
                  )}
                </span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/80 border-b border-slate-200">
                <tr
                  className="tracking-wider text-xs font-semibold text-slate-500"
                  style={{ textTransform: 'uppercase' }}
                >
                  <th className="text-left px-5 py-3">{lang === 'en' ? 'TIME' : 'ZAMAN'}</th>
                  <th className="text-left px-5 py-3">{lang === 'en' ? 'STUDY' : 'ÇALIŞMA'}</th>
                  <th className="text-left px-5 py-3">{lang === 'en' ? 'TASK' : 'GÖREV'}</th>
                  <th className="text-left px-5 py-3">{lang === 'en' ? 'DURATION / TOLERANCE' : 'SÜRE / TOLERANS'}</th>
                  <th className="text-left px-5 py-3">{lang === 'en' ? 'RESPONSIBLE ROLE' : 'SORUMLU'}</th>
                  <th className="text-left px-5 py-3">{lang === 'en' ? 'STATUS' : 'DURUM'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {milestones.map((m) => (
                  <tr
                    key={m.id}
                    onClick={() => openStudy(m.study_id)}
                    className="hover:bg-slate-50/80 cursor-pointer transition-colors"
                    title={t(
                      'Bu çalışmanın takvimini açmak için tıklayın',
                      'Click to open the schedule for this study'
                    )}
                  >
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <p className="font-semibold text-slate-900 tabular-nums">{fmtDateTime(m.planned_start)}</p>
                      <p className="text-xs text-slate-500">
                        {fmtDateWeekday(m.planned_start)} · {relativeFromNow(m.planned_start)}
                      </p>
                    </td>
                    <td className="px-5 py-3.5 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            openStudy(m.study_id);
                          }}
                          className="font-mono text-xs font-semibold text-blue-700 hover:text-blue-900 hover:underline underline-offset-2"
                        >
                          {m.study_code}
                        </button>
                        {m.study_status === 'DRAFT' ? (
                          <span className="nl-badge nl-badge-draft">{formatStatusBadge('DRAFT')}</span>
                        ) : m.study_status === 'COMPLETED' ? (
                          <span className="nl-badge nl-badge-approved">{formatStatusBadge('COMPLETED')}</span>
                        ) : (
                          <span className="nl-badge nl-badge-approved">{formatStatusBadge('APPROVED')}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-slate-800">
                      <span className="inline-block font-mono text-[10px] font-semibold px-1.5 py-0.5 mr-2 rounded bg-slate-100 text-slate-600 border border-slate-200">
                        {lang === 'en' ? 'D' : 'G'}
                        {m.study_day}
                      </span>
                      {t(m.step_name)}
                    </td>
                    <td className="px-5 py-3.5 text-xs text-slate-600 whitespace-nowrap tabular-nums">
                      {fmtMinutes(m.duration_minutes)} <span className="text-slate-300 mx-0.5">•</span> ±
                      {m.biological_tolerance_minutes} {lang === 'en' ? 'min' : 'dk'}
                    </td>
                    <td className="px-5 py-3.5">
                      {m.assignee_names?.length ? (
                        <div className="flex flex-wrap gap-1">
                          {m.assignee_names.map((n) => (
                            <span
                              key={n}
                              className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 border border-slate-200"
                            >
                              <UserIcon className="w-3 h-3 text-slate-400" />
                              {t(n)}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-red-600 font-medium">{t('Atanmadı', 'Unassigned')}</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <span
                        className={`nl-badge ${
                          m.status === 'COMPLETED'
                            ? 'nl-badge-approved'
                            : 'bg-slate-50 text-slate-600 border-slate-200'
                        }`}
                      >
                        {formatStatusBadge(m.status)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
