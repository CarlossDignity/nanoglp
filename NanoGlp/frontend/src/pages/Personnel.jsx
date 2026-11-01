import React, { useCallback, useEffect, useState } from 'react';
import {
  UserPlus,
  AlertTriangle,
  Lock,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Calendar as CalendarIcon,
  BarChart3,
  Table2,
} from 'lucide-react';
import { getDailyWorkload, getWeeklyWorkload, createPersonnel, extractError } from '../services/api';
import { useAuth } from '../state/AuthContext';
import { fmtMinutes, fmtTime, todayISO, ROLE_LABEL } from '../utils/format';

const emptyForm = { full_name: '', email: '', role: 'TECHNICIAN', qualifications: '', max_daily_hours: 9 };
const DAY_SHORT_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

function addDaysISO(isoDate, delta) {
  const [y, m, d] = isoDate.split('-').map(Number);
  const dt = new Date(y, m - 1, d + delta);
  const yy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, '0');
  const dd = String(dt.getDate()).padStart(2, '0');
  return `${yy}-${mm}-${dd}`;
}

function fmtShortDateTR(isoDate) {
  if (!isoDate) return '—';
  const [y, m, d] = isoDate.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return dt.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', weekday: 'short' });
}

function fmtWeekRangeTR(mondayIso) {
  if (!mondayIso) return '—';
  const sundayIso = addDaysISO(mondayIso, 6);
  const [y1, m1, d1] = mondayIso.split('-').map(Number);
  const [y2, m2, d2] = sundayIso.split('-').map(Number);
  const dt1 = new Date(y1, m1 - 1, d1);
  const dt2 = new Date(y2, m2 - 1, d2);
  return `${dt1.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })} – ${dt2.toLocaleDateString('tr-TR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })}`;
}

