import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FlaskConical, Plus, Calendar, User, FileText, FileDown, Loader2 } from 'lucide-react';
import { createStudy, downloadStudyPlanDocx } from '../services/api';
import { useAuth } from '../state/AuthContext';

export default function Studies({ studies = [], personnel = [], onRefresh }) {
  const { isReadOnly } = useAuth();
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);
  const [downloadingId, setDownloadingId] = useState(null);
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

  const directors = personnel.filter(p => p.role === 'STUDY_DIRECTOR' || p.role === 'TFM' || p.role === 'ADMIN');
  const qaOfficers = personnel.filter(p => p.role === 'QA' || p.role === 'ADMIN');

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
                {study.status}
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
                onClick={() => navigate('/planning', { state: { selectedStudyId: study.id } })}
                className="w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-300 rounded-lg px-3 py-2 transition"
              >
                <Calendar className="w-3.5 h-3.5 text-slate-500" />
                <span>Takvim & Planlamada Aç</span>
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
                  {personnel.map((p) => (
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
    </div>
  );
}
