import React, { useCallback, useEffect, useState } from 'react';
import {
  Timer,
  Boxes,
  History,
  UserCheck,
  CheckCircle2,
  Eye,
  Save,
  Lock,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { getCalibration, updateCalibration, extractError } from '../services/api';
import { useAuth } from '../state/AuthContext';
import { fmtDateTime, ROLE_SHORT, ROLE_LABEL } from '../utils/format';

const MIN_REASON = 3;

export default function Settings() {
  const { user, isReadOnly, canWriteManagement } = useAuth();

  const [steps, setSteps] = useState([]);
  const [equipment, setEquipment] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);
  const [savingEq, setSavingEq] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const [reason, setReason] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState('ISO_10993_23_IC');

  // Satır içi düzenleme state'i: { [stepId]: { duration_minutes, tolerance_minutes, start_time } }
  const [stepEdits, setStepEdits] = useState({});
  // Su banyosu kapasite düzenleme state'i
  const [polarCap, setPolarCap] = useState(3);
  const [apolarCap, setApolarCap] = useState(1);

  const canEdit = Boolean(user && canWriteManagement && !isReadOnly && reason.trim().length >= MIN_REASON);

  const applyServerData = useCallback((data) => {
    const stepList = data?.steps || [];
    const eqList = data?.equipment || [];
    setSteps(stepList);
    setEquipment(eqList);
    setAuditLogs(data?.audit_logs || []);

    const editsMap = {};
    for (const s of stepList) {
      editsMap[s.id] = {
        duration_minutes: s.duration_minutes,
        tolerance_minutes: s.tolerance_minutes,
        start_time: s.start_time,
      };
    }
    setStepEdits(editsMap);

    const wb = eqList.find((e) => e.code === 'EQ-WB-001') || eqList[0];
    if (wb) {
      setPolarCap(wb.polar_capacity ?? 3);
      setApolarCap(wb.non_polar_capacity ?? 1);
    }
  }, []);

  const loadCalibration = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getCalibration();
      applyServerData(res.data);
    } catch (err) {
      setError(extractError(err, 'Sistem kalibrasyon verileri veritabanından alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, [applyServerData]);

  useEffect(() => {
    loadCalibration();
  }, [loadCalibration]);

  const handleStepFieldChange = (stepId, field, value) => {
    setStepEdits((prev) => ({
      ...prev,
      [stepId]: {
        ...(prev[stepId] || {}),
        [field]: value,
      },
    }));
  };

  const handleSaveStep = async (step) => {
    if (!canEdit) return;
    const edited = stepEdits[step.id] || {};
    setSavingId(step.id);
    setError(null);
    setNotice(null);
    try {
      const res = await updateCalibration({
        reason: reason.trim(),
        step_id: step.id,
        duration_minutes: Number(edited.duration_minutes),
        tolerance_minutes: Number(edited.tolerance_minutes),
        start_time: edited.start_time,
      });
      applyServerData(res.data);
      setNotice(
        `'${step.step_name}' adımının süre/tolerans kalibrasyonu veritabanında güncellendi ve GLP AuditLog'a kaydedildi.`
      );
    } catch (err) {
      setError(extractError(err, 'Kalibrasyon adımı güncellenemedi.'));
    } finally {
      setSavingId(null);
    }
  };

  const handleSaveEquipment = async (e) => {
    e.preventDefault();
    if (!canEdit) return;
    setSavingEq(true);
    setError(null);
    setNotice(null);
    try {
      const res = await updateCalibration({
        reason: reason.trim(),
        equipment_code: 'EQ-WB-001',
        polar_capacity: Number(polarCap),
        non_polar_capacity: Number(apolarCap),
      });
      applyServerData(res.data);
      setNotice(
        'Çalkalamalı Su Banyosu 1 (EQ-WB-001) Polar/Apolar kapasiteleri veritabanında güncellendi ve GLP AuditLog kaydı üretildi.'
      );
    } catch (err) {
      setError(extractError(err, 'Cihaz kapasitesi güncellenemedi.'));
    } finally {
      setSavingEq(false);
    }
  };

  const templateOptions = Array.from(
    new Map(steps.map((s) => [s.template_code, s.template_label || s.template_code])).entries()
  );
  const filteredSteps =
    selectedTemplate === 'ALL' ? steps : steps.filter((s) => s.template_code === selectedTemplate);
  const waterBath = equipment.find((e) => e.code === 'EQ-WB-001') || equipment[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Sistem Kalibrasyonu (Canlı Veritabanı)</h2>
          <p className="text-sm text-slate-500">
            Standart görev süreleri, biyolojik toleranslar ve Çalkalamalı Su Banyosu (EQ-WB-001) Polar/Apolar
            kapasiteleri doğrudan SQLite veritabanından okunur ve zamanlama motorunu (scheduling_engine.py) besler.
          </p>
        </div>
        <button
          type="button"
          onClick={loadCalibration}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Yenile
        </button>
      </div>

      {isReadOnly ? (
        <div className="flex items-center gap-2.5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <Eye className="w-4 h-4 text-amber-700 shrink-0" />
          <span>
            <strong>Kalite Güvence (QA) Salt Okunur Modu:</strong> Standart görev sürelerini, toleransları, cihaz
            kapasitelerini ve denetim izi geçmişini inceleyebilirsiniz; değerleri değiştirme yetkiniz kapalıdır.
          </span>
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-700 shrink-0 mt-0.5" />
          <p className="text-xs text-emerald-950 leading-relaxed">
            <strong>Canlı Veritabanı Bağlantısı Aktif (`/api/v1/planning/calibration`):</strong> Bu ekranda yaptığınız
            tüm süre, tolerans ve kapasite güncellemeleri kalıcı olarak veritabanına kaydedilir, elektronik imzanızla{' '}
            <code>AuditLog</code> tablosuna işlenir ve yeni çalışma planlamalarında doğrudan kullanılır.
          </p>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-xs font-medium text-red-800">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-3 text-xs font-medium text-blue-900">
          {notice}
        </div>
      )}

      {/* Oturum Açmış Yönetici + Gerekçe (JWT Doğrulamalı GLP Denetim İzi) */}
      <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-5">
        <div className="flex items-center gap-2 mb-3">
          <UserCheck className="w-4 h-4 text-blue-700" />
          <h3 className="text-sm font-semibold text-slate-800">Elektronik İmza ve Değişiklik Gerekçesi (JWT & GLP AuditLog)</h3>
          <span
            className={`ml-auto text-[11px] font-medium px-2 py-0.5 rounded ${
              canEdit ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-500'
            }`}
          >
            {canEdit ? 'Düzenleme açık' : `Gerekçe girin (min. ${MIN_REASON} karakter)`}
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
            <span className="block text-xs font-medium text-slate-700 mb-1.5">
              GLP Değişiklik Gerekçesi (Kaydet butonlarını aktif etmek için zorunludur)
            </span>
            <input
              value={reason}
              disabled={isReadOnly || !canWriteManagement}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                isReadOnly
                  ? 'QA rolü salt okunur yetkiye sahiptir'
                  : 'Örn. SOP revizyonu / zaman etüdü doğrultusunda görev süresi ve su banyosu kapasitesi güncellendi'
              }
              className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:bg-slate-100"
            />
          </label>
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[1.6fr_1fr] gap-6 items-start">
        {/* 1) Görev Süreleri, Saatleri ve Biyolojik Toleranslar */}
        <section className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Timer className="w-4 h-4 text-blue-700" />
              <div>
                <h3 className="text-sm font-semibold text-slate-800">
                  Şablon Görev Süreleri ve Biyolojik Toleranslar
                </h3>
                <p className="text-xs text-slate-500">
                  9 saatlik (540 dk) günlük iş yükü ve biyolojik zaman kilidi hesaplarında kullanılır.
                </p>
              </div>
            </div>

            <select
              aria-label="Şablon Filtresi"
              value={selectedTemplate}
              onChange={(e) => setSelectedTemplate(e.target.value)}
              className="border border-slate-300 rounded-md px-2.5 py-1.5 text-xs bg-white font-medium text-slate-800"
            >
              {templateOptions.map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
              <option value="ALL">Tüm Şablonlar ({steps.length} adım)</option>
            </select>
          </div>

          {loading ? (
            <div className="p-8 text-center text-xs text-slate-400">Veritabanından yükleniyor…</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-semibold">Gün / Adım</th>
                    <th className="text-left px-3 py-2.5 font-semibold">Kategori</th>
                    <th className="text-center px-3 py-2.5 font-semibold">Başlangıç</th>
                    <th className="text-center px-3 py-2.5 font-semibold">Süre (dk)</th>
                    <th className="text-center px-3 py-2.5 font-semibold">Tolerans (±dk)</th>
                    <th className="text-right px-4 py-2.5 font-semibold">İşlem</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredSteps.map((st) => {
                    const edit = stepEdits[st.id] || {
                      duration_minutes: st.duration_minutes,
                      tolerance_minutes: st.tolerance_minutes,
                      start_time: st.start_time,
                    };
                    const isDirty =
                      Number(edit.duration_minutes) !== st.duration_minutes ||
                      Number(edit.tolerance_minutes) !== st.tolerance_minutes ||
                      String(edit.start_time) !== st.start_time;

                    return (
                      <tr key={st.id} className="hover:bg-slate-50/70">
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-1.5 font-medium text-slate-900">
                            <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-50 text-blue-800 border border-blue-200">
                              G{st.study_day}
                            </span>
                            {st.is_biological_fixed_time && (
                              <Lock className="w-3 h-3 text-blue-700 shrink-0" title="Biyolojik Zaman Kilitli" />
                            )}
                            <span>{st.step_name}</span>
                          </div>
                          {selectedTemplate === 'ALL' && (
                            <span className="text-[10px] text-slate-400 font-mono">{st.template_code}</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-slate-600">{st.step_type}</td>
                        <td className="px-3 py-2.5 text-center">
                          <input
                            type="time"
                            disabled={isReadOnly || !canWriteManagement}
                            value={edit.start_time}
                            onChange={(e) => handleStepFieldChange(st.id, 'start_time', e.target.value)}
                            className="w-24 border border-slate-300 rounded px-2 py-1 text-center font-mono text-xs disabled:bg-slate-100"
                          />
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <input
                            type="number"
                            min={1}
                            max={1440}
                            disabled={isReadOnly || !canWriteManagement}
                            value={edit.duration_minutes}
                            onChange={(e) => handleStepFieldChange(st.id, 'duration_minutes', e.target.value)}
                            className="w-20 border border-slate-300 rounded px-2 py-1 text-center font-mono text-xs disabled:bg-slate-100"
                          />
                        </td>
                        <td className="px-3 py-2.5 text-center">
                          <input
                            type="number"
                            min={0}
                            max={720}
                            disabled={isReadOnly || !canWriteManagement || !st.is_biological_fixed_time}
                            value={edit.tolerance_minutes}
                            onChange={(e) => handleStepFieldChange(st.id, 'tolerance_minutes', e.target.value)}
                            className="w-20 border border-slate-300 rounded px-2 py-1 text-center font-mono text-xs disabled:bg-slate-100"
                          />
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <button
                            type="button"
                            disabled={!canEdit || !isDirty || savingId === st.id}
                            onClick={() => handleSaveStep(st)}
                            title={!canEdit ? 'Önce değişiklik gerekçesi girin' : 'Veritabanına kaydet'}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-blue-700 text-white hover:bg-blue-800 disabled:bg-slate-200 disabled:text-slate-400"
                          >
                            {savingId === st.id ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <Save className="w-3 h-3" />
                            )}
                            Kaydet
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* 2) Çalkalamalı Su Banyosu 1 (EQ-WB-001) Polar / Apolar Kapasiteleri */}
        <section className="bg-white border border-slate-200 rounded-lg shadow-sm p-5 space-y-4">
          <div className="flex items-start gap-2.5">
            <Boxes className="w-4 h-4 text-blue-700 mt-0.5 shrink-0" />
            <div>
              <h3 className="text-sm font-semibold text-slate-800">
                Çalkalamalı Su Banyosu 1 (EQ-WB-001) Kapasite Kalibrasyonu
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                72 saatlik ekstraksiyon penceresinde aynı anda yürütülebilecek azami Polar ve Apolar çalışma sayısı.
                Aşıldığında sistem <code>EQUIPMENT_OVERLAP</code> çakışması üretir.
              </p>
            </div>
          </div>

          <form onSubmit={handleSaveEquipment} className="space-y-4 pt-2 border-t border-slate-100">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="block p-3 rounded-lg border border-blue-200 bg-blue-50/40">
                <span className="block text-xs font-bold text-blue-950 mb-1">
                  Polar Ekstraksiyon Kapasitesi (Max Çalışma)
                </span>
                <span className="block text-[11px] text-slate-600 mb-2">
                  Örn. %0.9 NaCl / Kültür Besiyeri (Varsayılan: 3)
                </span>
                <input
                  type="number"
                  min={1}
                  max={99}
                  disabled={isReadOnly || !canWriteManagement}
                  value={polarCap}
                  onChange={(e) => setPolarCap(e.target.value)}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm font-mono bg-white focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:bg-slate-100"
                />
              </label>

              <label className="block p-3 rounded-lg border border-amber-200 bg-amber-50/40">
                <span className="block text-xs font-bold text-amber-950 mb-1">
                  Apolar (Non-Polar) Kapasitesi (Max Çalışma)
                </span>
                <span className="block text-[11px] text-slate-600 mb-2">
                  Örn. Pamuk Tohumu Yağı / Susam Yağı (Varsayılan: 1)
                </span>
                <input
                  type="number"
                  min={1}
                  max={99}
                  disabled={isReadOnly || !canWriteManagement}
                  value={apolarCap}
                  onChange={(e) => setApolarCap(e.target.value)}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm font-mono bg-white focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:bg-slate-100"
                />
              </label>
            </div>

            <div className="flex items-center justify-between gap-3 pt-1">
              <div className="text-xs text-slate-500">
                Kayıtlı Değerler:{' '}
                <strong>
                  Polar Max: {waterBath?.polar_capacity ?? 3} • Apolar Max: {waterBath?.non_polar_capacity ?? 1}
                </strong>
              </div>
              <button
                type="submit"
                disabled={
                  !canEdit ||
                  savingEq ||
                  (Number(polarCap) === (waterBath?.polar_capacity ?? 3) &&
                    Number(apolarCap) === (waterBath?.non_polar_capacity ?? 1))
                }
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-xs font-semibold bg-blue-700 text-white hover:bg-blue-800 disabled:bg-slate-200 disabled:text-slate-400"
              >
                {savingEq ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Kapasiteleri Veritabanına Kaydet
              </button>
            </div>
          </form>
        </section>
      </div>

      {/* 3) Gerçek Veritabanı AuditLog Geçmişi */}
      <section className="bg-white border border-slate-200 rounded-lg shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center gap-2">
          <History className="w-4 h-4 text-blue-700" />
          <h3 className="text-sm font-semibold text-slate-800">
            Sistem Kalibrasyonu Değişiklik Geçmişi (Veritabanı AuditLog)
          </h3>
          <span className="ml-auto text-xs text-slate-500">{auditLogs.length} kayıt</span>
        </div>
        {auditLogs.length === 0 ? (
          <p className="p-6 text-center text-xs text-slate-400">
            Veritabanında henüz kalibrasyon değişikliği kaydı bulunmuyor.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {auditLogs.map((log) => (
              <li
                key={log.id}
                className="px-5 py-3 text-xs grid grid-cols-1 md:grid-cols-[170px_160px_1fr] gap-2 items-start"
              >
                <div className="text-slate-500">
                  {fmtDateTime(log.timestamp)}
                  <div className="text-slate-700 font-medium">
                    {log.editor} ({ROLE_SHORT[log.editor_role] || log.editor_role})
                  </div>
                </div>
                <div>
                  <span className="font-semibold px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                    {log.action}
                  </span>
                  <div className="text-slate-500 mt-1">{log.entity_name}</div>
                </div>
                <div className="space-y-1">
                  {log.old_values && (
                    <p className="text-slate-500 line-through font-mono text-[11px]">
                      Önce: {JSON.stringify(log.old_values)}
                    </p>
                  )}
                  {log.new_values && (
                    <p className="text-slate-800 font-mono text-[11px]">
                      Sonra: {JSON.stringify(log.new_values)}
                    </p>
                  )}
                  <p className="text-slate-600 italic">Gerekçe: {log.reason}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
