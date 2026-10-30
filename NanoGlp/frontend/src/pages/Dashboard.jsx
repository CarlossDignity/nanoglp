import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FlaskConical, ShieldAlert, ClipboardList, Lock, RefreshCw, ArrowRight } from 'lucide-react';
import StatCard from '../components/StatCard';
import { getSummary, getSteps, extractError } from '../services/api';
import { fmtDateTime, fmtMinutes, relativeFromNow } from '../utils/format';

export default function Dashboard({ onNavigate }) {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [milestones, setMilestones] = useState([]);
  const [days, setDays] = useState(14);
  const [includeAll, setIncludeAll] = useState(false);
  const [autoSwitched, setAutoSwitched] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, m] = await Promise.all([
        getSummary(),
        getSteps({ days, biological_only: true, include_all: includeAll }),
      ]);
      setSummary(s.data);

      // Eğer önümüzdeki N günde 0 görev varsa ancak sistemde planlı görevler mevcutsa (örn. 30.07.2026 çalışmaları),
      // otomatik olarak "Tüm Planlı Görevler (Geçmiş/Taslak Dahil)" görünümüne geç
      if (
        !autoSwitched &&
        !includeAll &&
        (m.data || []).length === 0 &&
        (s.data?.total_planned_tasks || 0) > 0
      ) {
        setAutoSwitched(true);
        setIncludeAll(true);
        return;
      }

      setAutoSwitched(true);
      setMilestones(m.data || []);
    } catch (err) {
      setError(extractError(err, 'Dashboard verileri alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, [days, includeAll, autoSwitched]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Yönetici Paneli</h2>
          <p className="text-sm text-slate-500">
            Laboratuvar operasyonel durumu — {new Date().toLocaleDateString('tr-TR', { dateStyle: 'full' })}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 text-xs font-medium text-slate-600 border border-slate-300 bg-white rounded-md px-3 py-2 hover:bg-slate-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Yenile
        </button>
      </div>

      {error && <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button
          type="button"
          className="text-left group"
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

        <button
          type="button"
          className="text-left"
          onClick={() => onNavigate?.('conflicts')}
        >
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
      </div>

      <div className="bg-white border border-slate-200 rounded-lg shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Lock className="w-4 h-4 text-blue-700" />
            <h3 className="text-sm font-semibold text-slate-800">
              {includeAll
                ? 'Tüm Planlı Biyolojik Kilometre Taşları (Geçmiş / Taslak Dahil)'
                : 'Yaklaşan Biyolojik Kilometre Taşları'}
            </h3>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-md border border-slate-300 bg-slate-50 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setIncludeAll(true)}
                className={`px-2.5 py-1 rounded font-medium transition ${
                  includeAll ? 'bg-blue-700 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                Tüm Planlı Görevler (Geçmiş/Taslak Dahil)
              </button>
              <button
                type="button"
                onClick={() => setIncludeAll(false)}
                className={`px-2.5 py-1 rounded font-medium transition ${
                  !includeAll ? 'bg-blue-700 text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                Önümüzdeki Günler
              </button>
            </div>

            {!includeAll && (
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="text-xs border border-slate-300 rounded-md px-2 py-1.5 bg-white"
              >
                <option value={7}>7 gün</option>
                <option value={14}>14 gün</option>
                <option value={30}>30 gün</option>
                <option value={90}>90 gün</option>
              </select>
            )}
          </div>
        </div>

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
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="text-left px-5 py-3 font-medium">Zaman</th>
                  <th className="text-left px-5 py-3 font-medium">Çalışma</th>
                  <th className="text-left px-5 py-3 font-medium">Görev</th>
                  <th className="text-left px-5 py-3 font-medium">Süre / Tolerans</th>
                  <th className="text-left px-5 py-3 font-medium">Sorumlu</th>
                  <th className="text-left px-5 py-3 font-medium">Durum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {milestones.map((m) => (
                  <tr
                    key={m.id}
                    onClick={() => navigate('/planning', { state: { selectedStudyId: m.study_id } })}
                    className="hover:bg-slate-50 cursor-pointer"
                    title="Bu çalışmanın takvimini açmak için tıklayın"
                  >
                    <td className="px-5 py-3 whitespace-nowrap">
                      <p className="font-medium text-slate-800">{fmtDateTime(m.planned_start)}</p>
                      <p className="text-xs text-blue-700">{relativeFromNow(m.planned_start)}</p>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs text-slate-700">
                      {m.study_code}
                      {m.study_status === 'DRAFT' ? (
                        <span className="ml-1.5 font-sans text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                          TASLAK
                        </span>
                      ) : (
                        <span className="ml-1.5 font-sans text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-800 border border-emerald-200">
                          ONAYLI
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-slate-800">
                      <span className="font-mono text-[10px] px-1 mr-1.5 rounded bg-slate-100 text-slate-600">
                        G{m.study_day}
                      </span>
                      {m.step_name}
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-600 whitespace-nowrap">
                      {fmtMinutes(m.duration_minutes)} • ±{m.biological_tolerance_minutes} dk
                    </td>
                    <td className="px-5 py-3 text-xs text-slate-700">
                      {m.assignee_names?.join(', ') || <span className="text-red-600 font-medium">Atanmadı</span>}
                    </td>
                    <td className="px-5 py-3">
                      <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                        {m.status}
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
