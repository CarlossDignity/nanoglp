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

const HOUR_MS = 3600 * 1000;
const WATER_BATH_CODE = 'EQ-WB-001';

/** Ekstraksiyon (G4–G7, 72 saat) pencerelerinden polar / apolar eşzamanlı zirve doluluğu hesaplar. */
function computeWaterBathLoad(studies = []) {
  const windows = [];
  studies.forEach((st) => {
    const ex = (st.steps || []).find((s) => s.step_type === 'Ekstraksiyon' || /ekstraksiyon/i.test(s.step_name || ''));
    if (!ex) return;
    const start = new Date(ex.planned_start).getTime();
    windows.push({
      code: st.study_code,
      status: st.study_status,
      start,
      end: start + 72 * HOUR_MS,
      polar: st.extraction_polar === true,
      nonPolar: st.extraction_non_polar === true,
      day: ex.study_day,
      iso: ex.planned_start,
    });
  });
  const peak = (flag) => {
    let max = 0;
    windows
      .filter((w) => w[flag])
      .forEach((w) => {
        const concurrent = windows.filter((o) => o[flag] && o.start <= w.start && o.end > w.start).length;
        max = Math.max(max, concurrent);
      });
    return max;
  };
  return { windows, polarPeak: peak('polar'), nonPolarPeak: peak('nonPolar') };
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

function EquipmentCapacityCard({ equipment, load, loading }) {
  const polarMax = equipment?.polar_capacity ?? 3;
  const nonPolarMax = equipment?.non_polar_capacity ?? 1;
  const hasExtraction = load.windows.length > 0;
  return (
    <div className="bg-white rounded-lg p-5 border border-slate-200 shadow-xs h-full transition ">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 leading-snug">
            Kritik Ekipman & Su Banyosu Kapasitesi
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
            <CapacityBar label={`Polar (Maks ${polarMax} Çalışma)`} used={load.polarPeak} max={polarMax} />
            <CapacityBar label={`Apolar / Non-Polar (Maks ${nonPolarMax} Çalışma)`} used={load.nonPolarPeak} max={nonPolarMax} />
          </div>
          <p className="text-[11px] text-slate-500 mt-3 leading-snug">
            {hasExtraction
              ? `Aktif + taslak ${load.windows.length} çalışmanın 72s ekstraksiyon (G4–G7) penceresindeki zirve eşzamanlı doluluk.`
              : 'Planlı ekstraksiyon (G4–G7) penceresi bulunmuyor.'}
          </p>
        </>
      )}
    </div>
  );
}

