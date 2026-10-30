import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  UploadCloud,
  FileText,
  FileSpreadsheet,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Sparkles,
  CalendarPlus,
  X,
  Eye,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Hash,
  Layers,
  FlaskConical,
  Building2,
  ShieldCheck,
  Trash2,
  ScanEye,
  FolderKanban,
  Plus,
  UserCheck,
} from 'lucide-react';
import {
  uploadDocument,
  getDocuments,
  getDossiers,
  getDossier,
  reparseDocument,
  reparseAllDocuments,
  deleteDocument,
  extractError,
} from '../services/api';
import { useAuth } from '../state/AuthContext';
import { fmtDateTime } from '../utils/format';

const ACCEPTED_EXT = ['pdf', 'xlsx', 'png', 'jpg', 'jpeg', 'txt', 'csv'];
const MAX_MB = 25;

const fmtSize = (b) =>
  b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`;

const extOf = (name) => (name || '').split('.').pop().toLowerCase();

const STATUS = {
  UPLOADING: { label: 'Yükleniyor', cls: 'bg-slate-100 text-slate-700 border-slate-200', Icon: Loader2, spin: true },
  ANALYZING: { label: 'Vision OCR Okuyor…', cls: 'bg-blue-50 text-blue-700 border-blue-200', Icon: Sparkles, spin: true },
  PARSED: { label: 'Analiz Tamamlandı', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', Icon: CheckCircle2 },
  NEEDS_REVIEW: { label: 'İnceleme Önerilir', cls: 'bg-amber-50 text-amber-800 border-amber-300', Icon: AlertTriangle },
  FAILED: { label: 'Analiz Başarısız', cls: 'bg-red-600 text-white border-red-600', Icon: XCircle },
};

const CATEGORY_STYLE = {
  CONTRACT_ORDER: 'bg-indigo-50 text-indigo-800 border-indigo-200',
  TIIS_FORM: 'bg-blue-50 text-blue-800 border-blue-200',
  COA_CERTIFICATE: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  ANIMAL_ORIGIN_CERT: 'bg-amber-50 text-amber-800 border-amber-200',
  FM083_ACCLIMATIZATION: 'bg-purple-50 text-purple-800 border-purple-200',
  SD_ASSIGNMENT: 'bg-sky-50 text-sky-800 border-sky-200',
  OTHER: 'bg-slate-100 text-slate-700 border-slate-200',
};

let localSeq = 0;

function formatFieldValue(val) {
  if (val === null || val === undefined || val === '') return null;
  if (typeof val === 'boolean') return val ? 'Evet (İşaretli ☑)' : 'Hayır (İşaretsiz ☐)';
  if (Array.isArray(val)) return val.join(', ');
  return String(val);
}

function MergedFieldCard({ item, extraText }) {
  if (!item || item.value === null || item.value === undefined || item.value === '') return null;
  const display = formatFieldValue(item.value);
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 flex flex-col justify-between gap-1.5">
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{item.label}</p>
        <p className="text-xs font-semibold text-slate-900 mt-0.5 break-words">
          {display}
          {extraText ? <span className="font-normal text-slate-600"> — {extraText}</span> : null}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-1 pt-1 border-t border-slate-200/70">
        <span
          className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-white border border-slate-200 text-blue-700 truncate max-w-full"
          title={`Kaynak Belge: ${item.source_filename} (${item.doc_category_label})`}
        >
          <FileText className="w-2.5 h-2.5 shrink-0" />
          {item.source_filename}
        </span>
        {item.all_sources?.length > 1 && (
          <span className="text-[10px] text-slate-400">+{item.all_sources.length - 1} belge</span>
        )}
      </div>
    </div>
  );
}

export default function Upload() {
  const navigate = useNavigate();
  const { isReadOnly, canWriteManagement } = useAuth();
  const canUpload = canWriteManagement && !isReadOnly;

  const [items, setItems] = useState([]);
  const [dossierPackages, setDossierPackages] = useState([
    {
      dossier_key: 'DOSSIER-ELISA-2026',
      dossier_label: 'ELISA TIBBI GEREÇLER — GLP2026-024/026/031/034',
      document_count: 0,
    },
  ]);
  const [activeDossierKey, setActiveDossierKey] = useState('DOSSIER-ELISA-2026');
  const [activeDossierLabel, setActiveDossierLabel] = useState(
    'ELISA TIBBI GEREÇLER — GLP2026-024/026/031/034'
  );
  const [showNewDossierForm, setShowNewDossierForm] = useState(false);
  const [newDossierKey, setNewDossierKey] = useState('');
  const [newDossierLabel, setNewDossierLabel] = useState('');
  const [dossier, setDossier] = useState(null);
  const [selectedStudyCode, setSelectedStudyCode] = useState('');
  const [selectedSdId, setSelectedSdId] = useState('');
  const [dragging, setDragging] = useState(false);
  const [rejected, setRejected] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [reparsingAll, setReparsingAll] = useState(false);
  const [reparsingIds, setReparsingIds] = useState({});
  const [historyError, setHistoryError] = useState(null);
  const [openTech, setOpenTech] = useState({});
  const dragDepth = useRef(0);
  const inputRef = useRef(null);

  const patch = (key, p) => setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...p } : it)));

  const loadAll = useCallback(async (targetKey = activeDossierKey) => {
    setLoadingHistory(true);
    setHistoryError(null);
    try {
      const [pkgsRes, docsRes, dossierRes] = await Promise.all([
        getDossiers(),
        getDocuments({ limit: 100, dossier_key: targetKey }),
        getDossier(targetKey),
      ]);
      const serverPkgs = pkgsRes.data?.dossiers || [];
      setDossierPackages((prev) => {
        const merged = [...serverPkgs];
        prev.forEach((p) => {
          if (!merged.some((m) => m.dossier_key === p.dossier_key)) merged.push(p);
        });
        return merged;
      });
      setItems((prev) => {
        const pending = prev.filter((it) => it.status === 'UPLOADING' || it.status === 'ANALYZING');
        const fromServer = (docsRes.data || []).map((doc) => ({
          key: `doc-${doc.id}`,
          name: doc.original_filename,
          size: doc.size_bytes,
          status: doc.status,
          progress: 100,
          doc,
          error: doc.error_message,
        }));
        return [...pending, ...fromServer];
      });
      const dos = dossierRes.data;
      setDossier(dos);
      setSelectedStudyCode((curr) => {
        if (curr && dos?.study_codes?.includes(curr)) return curr;
        return dos?.default_study_code || dos?.study_codes?.[0] || '';
      });
      if (dos?.sd_resolution?.suggested_sd_id) {
        setSelectedSdId(String(dos.sd_resolution.suggested_sd_id));
      }
    } catch (err) {
      setHistoryError(extractError(err, 'Belge ve çalışma dosyası verileri alınamadı.'));
    } finally {
      setLoadingHistory(false);
    }
  }, [activeDossierKey]);

  useEffect(() => {
    loadAll(activeDossierKey);
  }, [activeDossierKey, loadAll]);

  const refreshDossierOnly = async () => {
    try {
      const [pkgsRes, res] = await Promise.all([getDossiers(), getDossier(activeDossierKey)]);
      if (pkgsRes.data?.dossiers) {
        setDossierPackages((prev) => {
          const merged = [...pkgsRes.data.dossiers];
          prev.forEach((p) => {
            if (!merged.some((m) => m.dossier_key === p.dossier_key)) merged.push(p);
          });
          return merged;
        });
      }
      setDossier(res.data);
      setSelectedStudyCode((curr) => curr || res.data?.default_study_code || res.data?.study_codes?.[0] || '');
      if (res.data?.sd_resolution?.suggested_sd_id && !selectedSdId) {
        setSelectedSdId(String(res.data.sd_resolution.suggested_sd_id));
      }
    } catch {
      // ignore
    }
  };

  const processFile = async (file) => {
    const key = `local-${++localSeq}`;
    setItems((prev) => [{ key, name: file.name, size: file.size, status: 'UPLOADING', progress: 0 }, ...prev]);
    try {
      const res = await uploadDocument(
        file,
        (e) => {
          if (!e.total) return;
          const pct = Math.round((e.loaded / e.total) * 100);
          patch(key, pct >= 100 ? { progress: 100, status: 'ANALYZING' } : { progress: pct });
        },
        activeDossierKey,
        activeDossierLabel
      );
      const doc = res.data;
      patch(key, { key: `doc-${doc.id}`, status: doc.status, doc, progress: 100 });
      await refreshDossierOnly();
    } catch (err) {
      patch(key, { status: 'FAILED', error: extractError(err, 'Belge yüklenemedi veya ayrıştırılamadı.') });
    }
  };

  const handleFiles = (fileList) => {
    if (!canUpload) return;
    const errors = [];
    const accepted = [];
    Array.from(fileList).forEach((f) => {
      const ext = extOf(f.name);
      if (!ACCEPTED_EXT.includes(ext)) errors.push(`${f.name}: desteklenmeyen tür (PDF, XLSX, PNG, JPG, TXT, CSV)`);
      else if (f.size > MAX_MB * 1024 * 1024) errors.push(`${f.name}: ${MAX_MB} MB sınırını aşıyor`);
      else if (f.size === 0) errors.push(`${f.name}: dosya boş`);
      else accepted.push(f);
    });
    setRejected(errors);
    accepted.forEach(processFile);
  };

  const handleReparseSingle = async (doc) => {
    if (!canUpload || !doc?.id) return;
    setReparsingIds((s) => ({ ...s, [doc.id]: true }));
    setHistoryError(null);
    try {
      const res = await reparseDocument(doc.id);
      const updated = res.data;
      setItems((prev) =>
        prev.map((it) =>
          it.doc?.id === doc.id ? { ...it, status: updated.status, doc: updated, error: updated.error_message } : it
        )
      );
      await refreshDossierOnly();
    } catch (err) {
      setHistoryError(extractError(err, `"${doc.original_filename}" yeniden analiz edilemedi.`));
    } finally {
      setReparsingIds((s) => ({ ...s, [doc.id]: false }));
    }
  };

  const handleReparseAll = async () => {
    if (!canUpload) return;
    setReparsingAll(true);
    setHistoryError(null);
    try {
      const res = await reparseAllDocuments({ only_unparsed_vision: false });
      const { documents: updatedDocs, dossier: updatedDossier } = res.data;
      setItems(
        (updatedDocs || []).map((doc) => ({
          key: `doc-${doc.id}`,
          name: doc.original_filename,
          size: doc.size_bytes,
          status: doc.status,
          progress: 100,
          doc,
          error: doc.error_message,
        }))
      );
      if (updatedDossier) {
        setDossier(updatedDossier);
        setSelectedStudyCode(
          (curr) => curr || updatedDossier.default_study_code || updatedDossier.study_codes?.[0] || ''
        );
      }
    } catch (err) {
      setHistoryError(extractError(err, 'Toplu Vision OCR analizi sırasında hata oluştu.'));
    } finally {
      setReparsingAll(false);
    }
  };

  const handleDeleteDoc = async (doc) => {
    if (!canUpload || !doc?.id) return;
    if (!window.confirm(`"${doc.original_filename}" belgesini çalışma dosyasından kaldırmak istiyor musunuz?`)) return;
    try {
      await deleteDocument(doc.id);
      setItems((prev) => prev.filter((it) => it.doc?.id !== doc.id));
      await refreshDossierOnly();
    } catch (err) {
      setHistoryError(extractError(err, 'Belge silinemedi.'));
    }
  };

  const dropHandlers = canUpload
    ? {
        onDragEnter: (e) => {
          e.preventDefault();
          dragDepth.current += 1;
          setDragging(true);
        },
        onDragLeave: (e) => {
          e.preventDefault();
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) setDragging(false);
        },
        onDragOver: (e) => e.preventDefault(),
        onDrop: (e) => {
          e.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        },
      }
    : {};

  const handleCreateNewDossier = (e) => {
    e.preventDefault();
    const k = newDossierKey.trim().toUpperCase().replace(/\s+/g, '-');
    if (!k) return;
    const lbl = newDossierLabel.trim() || k;
    setDossierPackages((prev) => {
      if (prev.some((p) => p.dossier_key === k)) return prev;
      return [{ dossier_key: k, dossier_label: lbl, document_count: 0 }, ...prev];
    });
    setActiveDossierKey(k);
    setActiveDossierLabel(lbl);
    setSelectedStudyCode('');
    setShowNewDossierForm(false);
    setNewDossierKey('');
    setNewDossierLabel('');
  };

  const goToPlanningFromDossier = () => {
    const f = dossier?.fields || {};
    const val = (k) => f[k]?.value ?? null;
    const chosenCode = selectedStudyCode || dossier?.default_study_code || dossier?.study_codes?.[0] || '';
    const mappedTest = dossier?.study_code_mappings?.find((m) => m.study_code === chosenCode)?.test_type;
    const sdRes = dossier?.sd_resolution;
    const resolvedSdId = selectedSdId
      ? parseInt(selectedSdId, 10)
      : sdRes?.suggested_sd_id || null;

    navigate('/planning', {
      state: {
        prefill: {
          from_dossier: true,
          dossier_key: activeDossierKey,
          study_code: chosenCode,
          start_date: val('acclimatization_start_date') || '',
          template_code: dossier?.suggested_template_code || 'ISO_10993_23_IC',
          study_director_id: resolvedSdId,
          former_study_director_name: sdRes?.requires_handover ? sdRes.document_sd_name : null,
          sd_resolution: sdRes || null,
          test_type: mappedTest || val('test_type'),
          guideline: val('guideline'),
          sponsor_name: val('sponsor_name'),
          sponsor_contact: val('sponsor_contact'),
          test_item_name: val('test_item_name'),
          test_item_batch: val('lot_batch_no'),
          manufacture_date: val('manufacture_date'),
          expiry_date: val('expiry_date'),
          test_item_storage_condition: val('storage_conditions'),
          physical_state: val('physical_state'),
          sterility: val('sterility'),
          extraction_polar: val('extraction_polar'),
          extraction_polar_solvent: val('extraction_polar_solvent'),
          extraction_non_polar: val('extraction_non_polar'),
          extraction_non_polar_solvent: val('extraction_non_polar_solvent'),
          extraction_ratio: val('extraction_ratio'),
          extraction_conditions: val('extraction_conditions'),
          animal_species_strain: val('animal_species_strain'),
          animal_count: val('animal_count'),
          animal_birth_date: val('animal_birth_date'),
          requested_start_period: val('requested_start_period'),
          study_director: val('study_director'),
          source_document_ids: dossier?.document_ids || [],
          source_document_id: dossier?.document_ids?.[0] || null,
          source_filename: `${dossier?.total_documents || 0} Belgelik Birleştirilmiş Çalışma Dosyası (${activeDossierKey})`,
          dossier_fields: f,
          cross_checks: dossier?.cross_checks || [],
        },
      },
    });
  };

  const busyCount = items.filter((it) => it.status === 'UPLOADING' || it.status === 'ANALYZING').length;
  const f = dossier?.fields || {};
  const hasAnyDossierData =
    dossier &&
    (dossier.study_codes?.length > 0 || Object.values(f).some((item) => item && item.value !== null));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            Belge Yükleme ve Çoklu Belge Dosya Birleştirme (Vision OCR)
          </h2>
          <p className="text-sm text-slate-500">
            Sözleşme, TIIS, CoA, Hayvan Menşei Sertifikası ve FM.083 belgelerini yükleyin; GPT-4o Vision tüm sayfaları,
            tabloları ve işaretli kutucukları (<span className="font-mono">[X]</span>) okuyarak tek bir Çalışma
            Dosyasında birleştirir.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canUpload && items.length > 0 && (
            <button
              type="button"
              disabled={reparsingAll || busyCount > 0}
              onClick={handleReparseAll}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 border border-blue-300 bg-blue-50 hover:bg-blue-100 disabled:opacity-50 rounded-md px-3 py-2 transition"
            >
              {reparsingAll ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ScanEye className="w-3.5 h-3.5" />}
              {reparsingAll ? 'Tüm Belgeler Vision ile Okunuyor…' : 'Tüm Belgeleri Vision ile Yeniden Analiz Et'}
            </button>
          )}
          <button
            type="button"
            onClick={loadAll}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-600 border border-slate-300 bg-white rounded-md px-3 py-2 hover:bg-slate-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingHistory ? 'animate-spin' : ''}`} /> Yenile
          </button>
        </div>
      </div>

      {isReadOnly && (
        <div className="flex items-center gap-2.5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <Eye className="w-4 h-4 text-amber-700 shrink-0" />
          <span>
            <strong>Kalite Güvence (QA) Salt Okunur Modu:</strong> Birleştirilmiş çalışma dosyasını ve belge analiz
            sonuçlarını denetleyebilirsiniz; belge yükleme ve planlama başlatma yetkiniz kapalıdır.
          </span>
        </div>
      )}

      {/* FAZ 6.2 — ÇALIŞMA PAKETİ (DOSSIER) İZOLASYONU SEÇİCİSİ */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-200">
              <FolderKanban className="w-5 h-5" />
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-slate-700">
                Aktif Çalışma Paketi (Dossier) İzolasyonu
              </p>
              <p className="text-xs text-slate-500">
                Farklı firmaların ve çalışmaların PDF belgelerinin birbirine karışmaması için aktif çalışma paketini seçin
                veya yeni paket oluşturun.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Aktif Çalışma Paketi Seç"
              value={activeDossierKey}
              onChange={(e) => {
                const key = e.target.value;
                const pkg = dossierPackages.find((p) => p.dossier_key === key);
                setActiveDossierKey(key);
                setActiveDossierLabel(pkg?.dossier_label || key);
                setSelectedStudyCode('');
              }}
              className="border border-slate-300 rounded-lg px-3 py-2 text-xs font-semibold text-slate-800 bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              {dossierPackages.map((pkg) => (
                <option key={pkg.dossier_key} value={pkg.dossier_key}>
                  {pkg.dossier_key} — {pkg.dossier_label} ({pkg.document_count ?? 0} Belge)
                </option>
              ))}
            </select>

            {canUpload && (
              <button
                type="button"
                onClick={() => setShowNewDossierForm((v) => !v)}
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-lg px-3 py-2 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Yeni Paket Oluştur</span>
              </button>
            )}
          </div>
        </div>

        {showNewDossierForm && (
          <form
            onSubmit={handleCreateNewDossier}
            className="pt-3 border-t border-slate-200 grid grid-cols-1 md:grid-cols-[1fr_1.5fr_auto] gap-3 items-end"
          >
            <div>
              <label className="block text-[11px] font-semibold text-slate-700 mb-1">
                Yeni Paket Kodu (Örn: DOSSIER-MEDTECH-2026) *
              </label>
              <input
                type="text"
                required
                value={newDossierKey}
                onChange={(e) => setNewDossierKey(e.target.value)}
                placeholder="DOSSIER-FIRMA-2026"
                className="w-full border border-slate-300 rounded-md px-3 py-1.5 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-700 mb-1">
                Paket Açıklaması / Sponsor Adı
              </label>
              <input
                type="text"
                value={newDossierLabel}
                onChange={(e) => setNewDossierLabel(e.target.value)}
                placeholder="Örn: MEDTECH TIBBİ CİHAZLAR — ISO 10993-23 Dosyası"
                className="w-full border border-slate-300 rounded-md px-3 py-1.5 text-xs"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                type="submit"
                className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-md px-4 py-2"
              >
                Paketi Oluştur ve Seç
              </button>
              <button
                type="button"
                onClick={() => setShowNewDossierForm(false)}
                className="border border-slate-300 text-slate-600 text-xs rounded-md px-3 py-2"
              >
                İptal
              </button>
            </div>
          </form>
        )}
      </div>

      {/* ===================================================================== */}
      {/* BİRLEŞTİRİLMİŞ ÇALIŞMA DOSYASI ÖZETİ (MASTER STUDY PROFILE)           */}
      {/* ===================================================================== */}
      {hasAnyDossierData && (
        <section className="bg-white border-2 border-blue-600 rounded-xl shadow-md overflow-hidden">
          <div className="bg-gradient-to-r from-slate-900 via-blue-950 to-slate-900 text-white px-6 py-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-600/90 text-white">
                <Layers className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold tracking-wide">
                  Birleştirilmiş Çalışma Dosyası Özeti (Master Study Profile)
                </h3>
                <p className="text-xs text-blue-200">
                  {dossier.total_documents} belgeden otomatik birleştirildi · Her verinin altında kaynak PDF rozeti
                  gösterilmektedir
                </p>
              </div>
            </div>

            {canUpload && (
              <button
                type="button"
                onClick={goToPlanningFromDossier}
                className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-bold rounded-lg px-5 py-2.5 shadow transition"
              >
                <CalendarPlus className="w-4 h-4" />
                Bu Verilerle Çalışma ve Plan Oluştur
              </button>
            )}
          </div>

          <div className="p-6 space-y-5">
            {/* Çoklu Çalışma Kodu Seçici */}
            <div className="rounded-lg border border-blue-200 bg-blue-50/60 p-4 flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1">
                <p className="text-xs font-bold text-blue-950 uppercase tracking-wider">
                  Planlanacak Çalışma Kodu Seçimi
                </p>
                <p className="text-xs text-slate-600">
                  {dossier.study_codes?.length > 1
                    ? `Sözleşme / dosya içinde ${dossier.study_codes.length} farklı çalışma kodu tespit edildi. Planlamak istediğiniz kodu seçin:`
                    : dossier.study_codes?.length === 1
                    ? 'Dosyada tespit edilen çalışma kodu:'
                    : 'Belgelerde henüz çalışma kodu tespit edilmedi (Planlama ekranında elle girebilirsiniz).'}
                </p>
              </div>

              {dossier.study_codes?.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  {dossier.study_codes.map((code) => {
                    const mapping = dossier.study_code_mappings?.find((m) => m.study_code === code);
                    const active = selectedStudyCode === code;
                    return (
                      <button
                        key={code}
                        type="button"
                        onClick={() => setSelectedStudyCode(code)}
                        className={`px-3 py-1.5 rounded-md font-mono text-xs font-bold border transition flex items-center gap-1.5 ${
                          active
                            ? 'bg-blue-700 text-white border-blue-700 shadow-sm'
                            : 'bg-white text-slate-700 border-slate-300 hover:border-blue-400'
                        }`}
                      >
                        <span>{code}</span>
                        {mapping?.test_type && (
                          <span
                            className={`font-sans font-normal text-[10px] px-1.5 py-0.5 rounded ${
                              active ? 'bg-blue-800 text-blue-100' : 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {mapping.test_type}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* FAZ 6.2: Çalışma Direktörü (SD) Eşleştirme ve Devir Kutusu */}
            {dossier.sd_resolution && (
              <div
                className={`rounded-lg border px-4 py-3.5 text-xs flex flex-wrap items-center justify-between gap-4 ${
                  dossier.sd_resolution.requires_handover
                    ? 'border-amber-400 bg-amber-50 text-amber-950'
                    : 'border-emerald-300 bg-emerald-50 text-emerald-900'
                }`}
              >
                <div className="flex items-start gap-3 flex-1 min-w-[260px]">
                  <UserCheck
                    className={`w-5 h-5 shrink-0 mt-0.5 ${
                      dossier.sd_resolution.requires_handover ? 'text-amber-700' : 'text-emerald-700'
                    }`}
                  />
                  <div className="space-y-1">
                    <p className="font-bold">
                      Çalışma Direktörü (SD) Eşleştirme ve Devir Kontrolü
                    </p>
                    <p>{dossier.sd_resolution.message}</p>
                  </div>
                </div>

                {dossier.sd_resolution.active_sds?.length > 0 && (
                  <div className="flex items-center gap-2">
                    <label htmlFor="dossier-sd-select" className="font-semibold whitespace-nowrap">
                      Atanacak Aktif SD:
                    </label>
                    <select
                      id="dossier-sd-select"
                      value={selectedSdId || dossier.sd_resolution.suggested_sd_id || ''}
                      onChange={(e) => setSelectedSdId(e.target.value)}
                      className="border border-amber-400 bg-white text-slate-900 font-semibold rounded-md px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                    >
                      {dossier.sd_resolution.active_sds.map((sd) => (
                        <option key={sd.id} value={sd.id}>
                          {sd.full_name} ({sd.username})
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            )}

            {/* Çift Kaynak Kontrolü: Hayvan Menşei Sertifikası <-> FM.083 */}
            {dossier.cross_checks?.length > 0 && (
              <div className="space-y-2">
                {dossier.cross_checks.map((cc) => {
                  const isMatch = cc.status === 'MATCH';
                  const isMismatch = cc.status === 'MISMATCH';
                  return (
                    <div
                      key={cc.check}
                      className={`rounded-lg border px-4 py-3 text-xs flex items-start gap-3 ${
                        isMatch
                          ? 'border-emerald-300 bg-emerald-50 text-emerald-900'
                          : isMismatch
                          ? 'border-red-500 bg-red-50 text-red-900'
                          : 'border-amber-300 bg-amber-50 text-amber-900'
                      }`}
                    >
                      {isMatch ? (
                        <ShieldCheck className="w-5 h-5 text-emerald-700 shrink-0 mt-0.5" />
                      ) : (
                        <AlertTriangle
                          className={`w-5 h-5 shrink-0 mt-0.5 ${isMismatch ? 'text-red-700' : 'text-amber-700'}`}
                        />
                      )}
                      <div className="space-y-1 flex-1">
                        <p className="font-bold">{cc.title}</p>
                        <p>{cc.message}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Grup 1: Sponsor ve Çalışma Protokol Bilgileri */}
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5 text-blue-700" />
                1. Sponsor, Sözleşme ve Çalışma Bilgileri
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <MergedFieldCard item={f.sponsor_name} />
                <MergedFieldCard item={f.sponsor_contact} />
                <MergedFieldCard item={f.test_type} />
                <MergedFieldCard item={f.guideline} />
                <MergedFieldCard item={f.study_director} />
                <MergedFieldCard item={f.requested_start_period} />
              </div>
            </div>

            {/* Grup 2: Test Maddesi (TIIS) ve Analiz Sertifikası (CoA) & Ekstraksiyon */}
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                <FlaskConical className="w-3.5 h-3.5 text-blue-700" />
                2. Test Maddesi (TIIS / CoA) ve Ekstraksiyon Parametreleri
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <MergedFieldCard item={f.test_item_name} />
                <MergedFieldCard item={f.lot_batch_no} />
                <MergedFieldCard item={f.manufacture_date} />
                <MergedFieldCard item={f.expiry_date} />
                <MergedFieldCard item={f.storage_conditions} />
                <MergedFieldCard item={f.physical_state} />
                <MergedFieldCard item={f.sterility} />
                <MergedFieldCard
                  item={f.extraction_polar}
                  extraText={f.extraction_polar_solvent?.value}
                />
                <MergedFieldCard
                  item={f.extraction_non_polar}
                  extraText={f.extraction_non_polar_solvent?.value}
                />
                <MergedFieldCard item={f.extraction_polar_solvent} />
                <MergedFieldCard item={f.extraction_non_polar_solvent} />
                <MergedFieldCard item={f.extraction_ratio} />
                <MergedFieldCard item={f.extraction_conditions} />
              </div>
            </div>

            {/* Grup 3: Hayvan Menşei ve FM.083 Aklimatizasyon */}
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-blue-700" />
                3. Test Sistemi (Hayvan Menşei & FM.083 Aklimatizasyon)
              </h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <MergedFieldCard item={f.animal_species_strain} />
                <MergedFieldCard item={f.animal_count} />
                <MergedFieldCard item={f.animal_birth_date} />
                <MergedFieldCard item={f.acclimatization_start_date} />
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Drag & Drop Yükleme Alanı */}
      <div
        {...dropHandlers}
        role="button"
        tabIndex={canUpload ? 0 : -1}
        aria-disabled={!canUpload}
        onClick={() => {
          if (canUpload) inputRef.current?.click();
        }}
        onKeyDown={(e) => {
          if (canUpload && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className={`relative rounded-lg border-2 border-dashed px-6 py-8 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
          !canUpload
            ? 'border-slate-200 bg-slate-100 cursor-not-allowed opacity-70'
            : dragging
            ? 'border-blue-600 bg-blue-50 scale-[1.01] cursor-pointer'
            : 'border-slate-300 bg-white hover:border-blue-400 hover:bg-slate-50 cursor-pointer'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          disabled={!canUpload}
          accept=".pdf,.xlsx,.png,.jpg,.jpeg,.txt,.csv"
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = '';
          }}
        />
        <div
          className={`mx-auto w-12 h-12 rounded-full flex items-center justify-center mb-2.5 ${
            dragging ? 'bg-blue-600 text-white' : 'bg-blue-50 text-blue-700'
          }`}
        >
          <UploadCloud className="w-6 h-6" />
        </div>
        <p className="text-sm font-semibold text-slate-800">
          {!canUpload
            ? 'Belge yükleme yetkiniz yok'
            : dragging
            ? 'Bırakın, Vision OCR analizi başlasın'
            : 'Çalışma dosyası belgelerini (taranmış PDF / IMG_*.pdf / Excel) buraya sürükleyip bırakın'}
        </p>
        <p className="text-xs text-slate-500 mt-1">
          veya <span className="text-blue-700 font-medium underline">bilgisayardan çoklu seçin</span> · PDF, XLSX, PNG,
          JPG · en fazla {MAX_MB} MB
        </p>
        {busyCount > 0 && (
          <p className="mt-2.5 text-xs font-medium text-blue-700 inline-flex items-center gap-1.5">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> {busyCount} belge GPT-4o Vision ile okunuyor…
          </p>
        )}
      </div>

      {rejected.length > 0 && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-800 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
          <ul className="flex-1 space-y-0.5">
            {rejected.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <button onClick={() => setRejected([])} aria-label="Kapat" className="text-red-600 hover:text-red-800">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {historyError && (
        <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">{historyError}</div>
      )}

      {/* Tekil Belge Kartları */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-800">
            Yüklenen Dosya Belgeleri ({items.length})
          </h3>
        </div>

        {items.length === 0 && !loadingHistory && (
          <p className="p-10 bg-white border border-slate-200 rounded-lg text-center text-sm text-slate-400">
            Henüz belge yüklenmedi.
          </p>
        )}

        {items.map((it) => {
          const doc = it.doc;
          const d = doc?.extracted_data;
          const populated = d?.populated_fields || [];
          const cat = doc?.doc_category || d?.doc_category || 'OTHER';
          const catLabel = doc?.doc_category_label || d?.doc_category_label || 'GLP Belgesi';
          const isReparsing = Boolean(doc?.id && reparsingIds[doc.id]);
          const effectiveStatus = isReparsing
            ? 'ANALYZING'
            : it.status === 'FAILED'
            ? 'FAILED'
            : populated.length > 0 || cat === 'OTHER'
            ? 'PARSED'
            : it.status;
          const S = STATUS[effectiveStatus] || STATUS.PARSED;
          const FileIcon = extOf(it.name) === 'pdf' ? FileText : FileSpreadsheet;
          const techOpen = openTech[it.key];

          return (
            <article
              key={it.key}
              className={`bg-white border rounded-lg shadow-sm overflow-hidden ${
                effectiveStatus === 'FAILED' ? 'border-red-300' : 'border-slate-200'
              }`}
            >
              {/* Üst Başlık: Dosya Adı + Belge Türü Rozeti + Çıkarılan Alanlar Özeti */}
              <div className="px-5 py-3.5 flex flex-wrap items-center gap-3 border-b border-slate-100 bg-slate-50/50">
                <div
                  className={`p-2 rounded-md shrink-0 ${
                    extOf(it.name) === 'pdf' ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'
                  }`}
                >
                  <FileIcon className="w-5 h-5" />
                </div>

                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-slate-900 truncate" title={it.name}>
                      {it.name}
                    </p>
                    {d && (
                      <span
                        className={`text-[11px] font-semibold px-2.5 py-0.5 rounded border ${
                          CATEGORY_STYLE[cat] || CATEGORY_STYLE.OTHER
                        }`}
                      >
                        Belge Türü: {catLabel}
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-slate-600">
                    {d?.doc_summary ? (
                      <span>{d.doc_summary}</span>
                    ) : (
                      <span>{fmtSize(it.size)}</span>
                    )}
                    {populated.length > 0 && (
                      <span className="text-emerald-700 font-medium">
                        {' · '}Çıkarılan Alanlar ({populated.length}):{' '}
                        {populated.map((pf) => pf.label).join(', ')}
                      </span>
                    )}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded border ${S.cls}`}
                  >
                    <S.Icon className={`w-3 h-3 ${S.spin ? 'animate-spin' : ''}`} />
                    {S.label}
                  </span>

                  {canUpload && doc?.id && (
                    <button
                      type="button"
                      disabled={isReparsing || reparsingAll}
                      onClick={() => handleReparseSingle(doc)}
                      title="Bu PDF'i PyMuPDF + GPT-4o Vision ile yeniden analiz et"
                      className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-900 border border-blue-200 bg-blue-50/70 hover:bg-blue-100 rounded px-2.5 py-1 disabled:opacity-40 transition"
                    >
                      <ScanEye className="w-3.5 h-3.5" />
                      <span>Yeniden Analiz Et</span>
                    </button>
                  )}

                  {canUpload && doc?.id && (
                    <button
                      type="button"
                      onClick={() => handleDeleteDoc(doc)}
                      title="Belgeyi dosyadan kaldır"
                      className="p-1.5 rounded text-slate-400 hover:text-red-700 hover:bg-red-50 transition"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>

              {/* İşleniyor çubuğu */}
              {(it.status === 'UPLOADING' || it.status === 'ANALYZING' || isReparsing) && (
                <div className="px-5 py-3 bg-blue-50/40">
                  <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-600 animate-pulse transition-all"
                      style={{ width: `${it.status === 'UPLOADING' ? it.progress : 100}%` }}
                    />
                  </div>
                  <p className="mt-1.5 text-[11px] text-blue-800 font-medium">
                    {it.status === 'UPLOADING'
                      ? `Sunucuya yükleniyor %${it.progress}`
                      : 'Sayfalar PNG görüntüsüne çevrildi · GPT-4o Vision kutucukları ve tabloları okuyor…'}
                  </p>
                </div>
              )}

              {/* Hata */}
              {effectiveStatus === 'FAILED' && (
                <div className="px-5 py-3 text-xs text-red-800 bg-red-50 flex items-start gap-2">
                  <XCircle className="w-4 h-4 shrink-0 mt-px" />
                  <span>{it.error || 'Belge ayrıştırılamadı.'}</span>
                </div>
              )}

              {/* Sadece bu belgede bulunan anlamlı alanlar */}
              {d && (
                <div className="px-5 py-4 space-y-3">
                  {populated.length > 0 ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
                      {populated.map((pf) => (
                        <div
                          key={pf.key}
                          className="rounded-md border border-slate-200 bg-white px-3 py-2"
                        >
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                            {pf.label}
                          </p>
                          <p
                            className={`mt-0.5 text-xs font-semibold text-slate-900 break-words ${
                              pf.key.includes('code') || pf.key === 'lot_batch_no' ? 'font-mono' : ''
                            }`}
                          >
                            {pf.display}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500 italic">
                      Bu belge ({catLabel}) yardımcı/referans niteliğindedir.
                      {doc?.extraction_method !== 'PDF_VISION' &&
                        ' Taranmış görüntü içeriğini okumak için sağ üstteki "Yeniden Analiz Et" butonuna tıklayın.'}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                    <button
                      type="button"
                      onClick={() => setOpenTech((s) => ({ ...s, [it.key]: !techOpen }))}
                      className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
                    >
                      {techOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      Teknik & Denetim İzi Detayı ({fmtSize(it.size)} · {doc?.extraction_method || '—'})
                    </button>
                  </div>

                  {techOpen && doc && (
                    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-slate-600 bg-slate-50 border border-slate-200 rounded-md px-3 py-2">
                      <div>
                        <dt className="inline text-slate-400">Belge No: </dt>
                        <dd className="inline font-mono">#{doc.id}</dd>
                      </div>
                      <div>
                        <dt className="inline text-slate-400">AI Modeli: </dt>
                        <dd className="inline font-mono">{doc.ai_model}</dd>
                      </div>
                      <div>
                        <dt className="inline text-slate-400">Okuma Yöntemi: </dt>
                        <dd className="inline font-mono">
                          {doc.extraction_method}
                          {d.page_count ? ` · ${d.page_count} sayfa` : ''}
                        </dd>
                      </div>
                      <div>
                        <dt className="inline text-slate-400">Yüklenme Zamanı: </dt>
                        <dd className="inline">{fmtDateTime(doc.uploaded_at + 'Z')}</dd>
                      </div>
                      <div className="sm:col-span-2 flex items-start gap-1">
                        <Hash className="w-3 h-3 mt-0.5 text-slate-400" />
                        <span>
                          <span className="text-slate-400">SHA-256: </span>
                          <span className="font-mono break-all">{doc.sha256}</span>
                        </span>
                      </div>
                    </dl>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}