export default function Personnel({ onChanged }) {
  const { isReadOnly } = useAuth();
  const [date, setDate] = useState(todayISO());
  const [viewTab, setViewTab] = useState('daily'); // 'daily' | 'weekly'
  const [autoFocused, setAutoFocused] = useState(false);

  const [data, setData] = useState(null);
  const [weeklyData, setWeeklyData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState({});
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dailyRes, weeklyRes] = await Promise.all([
        getDailyWorkload(date),
        getWeeklyWorkload(date),
      ]);
      const dData = dailyRes.data;
      const wData = weeklyRes.data;

      // Eğer açılışta bugünün tarihinde (örn. 30.10.2026) hiç görev yoksa ve sistemde görevli tarihler varsa
      // otomatik olarak ilk görevli tarihe (örn. 30.07.2026) odaklan
      const totalToday = (dData?.personnel || []).reduce((acc, p) => acc + (p.total_minutes || 0), 0);
      if (
        !autoFocused &&
        totalToday === 0 &&
        dData?.active_dates?.length > 0 &&
        dData.default_focus_date &&
        dData.default_focus_date !== date
      ) {
        setAutoFocused(true);
        setDate(dData.default_focus_date);
        return;
      }

      setAutoFocused(true);
      setData(dData);
      setWeeklyData(wData);
    } catch (err) {
      setError(extractError(err, 'Personel iş yükü alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, [date, autoFocused]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      await createPersonnel({
        ...form,
        email: form.email.trim() || null,
        max_daily_hours: Number(form.max_daily_hours),
        qualifications: form.qualifications
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setShowModal(false);
      setForm(emptyForm);
      load();
      onChanged?.();
    } catch (err) {
      setFormError(extractError(err, 'Personel eklenemedi.'));
    } finally {
      setSaving(false);
    }
  };

  const limit = data?.limit_minutes ?? 540;
  const people = data?.personnel ?? [];
  const activeDates = data?.active_dates ?? [];
  const activeWeeks = weeklyData?.active_weeks ?? data?.active_weeks ?? [];
  const overCount = people.filter((p) => p.exceeds_limit).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Personel ve İş Yükü Yönetimi</h2>
          <p className="text-sm text-slate-500">
            Günlük yasal/GLP üst sınır: {fmtMinutes(limit)} ({limit} dk) • Seçili Tarih:{' '}
            <strong>{fmtShortDateTR(date)} ({date})</strong>
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Görünüm Sekmesi: Günlük Barlar / Haftalık Matris */}
          <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-sm">
            <button
              type="button"
              onClick={() => setViewTab('daily')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                viewTab === 'daily'
                  ? 'bg-blue-700 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <BarChart3 className="w-3.5 h-3.5" />
              <span>Günlük İş Yükü Barları</span>
            </button>
            <button
              type="button"
              onClick={() => setViewTab('weekly')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                viewTab === 'weekly'
                  ? 'bg-blue-700 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Table2 className="w-3.5 h-3.5" />
              <span>Haftalık İş Yükü Matrisi (Pzt–Paz)</span>
            </button>
          </div>

          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="border border-slate-300 rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
          />

          {!isReadOnly && (
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 bg-blue-700 hover:bg-blue-800 text-white text-sm font-medium rounded-md px-4 py-2"
            >
              <UserPlus className="w-4 h-4" /> Personel Ekle
            </button>
          )}
        </div>
      </div>

      {/* FAZ 6.3: Görev Olan Aktif Tarihler Kısayol Çubuğu */}
      {activeDates.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
              <CalendarIcon className="w-3.5 h-3.5 text-blue-700" />
              Görevli Günler (Hızlı Geçiş):
            </span>
            <button
              type="button"
              onClick={() => setDate(todayISO())}
              className={`text-[11px] font-medium px-2.5 py-0.5 rounded border ${
                date === todayISO()
                  ? 'bg-slate-800 text-white border-slate-800'
                  : 'bg-slate-50 text-slate-600 border-slate-300 hover:bg-slate-100'
              }`}
            >
              Bugün ({todayISO()})
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {activeDates.map((dt) => {
              const isSelected = dt === date;
              return (
                <button
                  key={dt}
                  type="button"
                  onClick={() => setDate(dt)}
                  className={`text-xs font-medium px-3 py-1 rounded-full border transition ${
                    isSelected
                      ? 'bg-blue-700 text-white border-blue-700 shadow-sm'
                      : 'bg-blue-50/60 text-blue-900 border-blue-200 hover:bg-blue-100'
                  }`}
                >
                  {fmtShortDateTR(dt)}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {error && <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>}

      {overCount > 0 && (
        <div className="flex items-center gap-3 rounded-lg border-2 border-red-600 bg-red-50 px-4 py-3">
          <AlertTriangle className="w-5 h-5 text-red-700" />
          <p className="text-sm text-red-900">
            <strong>{overCount} personel</strong> bu tarihte 9 saatlik sınırı aşıyor. Görevler otomatik kaydırılmaz —
            ek personel ataması veya SD onaylı plan revizyonu gerekir.
          </p>
        </div>
      )}

      {/* =====================================================================
          SEKME 1: GÜNLÜK İŞ YÜKÜ BARLARI
         ===================================================================== */}
      {viewTab === 'daily' && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm divide-y divide-slate-100">
          {loading && !data && <p className="p-8 text-center text-sm text-slate-400">Yükleniyor…</p>}
          {!loading && people.length === 0 && (
            <p className="p-8 text-center text-sm text-slate-400">Kayıtlı aktif personel yok.</p>
          )}

          {people.map((p) => {
            const ratio = p.total_minutes / limit;
            const barPct = Math.min(ratio, 1) * 100;
            const over = p.exceeds_limit;
            const barColor = over ? 'bg-red-600' : ratio >= 0.85 ? 'bg-amber-500' : 'bg-blue-600';
            const open = expanded[p.personnel_id] ?? p.tasks.length > 0;

            return (
              <div key={p.personnel_id} className={over ? 'bg-red-50/60' : ''}>
                <button
                  onClick={() => setExpanded((s) => ({ ...s, [p.personnel_id]: !open }))}
                  className="w-full text-left px-5 py-4 grid grid-cols-1 md:grid-cols-[minmax(240px,1fr)_2fr_auto] gap-4 items-center"
                >
                  <div className="flex items-start gap-2">
                    {open ? (
                      <ChevronDown className="w-4 h-4 mt-0.5 text-slate-400" />
                    ) : (
                      <ChevronRight className="w-4 h-4 mt-0.5 text-slate-400" />
                    )}
                    <div>
                      <p className="text-sm font-medium text-slate-900 flex flex-wrap items-center gap-2">
                        {p.full_name}
                        {over && (
                          <span className="text-[10px] font-bold tracking-wide px-2 py-0.5 rounded bg-red-600 text-white">
                            9 SAAT AŞIMI
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-slate-500">{ROLE_LABEL[p.role] || p.role}</p>
                    </div>
                  </div>

                  <div>
                    <div className="relative h-3 bg-slate-100 rounded-full overflow-hidden">
                      <div className={`h-full ${barColor}`} style={{ width: `${barPct}%` }} />
                    </div>
                    <div className="flex justify-between mt-1 text-[10px] text-slate-400">
                      <span>0 dk</span>
                      <span>9 sa (540 dk)</span>
                    </div>
                  </div>

                  <div className="text-right whitespace-nowrap">
                    <p className={`text-sm font-semibold ${over ? 'text-red-700' : 'text-slate-800'}`}>
                      {fmtMinutes(p.total_minutes)}
                    </p>
                    <p className={`text-[11px] ${over ? 'text-red-600 font-medium' : 'text-slate-500'}`}>
                      {over ? `+${p.total_minutes - limit} dk aşım` : `${p.tasks.length} görev`}
                    </p>
                  </div>
                </button>

                {open && (
                  <div className="px-12 pb-4">
                    {p.tasks.length === 0 ? (
                      <p className="text-xs text-slate-400 italic">Bu tarihte atanmış görev yok.</p>
                    ) : (
                      <ul className="text-xs border border-slate-200 rounded-md divide-y divide-slate-100 bg-white">
                        {p.tasks.map((t) => (
                          <li key={t.step_id} className="px-3 py-2 flex items-center justify-between gap-4">
                            <span className="flex items-center gap-1.5 text-slate-700">
                              <span className="font-mono text-[11px] font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-800 border border-blue-200 shrink-0">
                                [{t.study_code}]
                              </span>
                              <span className="font-mono text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 shrink-0">
                                G{t.study_day}
                              </span>
                              {t.is_biological_fixed_time && <Lock className="w-3 h-3 text-blue-700 shrink-0" />}
                              <span>{t.step_name}</span>
                            </span>
                            <span className="text-slate-500 whitespace-nowrap">
                              {fmtTime(t.planned_start)}–{fmtTime(t.planned_end)} • {fmtMinutes(t.minutes)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {p.qualifications.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {p.qualifications.map((q) => (
                          <span key={q} className="text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-600">
                            {q}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* =====================================================================
          SEKME 2: HAFTALIK İŞ YÜKÜ MATRİSİ (PAZARTESİ - PAZAR)
         ===================================================================== */}
      {viewTab === 'weekly' && weeklyData && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="p-4 border-b border-slate-200 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Haftalık Personel İş Yükü Matrisi ({fmtWeekRangeTR(weeklyData.week_start)})
                </h3>
                <p className="text-xs text-slate-500">
                  7 günlük (Pzt–Paz) toplam görev süreleri • Hücreye tıklayarak o günün detaylı görev dökümüne
                  geçebilirsiniz.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setDate((d) => addDaysISO(d, -7))}
                  className="inline-flex items-center gap-1 border border-slate-300 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Önceki Hafta
                </button>
                <button
                  type="button"
                  onClick={() => setDate((d) => addDaysISO(d, 7))}
                  className="inline-flex items-center gap-1 border border-slate-300 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Sonraki Hafta <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {activeWeeks.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-semibold text-slate-500 mr-1">Görevli Haftalar:</span>
                {activeWeeks.map((wk) => {
                  const active = wk === weeklyData.week_start;
                  return (
                    <button
                      key={wk}
                      type="button"
                      onClick={() => setDate(wk)}
                      className={`text-[11px] font-medium px-2.5 py-1 rounded-full border transition ${
                        active
                          ? 'bg-blue-700 text-white border-blue-700'
                          : 'bg-slate-50 text-slate-700 border-slate-300 hover:bg-blue-50'
                      }`}
                    >
                      {fmtWeekRangeTR(wk)}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-600">
                <tr>
                  <th className="text-left px-4 py-3 font-semibold min-w-[200px]">Personel / Rol</th>
                  {weeklyData.days.map((dIso, idx) => (
                    <th
                      key={dIso}
                      className={`text-center px-3 py-3 font-semibold min-w-[95px] ${
                        idx >= 5 ? 'bg-amber-50/60 text-amber-900' : ''
                      }`}
                    >
                      <div>{DAY_SHORT_TR[idx]}</div>
                      <div className="font-mono text-[10px] font-normal text-slate-500">{dIso.slice(5)}</div>
                    </th>
                  ))}
                  <th className="text-right px-4 py-3 font-semibold min-w-[110px]">Haftalık Toplam</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {weeklyData.personnel.map((p) => (
                  <tr key={p.personnel_id} className="hover:bg-slate-50/70">
                    <td className="px-4 py-3">
                      <p className="font-semibold text-slate-900">{p.full_name}</p>
                      <p className="text-[11px] text-slate-500">{ROLE_LABEL[p.role] || p.role}</p>
                    </td>
                    {p.daily.map((cell, idx) => {
                      const hasWork = cell.total_minutes > 0;
                      const over = cell.exceeds_limit;
                      return (
                        <td
                          key={cell.date}
                          onClick={() => {
                            setDate(cell.date);
                            setViewTab('daily');
                          }}
                          className={`text-center px-2 py-3 cursor-pointer transition ${
                            idx >= 5 ? 'bg-amber-50/20' : ''
                          } hover:bg-blue-50/60`}
                          title={
                            hasWork
                              ? cell.tasks.map((t) => `[${t.study_code}] G${t.study_day} — ${t.step_name} (${t.minutes} dk)`).join('\n')
                              : 'Görev yok'
                          }
                        >
                          {hasWork ? (
                            <div
                              className={`inline-flex flex-col items-center px-2.5 py-1 rounded-md border ${
                                over
                                  ? 'bg-red-600 text-white border-red-700 font-bold'
                                  : 'bg-blue-50 text-blue-900 border-blue-200 font-semibold'
                              }`}
                            >
                              <span>{fmtMinutes(cell.total_minutes)}</span>
                              <span className={`text-[10px] ${over ? 'text-red-100' : 'text-blue-700'}`}>
                                {cell.task_count} görev
                              </span>
                            </div>
                          ) : (
                            <span className="text-slate-300">—</span>
                          )}
                        </td>
                      );
                    })}
                    <td className="px-4 py-3 text-right font-semibold text-slate-800">
                      <div>{fmtMinutes(p.weekly_total_minutes)}</div>
                      <div className="text-[10px] font-normal text-slate-500">{p.weekly_task_count} görev</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-slate-900/40 z-50 flex items-center justify-center p-4">
          <form onSubmit={handleCreate} className="bg-white rounded-lg shadow-xl max-w-md w-full p-6 space-y-3 text-sm">
            <h3 className="text-base font-semibold text-slate-900">Yeni Personel</h3>
            {formError && <div className="p-2.5 bg-red-50 text-red-700 rounded text-xs">{formError}</div>}
            {[
              ['full_name', 'Ad Soyad', 'text'],
              ['email', 'E-posta (opsiyonel)', 'email'],
            ].map(([key, label, type]) => (
              <label key={key} className="block">
                <span className="block text-xs font-medium text-slate-700 mb-1">{label}</span>
                <input
                  type={type}
                  required={key === 'full_name'}
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-600"
                />
              </label>
            ))}
            <label className="block">
              <span className="block text-xs font-medium text-slate-700 mb-1">GLP Rolü</span>
              <select
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                className="w-full border border-slate-300 rounded-md px-3 py-2 bg-white"
              >
                {Object.entries(ROLE_LABEL).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-slate-700 mb-1">Yetkinlikler (virgülle)</span>
              <input
                value={form.qualifications}
                onChange={(e) => setForm({ ...form, qualifications: e.target.value })}
                placeholder="Dozlama, Hücre Kültürü, HPLC"
                className="w-full border border-slate-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </label>
            <div className="flex justify-end gap-2 pt-3 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="px-3 py-2 border border-slate-300 rounded-md text-slate-600"
              >
                İptal
              </button>
              <button
                type="submit"
                disabled={saving}
                className="px-4 py-2 bg-blue-700 text-white rounded-md disabled:bg-blue-400"
              >
                {saving ? 'Kaydediliyor…' : 'Kaydet'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