export default function Dashboard({ onNavigate }) {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [milestones, setMilestones] = useState([]);
  const [studies, setStudies] = useState([]);
  const [waterBath, setWaterBath] = useState(null);
  const [days, setDays] = useState(14);
  const [includeAll, setIncludeAll] = useState(true);
  const [showingFallbackAll, setShowingFallbackAll] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, m, cal, eq] = await Promise.all([
        getSummary(),
        getSteps({ days, biological_only: true, include_all: includeAll }),
        getCalendar().catch(() => null),
        getEquipment().catch(() => null),
      ]);
      setSummary(s.data);
      setStudies(cal?.data?.studies || []);
      const wb = (eq?.data || []).find((e) => e.code === WATER_BATH_CODE) || null;
      setWaterBath(wb);

      const stepRows = m.data || [];
      if (!includeAll && stepRows.length === 0 && (s.data?.total_planned_tasks || 0) > 0) {
        const allRes = await getSteps({ days, biological_only: true, include_all: true });
        setMilestones(allRes.data || []);
        setShowingFallbackAll(true);
      } else {
        setMilestones(stepRows);
        setShowingFallbackAll(false);
      }
    } catch (err) {
      setError(extractError(err, 'Dashboard verileri alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, [days, includeAll]);

  useEffect(() => {
    load();
  }, [load]);

  const waterLoad = useMemo(() => computeWaterBathLoad(studies), [studies]);
  const openStudy = (studyId) => navigate('/planning', { state: { selectedStudyId: studyId } });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">Yönetici Paneli</h2>
          <p className="text-sm text-slate-500">
            Laboratuvar operasyonel durumu — {new Date().toLocaleDateString('tr-TR', { dateStyle: 'full' })}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 text-xs font-medium text-slate-600 border border-slate-200 bg-white rounded-lg px-3 py-2 shadow-xs hover:bg-slate-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Yenile
        </button>
      </div>

      {error && <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <button
          type="button"
          className="text-left"
          onClick={() => navigate('/planning', { state: { focusDraft: true } })}
          title="Taslak ve aktif çalışmaları Planlama & Master Takvim ekranında görüntüle / onayla"
        >
          <StatCard
            title="Aktif Çalışmalar"
            value={summary?.active_studies ?? '—'}
            subtitle={
              summary
                ? summary.draft_studies > 0
                  ? `${summary.draft_studies} taslak çalışma bekliyor (Onaylamak için tıkla →)`
                  : 'Bekleyen taslak çalışma yok'
                : ''
            }
            icon={FlaskConical}
            tone="blue"
            loading={loading && !summary}
          />
        </button>

        <button type="button" className="text-left" onClick={() => onNavigate?.('conflicts')}>
          <StatCard
            title="Çözülmemiş Kritik Çakışmalar"
            value={summary?.critical_conflicts ?? '—'}
            subtitle={summary ? `${summary.open_conflicts} toplam açık çakışma` : ''}
            icon={ShieldAlert}
            alert={summary?.critical_conflicts > 0}
            tone="slate"
            loading={loading && !summary}
          />
        </button>

        <button
          type="button"
          className="text-left"
          onClick={() => navigate('/planning')}
          title="Master Operasyon Takvimini aç"
        >
          <StatCard
            title="Bugünün Görevleri"
            value={summary?.todays_tasks ?? '—'}
            subtitle={
              summary && summary.todays_tasks === 0 && summary.total_planned_tasks > 0
                ? `Bugün 0 • Takvimde toplam ${summary.total_planned_tasks} planlı adım (Takvime Git →)`
                : 'Bugüne düşen planlı GLP adımı'
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
                ? 'Tüm Planlı Biyolojik Kilometre Taşları (Geçmiş / Taslak Dahil)'
                : 'Yaklaşan Biyolojik Kilometre Taşları'}
            </h3>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setIncludeAll(true)}
                className={`px-2.5 py-1 rounded-md font-medium transition ${
                  includeAll ? 'bg-slate-900 text-white shadow-xs' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                Tüm Planlı Görevler (Geçmiş/Taslak Dahil)
              </button>
              <button
                type="button"
                onClick={() => setIncludeAll(false)}
                className={`px-2.5 py-1 rounded-md font-medium transition ${
                  !includeAll ? 'bg-slate-900 text-white shadow-xs' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                Önümüzdeki Günler
              </button>
            </div>

            {!includeAll && (
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-white"
              >
                <option value={7}>7 gün</option>
                <option value={14}>14 gün</option>
                <option value={30}>30 gün</option>
                <option value={90}>90 gün</option>
              </select>
            )}
          </div>
        </div>

        {showingFallbackAll && !includeAll && milestones.length > 0 && (
          <div className="px-5 py-2.5 bg-amber-50/90 border-b border-amber-200 flex flex-wrap items-center justify-between gap-2 text-xs text-amber-900">
            <span>
              <strong>Bilgilendirme:</strong> Bugünden itibaren önümüzdeki {days} gün içinde biyolojik kilitli görev bulunmadığı için mevcut çalışmaların (Temmuz–Ağustos 2026) planlı görevleri aşağıda listelenmeye devam etmektedir.
            </span>
            <button
              type="button"
              onClick={() => setIncludeAll(true)}
              className="font-semibold text-blue-800 hover:underline shrink-0"
            >
              Tüm Planlı Görevler görünümünde sabitle →
            </button>
          </div>
        )}

        {milestones.length === 0 ? (
          <div className="p-8 text-center space-y-2">
            <p className="text-sm text-slate-400">
              {loading
                ? 'Yükleniyor…'
                : includeAll
                  ? 'Sistemde henüz planlanmış biyolojik kilitli görev bulunmuyor.'
                  : `Önümüzdeki ${days} gün içinde biyolojik kilitli görev bulunmuyor.`}
            </p>
            {!loading && !includeAll && (summary?.total_planned_tasks || 0) > 0 && (
              <button
                type="button"
                onClick={() => setIncludeAll(true)}
                className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline"
              >
                <span>Geçmiş / Taslak Dahil Tüm Planlı Görevleri Göster ({summary.total_planned_tasks} adım)</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/80 border-b border-slate-200">
                <tr className="tracking-wider uppercase text-xs font-semibold text-slate-500">
                  <th className="text-left px-5 py-3">Zaman</th>
                  <th className="text-left px-5 py-3">Çalışma</th>
                  <th className="text-left px-5 py-3">Görev</th>
                  <th className="text-left px-5 py-3">Süre / Tolerans</th>
                  <th className="text-left px-5 py-3">Sorumlu</th>
                  <th className="text-left px-5 py-3">Durum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {milestones.map((m) => (
                  <tr
                    key={m.id}
                    onClick={() => openStudy(m.study_id)}
                    className="hover:bg-slate-50/80 cursor-pointer transition-colors"
                    title="Bu çalışmanın takvimini açmak için tıklayın"
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
                          <span className="nl-badge nl-badge-draft">TASLAK</span>
                        ) : (
                          <span className="nl-badge nl-badge-approved">ONAYLI</span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-slate-800">
                      <span className="inline-block font-mono text-[10px] font-semibold px-1.5 py-0.5 mr-2 rounded bg-slate-100 text-slate-600 border border-slate-200">
                        G{m.study_day}
                      </span>
                      {m.step_name}
                    </td>
                    <td className="px-5 py-3.5 text-xs text-slate-600 whitespace-nowrap tabular-nums">
                      {fmtMinutes(m.duration_minutes)} <span className="text-slate-300 mx-0.5">•</span> ±
                      {m.biological_tolerance_minutes} dk
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
                              {n}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-red-600 font-medium">Atanmadı</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="nl-badge bg-slate-50 text-slate-600 border-slate-200">{m.status}</span>
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
