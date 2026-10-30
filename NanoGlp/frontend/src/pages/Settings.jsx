import React, { useState } from 'react';
import { Timer, Boxes, History, UserCheck, AlertTriangle, Eye } from 'lucide-react';
import ConfigTable from '../components/ConfigTable';
import { useMockStore, uid, TASK_CATEGORIES, RESOURCE_TYPES } from '../state/MockStore';
import { useAuth } from '../state/AuthContext';
import { fmtDateTime, ROLE_SHORT, ROLE_LABEL } from '../utils/format';

const MIN_REASON = 5;

const describeDuration = (d) => d && `${d.name} · ${d.category} · ${d.minutes} dk`;
const describeResource = (r) => r && `${r.name} · ${r.type} · kapasite ${r.capacity} (${r.unit})`;

const isDuplicate = (rows, name, editingId) =>
  rows.some((r) => r.id !== editingId && r.name.toLocaleLowerCase('tr') === name.toLocaleLowerCase('tr'));

const ACTION_STYLE = {
  EKLEME: 'bg-blue-50 text-blue-700',
  GÜNCELLEME: 'bg-amber-50 text-amber-800',
  SİLME: 'bg-red-50 text-red-700',
};

export default function Settings() {
  const { user, isReadOnly, canWriteManagement } = useAuth();
  const { durations, setDurations, resources, setResources, settingsLog, setSettingsLog } = useMockStore();

  const [reason, setReason] = useState('');
  const canEdit = Boolean(user && canWriteManagement && !isReadOnly && reason.trim().length >= MIN_REASON);
  const lockedReason = isReadOnly
    ? 'Kalite Güvence (QA) rolü SADECE OKUMA yetkisine sahiptir; ayar değiştiremez.'
    : !canWriteManagement
    ? 'Bu ekranı yalnızca TFM, Çalışma Yöneticisi (SD) veya Planlama Koordinatörü düzenleyebilir.'
    : `Değişiklik gerekçesi en az ${MIN_REASON} karakter olmalı.`;

  const log = (action, entity, before, after) =>
    setSettingsLog((prev) => [
      {
        id: uid(),
        at: new Date().toISOString(),
        editor: user.full_name,
        editorRole: user.role,
        action,
        entity,
        before,
        after,
        reason: reason.trim(),
      },
      ...prev,
    ]);

  /** Tablo-bağımsız CRUD + denetim kaydı */
  const crud = (rows, setRows, entity, describe) => ({
    onAdd: (values) => {
      if (!canEdit) return;
      const row = { id: uid(), ...values };
      setRows((prev) => [...prev, row]);
      log('EKLEME', entity, null, describe(row));
    },
    onUpdate: (id, values) => {
      if (!canEdit) return;
      const before = rows.find((r) => r.id === id);
      const after = { ...before, ...values };
      if (describe(before) === describe(after)) return;
      setRows((prev) => prev.map((r) => (r.id === id ? after : r)));
      log('GÜNCELLEME', entity, describe(before), describe(after));
    },
    onDelete: (id) => {
      if (!canEdit) return;
      const row = rows.find((r) => r.id === id);
      if (!window.confirm(`"${row.name}" kaydı silinsin mi?\nGerekçe: ${reason.trim()}`)) return;
      setRows((prev) => prev.filter((r) => r.id !== id));
      log('SİLME', entity, describe(row), null);
    },
  });

  const validateDuration = (v, editingId) => {
    if (!v.name) return 'Görev adı zorunludur.';
    if (isDuplicate(durations, v.name, editingId)) return `"${v.name}" zaten tanımlı.`;
    if (!Number.isInteger(v.minutes) || v.minutes < 1 || v.minutes > 1440) return 'Süre 1–1440 dk arasında tam sayı olmalıdır.';
    return null;
  };

  const validateResource = (v, editingId) => {
    if (!v.name) return 'Oda/cihaz adı zorunludur.';
    if (isDuplicate(resources, v.name, editingId)) return `"${v.name}" zaten tanımlı.`;
    if (!Number.isInteger(v.capacity) || v.capacity < 1 || v.capacity > 999) return 'Kapasite 1–999 arasında tam sayı olmalıdır.';
    if (!v.unit) return 'Kapasite birimi zorunludur (örn. eşzamanlı kullanım).';
    return null;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Sistem Kalibrasyonu</h2>
        <p className="text-sm text-slate-500">
          Standart görev süreleri ile oda ve cihaz kapasiteleri. Değişiklikler JWT kimliğinizle denetim izine yazılır.
        </p>
      </div>

      {isReadOnly ? (
        <div className="flex items-center gap-2.5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <Eye className="w-4 h-4 text-amber-700 shrink-0" />
          <span>
            <strong>Kalite Güvence (QA) Salt Okunur Modu:</strong> Standart görev sürelerini, kapasiteleri ve değişiklik
            geçmişini denetleyebilirsiniz; değerleri değiştirme yetkiniz kapalıdır.
          </span>
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3">
          <AlertTriangle className="w-5 h-5 text-amber-700 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-900 leading-relaxed">
            <strong>Geçici mod (mock):</strong> Değerler yalnızca tarayıcı belleğinde tutulur, sayfa yenilenince sıfırlanır.
            Backend kalibrasyon bağlantısı tamamlandığında bu ekran master kaynak olacaktır.
          </p>
        </div>
      )}

      {/* Oturum Açmış Yönetici + Gerekçe (JWT Doğrulamalı GLP Denetim İzi) */}
      <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-5">
        <div className="flex items-center gap-2 mb-3">
          <UserCheck className="w-4 h-4 text-blue-700" />
          <h3 className="text-sm font-semibold text-slate-800">Elektronik İmza ve Değişiklik Gerekçesi (JWT)</h3>
          <span
            className={`ml-auto text-[11px] font-medium px-2 py-0.5 rounded ${
              canEdit ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-500'
            }`}
          >
            {canEdit ? 'Düzenleme açık' : 'Salt okunur'}
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4 items-end">
          <div>
            <span className="block text-xs font-medium text-slate-700 mb-1.5">Oturum Açan Yetkili</span>
            <div className="w-full border border-slate-200 rounded-md px-3 py-2 text-sm bg-slate-50 text-slate-800 font-medium">
              {user?.full_name} ({ROLE_LABEL[user?.role] || user?.role})
            </div>
          </div>
          <label className="block">
            <span className="block text-xs font-medium text-slate-700 mb-1.5">Değişiklik gerekçesi (zorunlu)</span>
            <input
              value={reason}
              disabled={isReadOnly || !canWriteManagement}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                isReadOnly
                  ? 'QA rolü salt okunur yetkiye sahiptir'
                  : 'Örn. Zaman etüdü sonuçlarına göre gözlem süresi güncellendi'
              }
              className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:bg-slate-100"
            />
          </label>
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ConfigTable
          title="Standart Görev Süreleri"
          description="Personelin görevde fiilen meşgul olduğu süre; 9 saatlik iş yükü hesabına girecek."
          icon={Timer}
          columns={[
            { key: 'name', label: 'Görev', type: 'text' },
            { key: 'category', label: 'Kategori', type: 'select', options: TASK_CATEGORIES },
            { key: 'minutes', label: 'Süre', type: 'number', min: 1, max: 1440, suffix: 'dk', className: 'w-32' },
          ]}
          rows={durations}
          newRowDefaults={{ name: '', category: TASK_CATEGORIES[0], minutes: 15 }}
          validate={validateDuration}
          canEdit={canEdit}
          lockedReason={lockedReason}
          emptyText="Tanımlı görev süresi yok."
          {...crud(durations, setDurations, 'Görev Süresi', describeDuration)}
        />

        <ConfigTable
          title="Oda ve Cihaz Kapasiteleri"
          description="Aynı anda yürütülebilecek azami işlem sayısı; kaynak çakışma kontrolünde kullanılacak."
          icon={Boxes}
          columns={[
            { key: 'name', label: 'Oda / Cihaz', type: 'text' },
            { key: 'type', label: 'Tür', type: 'select', options: RESOURCE_TYPES, className: 'w-24' },
            { key: 'capacity', label: 'Kapasite', type: 'number', min: 1, max: 999, className: 'w-24' },
            { key: 'unit', label: 'Birim', type: 'text' },
          ]}
          rows={resources}
          newRowDefaults={{ name: '', type: 'Cihaz', capacity: 1, unit: 'eşzamanlı kullanım' }}
          validate={validateResource}
          canEdit={canEdit}
          lockedReason={lockedReason}
          emptyText="Tanımlı oda veya cihaz yok."
          {...crud(resources, setResources, 'Kapasite', describeResource)}
        />
      </div>

      <section className="bg-white border border-slate-200 rounded-lg shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center gap-2">
          <History className="w-4 h-4 text-blue-700" />
          <h3 className="text-sm font-semibold text-slate-800">Değişiklik Geçmişi (Denetim İzi)</h3>
          <span className="ml-auto text-xs text-slate-500">{settingsLog.length} kayıt</span>
        </div>
        {settingsLog.length === 0 ? (
          <p className="p-6 text-center text-xs text-slate-400">Bu oturumda henüz değişiklik yapılmadı.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {settingsLog.map((e) => (
              <li key={e.id} className="px-5 py-3 text-xs grid grid-cols-1 md:grid-cols-[150px_110px_1fr] gap-2">
                <div className="text-slate-500">
                  {fmtDateTime(e.at)}
                  <div className="text-slate-700 font-medium">{e.editor} ({ROLE_SHORT[e.editorRole] || e.editorRole})</div>
                </div>
                <div>
                  <span className={`font-semibold px-1.5 py-0.5 rounded ${ACTION_STYLE[e.action]}`}>{e.action}</span>
                  <div className="text-slate-500 mt-1">{e.entity}</div>
                </div>
                <div className="space-y-0.5">
                  {e.before && <p className="text-slate-500 line-through">{e.before}</p>}
                  {e.after && <p className="text-slate-800">{e.after}</p>}
                  <p className="text-slate-500 italic">Gerekçe: {e.reason}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
