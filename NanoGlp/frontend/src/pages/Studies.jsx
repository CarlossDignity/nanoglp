import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Plus,
  Calendar,
  User,
  FileDown,
  Loader2,
  X,
  Lock,
  ExternalLink,
  AlertTriangle,
  Clock,
} from 'lucide-react';
import { createStudy, downloadStudyPlanDocx, getStudySchedule, extractError } from '../services/api';
import { useAuth } from '../state/AuthContext';
import { usePreferences } from '../state/PreferencesContext';
import { fmtMinutes, fmtTime, ROLE_SHORT } from '../utils/format';

const FORBIDDEN_SD_ROLES = new Set(['SYSADMIN', 'ADMIN', 'EXECUTIVE', 'SALES', 'TRM_KABUL', 'TRM_ACCEPTANCE']);

const STEP_STATUS_BADGE = {
  PENDING: { label: 'Bekliyor', cls: 'bg-slate-100 text-slate-700 border-slate-200' },
  IN_PROGRESS: { label: 'Devam Ediyor', cls: 'bg-blue-50 text-blue-800 border-blue-200' },
  COMPLETED: { label: 'Tamamlandı', cls: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
};

function fmtDateTR(iso) {
  if (!iso) return '—';
  const s = String(iso).slice(0, 10);
  const [y, m, d] = s.split('-');
  if (!y || !m || !d) return s;
  return `${d}.${m}.${y}`;
}

export default function Studies({ studies = [], personnel = [], onRefresh }) {
  const { isReadOnly } = useAuth();
  const { formatStatusBadge } = usePreferences();
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);
  const [downloadingId, setDownloadingId] = useState(null);
  const [scheduleModalStudy, setScheduleModalStudy] = useState(null);
  const [scheduleDetail, setScheduleDetail] = useState(null);
  const [loadingSchedule, setLoadingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState(null);
  const [formData, setFormData] = useState({
    study_code: '',
    title: '',
    sponsor_name: '',
    test_item_name: '',
    test_item_batch: '',
    test_item_storage_condition: '+4°C Soğuk Muhafaza',
    study_director_id: '',
    qa_officer_id: '',
    status: 'DRAFT',
    description: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const payload = {
        ...formData,
        study_director_id: parseInt(formData.study_director_id, 10),
        qa_officer_id: formData.qa_officer_id ? parseInt(formData.qa_officer_id, 10) : null,
      };
      await createStudy(payload);
      setShowModal(false);
      setFormData({
        study_code: '',
        title: '',
        sponsor_name: '',
        test_item_name: '',
        test_item_batch: '',
        test_item_storage_condition: '+4°C Soğuk Muhafaza',
        study_director_id: '',
        qa_officer_id: '',
        status: 'DRAFT',
        description: '',
      });
      if (onRefresh) onRefresh();
    } catch (err) {
      setError(err.response?.data?.detail || 'Çalışma eklenirken hata oluştu.');
    } finally {
      setLoading(false);
    }
  };

  const directors = personnel.filter(
    (p) =>
      (p.role === 'STUDY_DIRECTOR' || p.role === 'TFM') &&
      !FORBIDDEN_SD_ROLES.has(String(p.role || '').toUpperCase()) &&
      String(p.username || '').toLowerCase() !== 'yigit' &&
      p.is_active !== false
  );

  const handleOpenScheduleModal = async (study) => {
    setScheduleModalStudy(study);
    setScheduleDetail(null);
    setScheduleError(null);
    setLoadingSchedule(true);
    try {
      const res = await getStudySchedule(study.id);
      setScheduleDetail(res.data || null);
    } catch (err) {
      setScheduleError(extractError(err, 'Çalışma takvimi alınamadı.'));
    } finally {
      setLoadingSchedule(false);
    }
  };

  const handleCloseScheduleModal = () => {
    setScheduleModalStudy(null);
    setScheduleDetail(null);
    setScheduleError(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold text-slate-800">GLP Test Çalışmaları (Studies)</h2>
          <p className="text-sm text-slate-500">
            Nanolab Edirne GLP akreditasyonuna uygun kayıtlı test ve çalışma protokolleri.
          </p>
        </div>
        {!isReadOnly && (
          <button
            onClick={() => setShowModal(true)}
            className="bg-slate-900 hover:bg-slate-800 text-white px-4 py-2 rounded-lg text-xs font-semibold flex items-center space-x-2 shadow-xs transition"
          >
            <Plus className="w-4 h-4" />
            <span>Yeni GLP Çalışması Başlat</span>
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {studies.map((study) => (
          <div key={study.id} className="bg-white border border-slate-200 rounded-lg p-5 shadow-xs space-y-3">
            <div className="flex items-start justify-between">
              <div>
                <span className="text-[10px] font-bold text-blue-700 uppercase bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                  {study.study_code}
                </span>
                <h3 className="font-bold text-slate-900 text-sm mt-1">{study.title}</h3>
              </div>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                {formatStatusBadge(study.status)}
              </span>
            </div>

            <div className="space-y-1.5 text-xs text-slate-600">
              <p><strong>Sponsor:</strong> {study.sponsor_name || 'Belirtilmedi'}</p>
              <p>
                <strong>Test Maddesi:</strong> {study.test_item_name}{' '}
                {study.test_item_batch && (
                  <span className="font-mono text-[11px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-700">
                    Lot: {study.test_item_batch}
                  </span>
                )}
              </p>
              <p><strong>Saklama:</strong> {study.test_item_storage_condition || 'Oda Sıcaklığı'}</p>
              {(study.guideline || study.test_type) && (
                <p>
                  <strong>Kılavuz / Test:</strong> {[study.guideline, study.test_type].filter(Boolean).join(' — ')}
                </p>
              )}
              {(study.extraction_polar !== null && study.extraction_polar !== undefined) ||
              (study.extraction_non_polar !== null && study.extraction_non_polar !== undefined) ? (
                <p>
                  <strong>Ekstraksiyon:</strong>{' '}
                  Polar: {study.extraction_polar ? `Evet (${study.extraction_polar_solvent || 'Salin'})` : 'Hayır'}
                  {' · '}
                  Apolar: {study.extraction_non_polar ? `Evet (${study.extraction_non_polar_solvent || 'Yağ'})` : 'Hayır'}
                </p>
              ) : null}
              {(study.animal_species_strain || study.animal_count) && (
                <p>
                  <strong>Hayvan Modeli:</strong> {study.animal_species_strain || '—'}{' '}
                  {study.animal_count && `(${study.animal_count})`}
                </p>
              )}
            </div>

            <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
              <span className="flex items-center space-x-1">
                <User className="w-3.5 h-3.5 text-slate-400" />
                <span>
                  SD: {study.study_director?.full_name || `#${study.study_director_id}`}
                </span>
              </span>
              <span>Adım Sayısı: {study.steps ? study.steps.length : 0}</span>
            </div>

            <div className="pt-1 flex flex-col gap-2">
              <button
                type="button"
                onClick={() => handleOpenScheduleModal(study)}
                className="w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-slate-800 bg-slate-100 hover:bg-slate-200 border border-slate-300 rounded-lg px-3 py-2 transition"
              >
                <Calendar className="w-3.5 h-3.5 text-slate-600" />
                <span>Takvimde Görüntüle</span>
              </button>
              <button
                type="button"
                disabled={downloadingId === study.id}
                onClick={async () => {
                  setDownloadingId(study.id);
                  try {
                    await downloadStudyPlanDocx(study.id, study.study_code);
                  } finally {
                    setDownloadingId(null);
                  }
                }}
                className="w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg px-3 py-2 transition disabled:opacity-50"
              >
                {downloadingId === study.id ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <FileDown className="w-3.5 h-3.5" />
                )}
                <span>Study Plan Taslağı İndir (.docx)</span>
              </button>
            </div>
          </div>
        ))}
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6 border border-slate-200 max-h-[90vh] overflow-y-auto">
            <h3 className="text-base font-bold text-slate-900 mb-4">Yeni GLP Çalışması Tanımla</h3>
            {error && <div className="p-3 mb-3 bg-red-50 text-red-700 rounded-lg text-xs">{error}</div>}
            <form onSubmit={handleSubmit} className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Çalışma Kodu *</label>
                  <input
                    type="text"
                    required
                    value={formData.study_code}
                    onChange={(e) => setFormData({ ...formData, study_code: e.target.value })}
                    className="w-full border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    placeholder="GLP-2026-EDR-001"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Sponsor / Müşteri</label>
                  <input
                    type="text"
                    value={formData.sponsor_name}
                    onChange={(e) => setFormData({ ...formData, sponsor_name: e.target.value })}
                    className="w-full border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    placeholder="Nanolab Pharma"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">Çalışma Başlığı *</label>
                <input
                  type="text"
                  required
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                  className="w-full border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                  placeholder="In Vitro Sitotoksisite Testi (OECD 10993-5)"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Test Maddesi / Örnek *</label>
                  <input
                    type="text"
                    required
                    value={formData.test_item_name}
                    onChange={(e) => setFormData({ ...formData, test_item_name: e.target.value })}
                    className="w-full border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    placeholder="Biyopolimer İmplant Örneği"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Lot / Parti No</label>
                  <input
                    type="text"
                    value={formData.test_item_batch}
                    onChange={(e) => setFormData({ ...formData, test_item_batch: e.target.value })}
                    className="w-full border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    placeholder="BATCH-2026-X"
                  />
                </div>
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">Çalışma Yöneticisi (Study Director) *</label>
                <select
                  required
                  value={formData.study_director_id}
                  onChange={(e) => setFormData({ ...formData, study_director_id: e.target.value })}
                  className="w-full border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-blue-500 focus:outline-none bg-white"
                >
                  <option value="">Seçiniz...</option>
                  {directors.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.full_name} ({p.role})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex justify-end space-x-2 pt-4 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3 py-2 border border-slate-300 text-slate-600 rounded-lg hover:bg-slate-50 font-medium"
                >
                  İptal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg font-medium shadow-xs transition"
                >
                  {loading ? 'Oluşturuluyor...' : 'Çalışmayı Kaydet'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* FAZ 8.4: Sayfa Değiştirmeden Açılan Tekil Çalışma Takvimi & Biyolojik Adımlar Modalı */}
      {scheduleModalStudy && (
        <div
          className="fixed inset-0 bg-slate-900/50 z-50 flex items-center justify-center p-4"
          onClick={handleCloseScheduleModal}
        >
          <div
            className="bg-white rounded-lg shadow-xl border border-slate-200 max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Üst Başlık Bandı */}
            <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 bg-slate-50/70">
              <div className="flex flex-wrap items-center gap-2">
                <Calendar className="w-4 h-4 text-slate-600" />
                <span className="font-mono text-sm font-bold text-slate-900">
                  {scheduleModalStudy.study_code}
                </span>
                <span className="text-[11px] font-bold px-2 py-0.5 rounded border bg-white text-slate-700 border-slate-300">
                  {formatStatusBadge(scheduleDetail?.study_status || scheduleModalStudy.status)}
                </span>
                <span className="text-xs font-medium text-slate-600 truncate max-w-md">
                  — {scheduleDetail?.title || scheduleModalStudy.title}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const targetId = scheduleModalStudy.id;
                    handleCloseScheduleModal();
                    navigate('/planning', { state: { selectedStudyId: targetId } });
                  }}
                  className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-900 hover:underline px-2 py-1 rounded"
                  title="Çoklu Çalışma Planlama ekranında düzenlemek için aç"
                >
                  <span>Master Planlamada Düzenle</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={handleCloseScheduleModal}
                  className="p-1.5 rounded-md text-slate-500 hover:text-slate-800 hover:bg-slate-200/60"
                  aria-label="Kapat"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* İçerik Gövdesi */}
            <div className="p-5 overflow-y-auto space-y-4 flex-1">
              {/* Çalışma Özet Kartları */}
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5 text-xs">
                <div className="border border-slate-200 rounded-md p-2.5 bg-slate-50/50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    GLP Kodu
                  </span>
                  <span className="font-mono font-bold text-slate-900 mt-0.5 block">
                    {scheduleModalStudy.study_code}
                  </span>
                </div>
                <div className="border border-slate-200 rounded-md p-2.5 bg-slate-50/50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Test Türü / Şablon
                  </span>
                  <span className="font-medium text-slate-800 mt-0.5 block truncate" title={scheduleDetail?.template?.title || scheduleModalStudy.test_type || scheduleModalStudy.title}>
                    {scheduleDetail?.template
                      ? `${scheduleDetail.template.standard} — ${scheduleDetail.template.title}`
                      : scheduleModalStudy.test_type || scheduleModalStudy.title}
                  </span>
                </div>
                <div className="border border-slate-200 rounded-md p-2.5 bg-slate-50/50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Sponsor
                  </span>
                  <span className="font-medium text-slate-800 mt-0.5 block truncate" title={scheduleDetail?.sponsor_name || scheduleModalStudy.sponsor_name || 'Belirtilmedi'}>
                    {scheduleDetail?.sponsor_name || scheduleModalStudy.sponsor_name || 'Belirtilmedi'}
                  </span>
                </div>
                <div className="border border-slate-200 rounded-md p-2.5 bg-slate-50/50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Çalışma Yöneticisi (SD)
                  </span>
                  <span className="font-medium text-slate-800 mt-0.5 block truncate">
                    {scheduleDetail?.study_director_name ||
                      scheduleModalStudy.study_director?.full_name ||
                      `#${scheduleModalStudy.study_director_id}`}
                  </span>
                </div>
                <div className="border border-slate-200 rounded-md p-2.5 bg-slate-50/50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Başlangıç (Gün 0)
                  </span>
                  <span className="font-mono font-semibold text-slate-900 mt-0.5 block">
                    {fmtDateTR(scheduleDetail?.acclimatization_start_date || scheduleModalStudy.acclimatization_start_date)}
                  </span>
                </div>
                <div className="border border-slate-200 rounded-md p-2.5 bg-slate-50/50">
                  <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Bitiş / Rapor Hedefi
                  </span>
                  <span className="font-mono font-semibold text-slate-900 mt-0.5 block">
                    {fmtDateTR(scheduleDetail?.target_end_date || scheduleModalStudy.target_end_date)}
                  </span>
                </div>
              </div>

              {/* Varsa Test Kısıtlaması Otomatik Öteleme Bildirimi */}
              {scheduleDetail?.auto_schedule_notice?.text && (
                <div className="rounded-md border border-slate-200 border-l-4 border-l-amber-500 bg-amber-50/50 px-3.5 py-2.5 text-xs text-slate-800 flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                  <span>{scheduleDetail.auto_schedule_notice.text}</span>
                </div>
              )}

              {scheduleError && (
                <div className="p-3 rounded-md bg-red-50 border border-red-200 text-xs text-red-700">
                  {scheduleError}
                </div>
              )}

              {/* Biyolojik Takvim Tablosu */}
              {loadingSchedule ? (
                <div className="py-12 flex items-center justify-center gap-2 text-xs text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin text-slate-600" />
                  <span>Çalışma takvimi ve biyolojik adımlar yükleniyor…</span>
                </div>
              ) : !scheduleDetail?.steps || scheduleDetail.steps.length === 0 ? (
                <div className="border border-slate-200 rounded-lg p-8 text-center space-y-2 bg-slate-50/40">
                  <Clock className="w-5 h-5 text-slate-400 mx-auto" />
                  <p className="text-xs font-medium text-slate-700">
                    Bu çalışma için henüz adım bazlı biyolojik takvim oluşturulmamış.
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Sağ üstteki <strong>Master Planlamada Düzenle</strong> bağlantısından veya Numune & Çalışma Takip ekranından otomatik takvim oluşturabilirsiniz.
                  </p>
                </div>
              ) : (
                <div className="border border-slate-200 rounded-lg overflow-hidden">
                  <div className="px-4 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-800">
                      Biyolojik Adım Takvimi ({scheduleDetail.steps.length} Adım)
                    </span>
                    <span className="text-[11px] text-slate-500">
                      Kritik Çakışma: <strong>{scheduleDetail.critical_conflicts ?? 0}</strong> · Uyarı:{' '}
                      <strong>{scheduleDetail.warning_conflicts ?? 0}</strong>
                    </span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-slate-50/80 text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
                        <tr>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Gün</th>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Tarih</th>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Adım Adı</th>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Saat / Süre</th>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Atanan Personel</th>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Cihaz / Kilit</th>
                          <th className="text-left px-3.5 py-2.5 font-semibold">Durum</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {scheduleDetail.steps.map((st) => {
                          const stBadge = STEP_STATUS_BADGE[st.status] || STEP_STATUS_BADGE.PENDING;
                          return (
                            <tr key={st.id} className="hover:bg-slate-50/70">
                              <td className="px-3.5 py-2.5 font-mono font-bold text-slate-800 whitespace-nowrap">
                                G{st.study_day}
                              </td>
                              <td className="px-3.5 py-2.5 font-mono text-slate-600 whitespace-nowrap">
                                {fmtDateTR(st.planned_start)}
                              </td>
                              <td className="px-3.5 py-2.5 font-medium text-slate-900">
                                {st.step_name}
                              </td>
                              <td className="px-3.5 py-2.5 font-mono text-slate-600 whitespace-nowrap">
                                {fmtTime(st.planned_start)}–{fmtTime(st.planned_end)} ({fmtMinutes(st.duration_minutes)})
                              </td>
                              <td className="px-3.5 py-2.5 text-slate-700">
                                {st.assignees && st.assignees.length > 0 ? (
                                  st.assignees
                                    .map((a) => `${a.full_name} (${ROLE_SHORT[a.role] || a.role})`)
                                    .join(', ')
                                ) : (
                                  <span className="text-slate-400 italic">Atanmadı</span>
                                )}
                              </td>
                              <td className="px-3.5 py-2.5 text-slate-600 whitespace-nowrap">
                                {st.equipment_id ? (
                                  <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 mr-1.5">
                                    EQ-WB-001
                                  </span>
                                ) : null}
                                {st.is_biological_fixed_time ? (
                                  <span className="inline-flex items-center gap-1 text-blue-700 font-medium">
                                    <Lock className="w-3 h-3" /> ±{st.biological_tolerance_minutes} dk
                                  </span>
                                ) : (
                                  <span className="text-slate-400">Esnek</span>
                                )}
                              </td>
                              <td className="px-3.5 py-2.5 whitespace-nowrap">
                                <span
                                  className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${stBadge.cls}`}
                                >
                                  {stBadge.label}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* Alt Aksiyon Çubuğu */}
            <div className="px-5 py-3 border-t border-slate-200 bg-slate-50/70 flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                disabled={downloadingId === scheduleModalStudy.id}
                onClick={async () => {
                  setDownloadingId(scheduleModalStudy.id);
                  try {
                    await downloadStudyPlanDocx(scheduleModalStudy.id, scheduleModalStudy.study_code);
                  } finally {
                    setDownloadingId(null);
                  }
                }}
                className="inline-flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold px-4 py-2 rounded-md shadow-xs transition disabled:opacity-50"
              >
                {downloadingId === scheduleModalStudy.id ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <FileDown className="w-3.5 h-3.5" />
                )}
                <span>Study Plan İndir (.docx)</span>
              </button>

              <button
                type="button"
                onClick={handleCloseScheduleModal}
                className="px-4 py-2 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-md"
              >
                Kapat
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
