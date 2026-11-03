import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import {
  getRestrictions,
  createRestriction,
  updateRestriction,
  deleteRestriction,
  extractError,
} from '../services/api';
import { todayISO } from '../utils/format';
import { usePreferences } from '../state/PreferencesContext';

const fmt = (iso) => {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
};

/**
 * FAZ 8.1 — Test Kısıtlama ve Uygunluk Takvimi (Blackout).
 * "XXX testini XXX sebebinden dolayı ŞU TARİHE KADAR yapamayız" kayıtlarını listeler / ekler / siler.
 * Takvim motoru, kısıtlı aralığa denk gelen Gün 0'ı otomatik olarak restricted_until + 1 (ilk iş günü) tarihine öteler.
 */
export default function RestrictionManager({ canEdit = false, embedded = false }) {
  const { t, tr, lang } = usePreferences();
  const [rows, setRows] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({
    template_code: 'ALL',
    restricted_from: todayISO(),
    restricted_until: '',
    reason: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getRestrictions();
      setRows(res.data?.restrictions || []);
      setTemplates(res.data?.templates || []);
      setError(null);
    } catch (err) {
      setError(extractError(err, 'Test kısıtlamaları alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedLabel = useMemo(
    () => templates.find((t) => t.code === form.template_code)?.label || 'Tüm Testler',
    [templates, form.template_code]
  );

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!form.restricted_until || !form.reason.trim()) {
      setError('Bitiş tarihi ve kısıtlama sebebi zorunludur.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createRestriction({
        template_code: form.template_code,
        test_name: selectedLabel,
        restricted_from: form.restricted_from,
        restricted_until: form.restricted_until,
        reason: form.reason.trim(),
      });
      setForm((f) => ({ ...f, restricted_until: '', reason: '' }));
      await load();
    } catch (err) {
      setError(extractError(err, 'Kısıtlama eklenemedi.'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (r) => {
    if (!window.confirm(`"${r.test_name}" kısıtlamasını silmek istiyor musunuz?`)) return;
    try {
      await deleteRestriction(r.id);
      await load();
    } catch (err) {
      setError(extractError(err, 'Kısıtlama silinemedi.'));
    }
  };

  const toggleActive = async (r) => {
    try {
      await updateRestriction(r.id, { is_active: !r.is_active });
      await load();
    } catch (err) {
      setError(extractError(err, 'Kısıtlama güncellenemedi.'));
    }
  };

  return (
    <div className={embedded ? '' : 'bg-white border border-slate-200 rounded-lg'}>
      {!embedded && (
        <div className="px-5 py-3 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900">Test Kısıtlama ve Uygunluk Takvimi</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Bir test belirli bir tarihe kadar yapılamıyorsa kaydedin; Gün 0 bu aralığa denk gelen çalışmalar otomatik olarak
            kısıtlama bitişinden sonraki ilk iş gününe ötelenir.
          </p>
        </div>
      )}

      {error && (
        <div className="mx-5 mt-3 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 rounded">{error}</div>
      )}

      {canEdit && (
        <form onSubmit={handleAdd} className="px-5 py-3 grid grid-cols-1 md:grid-cols-[1.3fr_0.7fr_0.7fr_1.6fr_auto] gap-2 items-end border-b border-slate-100">
          <label className="block">
            <span className="block text-[11px] font-medium text-slate-500 mb-1">Test</span>
            <select
              value={form.template_code}
              onChange={(e) => setForm({ ...form, template_code: e.target.value })}
              className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-600"
            >
              {templates.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="block text-[11px] font-medium text-slate-500 mb-1">Kısıtlama başlangıcı</span>
            <input
              type="date"
              value={form.restricted_from}
              onChange={(e) => setForm({ ...form, restricted_from: e.target.value })}
              className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
            />
          </label>
          <label className="block">
            <span className="block text-[11px] font-medium text-slate-500 mb-1">Şu tarihe kadar yapılamaz</span>
            <input
              type="date"
              value={form.restricted_until}
              min={form.restricted_from}
              onChange={(e) => setForm({ ...form, restricted_until: e.target.value })}
              className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
            />
          </label>
          <label className="block">
            <span className="block text-[11px] font-medium text-slate-500 mb-1">Sebep</span>
            <input
              type="text"
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              placeholder="Örn. Tavşan tedarikçisi sevkiyat aksaklığı"
              className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
            />
          </label>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center justify-center gap-1.5 bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-xs font-medium rounded px-3 py-1.5"
          >
            {saving && <Loader2 className="w-3 h-3 animate-spin" />}
            Kısıtlama Ekle
          </button>
        </form>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <tr>
              <th className="text-left px-5 py-2 font-medium">Test</th>
              <th className="text-left px-3 py-2 font-medium">Kısıtlı aralık</th>
              <th className="text-left px-3 py-2 font-medium">Sebep</th>
              <th className="text-left px-3 py-2 font-medium">Durum</th>
              {canEdit && <th className="px-5 py-2" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-5 py-5 text-center text-slate-400">
                  Yükleniyor…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-5 py-5 text-center text-slate-400">
                  Tanımlı test kısıtlaması yok.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className={r.is_active && !r.is_expired ? '' : 'text-slate-400'}>
                  <td className="px-5 py-2">
                    <span className="font-medium text-slate-800">{r.test_name}</span>
                    <span className="ml-2 font-mono text-[10px] text-slate-400">{r.template_code}</span>
                  </td>
                  <td className="px-3 py-2 font-mono tabular-nums whitespace-nowrap">
                    {fmt(r.restricted_from)} → {fmt(r.restricted_until)}
                  </td>
                  <td className="px-3 py-2 max-w-[360px]">{r.reason}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          !r.is_active ? 'bg-slate-300' : r.is_expired ? 'bg-slate-300' : r.is_current ? 'bg-red-500' : 'bg-amber-400'
                        }`}
                      />
                      {!r.is_active ? 'Pasif' : r.is_expired ? 'Süresi doldu' : r.is_current ? 'Şu an kısıtlı' : 'Planlı kısıtlama'}
                    </span>
                  </td>
                  {canEdit && (
                    <td className="px-5 py-2 text-right whitespace-nowrap">
                      <button type="button" onClick={() => toggleActive(r)} className="text-slate-500 hover:text-slate-900 mr-3">
                        {r.is_active ? 'Pasife al' : 'Aktifleştir'}
                      </button>
                      <button type="button" onClick={() => handleDelete(r)} className="text-slate-400 hover:text-red-700 align-middle" title="Sil">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
