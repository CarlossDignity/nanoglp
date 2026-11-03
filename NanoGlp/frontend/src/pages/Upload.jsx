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
  deleteDocument,
  extractError,
} from '../services/api';
import { useAuth } from '../state/AuthContext';
import { usePreferences } from '../state/PreferencesContext';
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
  const { t, tr, lang } = usePreferences();
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
  const [reparsingIds, setReparsingIds] = useState({});
  const [historyError, setHistoryError] = useState(null);
  const [openTech, setOpenTech] = useState({});
  // FAZ 7.1: Detaylı belge verileri ve kaynak PDF listesi varsayılan olarak kapalı akordeon içinde
  const [showDossierDetails, setShowDossierDetails] = useState(false);
  // FAZ 9.3: Çapraz kontrol uyarıları varsayılan olarak gizli; yalnızca rozete tıklandığında veya yeniden analizde açılır
  const [showCrossChecks, setShowCrossChecks] = useState(false);
  const dragDepth = useRef(0);
  const inputRef = useRef(null);

  const resolveAutoSdId = (sdRes) => {
    if (!sdRes) return '';
    const activeSds = sdRes.active_sds || [];
    const ezgi = activeSds.find(
      (sd) => /ezgi/i.test(sd.full_name || '') || /ezgi/i.test(sd.username || '')
    );
    if (sdRes.requires_handover || /yi[gğ]it/i.test(sdRes.document_sd_name || '')) {
      return String(ezgi?.id || sdRes.suggested_sd_id || activeSds[0]?.id || '');
    }
    return String(sdRes.suggested_sd_id || ezgi?.id || activeSds[0]?.id || '');
  };

  const dismissCrossChecks = () => {
    try {
      const raw = JSON.parse(localStorage.getItem('nanolab_dismissed_crosschecks') || '{}');
      raw[activeDossierKey] = true;
      localStorage.setItem('nanolab_dismissed_crosschecks', JSON.stringify(raw));
    } catch {
      /* ignore */
    }
    setShowCrossChecks(false);
  };

  const patch = (key, p) => setItems((prev) => prev.map((it) => (it.key === key ? { ...it, ...p } : it)));

  const loadAll = useCallback(async (targetKey) => {
    const resolvedKey = typeof targetKey === 'string' && targetKey ? targetKey : activeDossierKey;
    setLoadingHistory(true);
    setHistoryError(null);
    setShowCrossChecks(false);
    try {
      const [pkgsRes, docsRes, dossierRes] = await Promise.all([
        getDossiers(),
        getDocuments({ limit: 100, dossier_key: resolvedKey }),
        getDossier(resolvedKey),
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
      const autoSd = resolveAutoSdId(dos?.sd_resolution);
      if (autoSd) {
        setSelectedSdId(autoSd);
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
      const autoSd = resolveAutoSdId(res.data?.sd_resolution);
      if (autoSd && !selectedSdId) {
        setSelectedSdId(autoSd);
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
      try {
        const raw = JSON.parse(localStorage.getItem('nanolab_dismissed_crosschecks') || '{}');
        delete raw[activeDossierKey];
        localStorage.setItem('nanolab_dismissed_crosschecks', JSON.stringify(raw));
      } catch {
        /* ignore */
      }
      setShowCrossChecks(true);
      await refreshDossierOnly();
    } catch (err) {
      setHistoryError(extractError(err, `"${doc.original_filename}" yeniden analiz edilemedi.`));
    } finally {
      setReparsingIds((s) => ({ ...s, [doc.id]: false }));
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
    const mappedEntry = dossier?.study_code_mappings?.find((m) => m.study_code === chosenCode);
    const mappedTest = mappedEntry?.test_type;
    const mappedGuideline = mappedEntry?.guideline;
    const mappedTemplate = mappedEntry?.suggested_template_code;
    const sdRes = dossier?.sd_resolution;
    const autoIdStr = selectedSdId || resolveAutoSdId(sdRes);
    const resolvedSdId = autoIdStr ? parseInt(autoIdStr, 10) : sdRes?.suggested_sd_id || null;
    const rawDocSd = val('study_director') || '';
    const effectiveSdName = /yi[gğ]it/i.test(String(rawDocSd)) ? 'Ezgi Nur AKIN' : rawDocSd;

    navigate('/planning', {
      state: {
        prefill: {
          from_dossier: true,
          dossier_key: activeDossierKey,
          study_code: chosenCode,
          start_date: val('acclimatization_start_date') || '',
          template_code: mappedTemplate || dossier?.suggested_template_code || 'ISO_10993_23_IC',
          study_director_id: resolvedSdId,
          former_study_director_name: null,
          sd_resolution: sdRes ? { ...sdRes, requires_handover: false } : null,
          test_type: mappedTest || val('test_type'),
          guideline: mappedGuideline || val('guideline'),
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
          study_director: effectiveSdName,
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

  const docCount = dossier?.total_documents ?? items.length;
  const studyCodeCount = dossier?.study_codes?.length ?? 0;
  const crossCheckIssues = (dossier?.cross_checks || []).filter((c) => c.status !== 'MATCH');
  const glpWarningCount = crossCheckIssues.length;

  // Sıradaki boş GLP çalışma kodunu hesapla (gerçek seri GLP2026-001..082 -> GLP2026-083)
  const nextSuggestedGlpCode = (() => {
    if (dossier?.next_glp_code) return dossier.next_glp_code;
    const codes = [
      ...(dossier?.study_codes || []),
      ...dossierPackages.flatMap((p) => p.study_codes || []),
    ];
    let maxSeq = 82;
    codes.forEach((raw) => {
      const m = String(raw).match(/^GLP\d{4}-(\d{2,3})$/i);
      if (m) {
        const n = parseInt(m[1], 10);
        if (!Number.isNaN(n) && n <= 150 && n > maxSeq) maxSeq = n;
      }
    });
    return `GLP2026-${String(maxSeq + 1).padStart(3, '0')}`;
  })();

  return (
    <div className="space-y-6" {...dropHandlers}>
      {/* Gizli dosya seçici: hem üst bardaki buton hem de sürükle-bırak alanı tarafından tetiklenir */}
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

      {/* FAZ 7.1 — Üst Başlık ve Doğrudan "+ Yeni Müşteri Belgeleri Yükle (PDF Seç / Sürükle-Bırak)" Alanı */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            Belge Yükleme ve Çoklu Belge Dosya Birleştirme (Vision OCR)
          </h2>
          <p className="text-sm text-slate-500">
            Sözleşme, TIIS, CoA, Hayvan Menşei Sertifikası ve FM.083 belgelerini yükleyin; GPT-4o Vision tüm sayfaları,
            tabloları ve işaretli kutucukları (<span className="font-mono">[X]</span>) okuyarak aktif müşteri klasöründe
            birleştirir.
          </p>
        </div>

        {canUpload && (
          <button
            type="button"
            disabled={busyCount > 0}
            onClick={() => inputRef.current?.click()}
            className={`inline-flex items-center gap-2 text-xs font-medium rounded px-3.5 py-2 border transition ${
              dragging
                ? 'border-slate-900 bg-slate-100 text-slate-900'
                : 'border-slate-900 bg-slate-900 hover:bg-slate-800 text-white'
            }`}
          >
            {busyCount > 0 ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>{busyCount} Belge Vision OCR ile Analiz Ediliyor…</span>
              </>
            ) : (
              <>
                <UploadCloud className="w-4 h-4" />
                <span>+ Yeni Müşteri Belgeleri Yükle (PDF Seç / Sürükle-Bırak)</span>
              </>
            )}
          </button>
        )}
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

      {/* FAZ 7.1 — MÜŞTERİ / BAŞVURU KLASÖRÜ SEÇİMİ */}
      <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-xs space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <FolderKanban className="w-4 h-4 text-slate-500" />
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-slate-800">
                MÜŞTERİ / BAŞVURU KLASÖRÜ SEÇİMİ
              </p>
              <p className="text-xs text-slate-500">
                Her firmanın başvuru belgeleri kendi klasöründe ayrı tutulur; seçtiğiniz klasördeki PDF'ler otomatik birleştirilir.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Müşteri / Başvuru Klasörü Seç"
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
                className="nl-blue-btn inline-flex items-center gap-1.5 text-xs font-semibold text-[#1d4ed8] bg-[#eff6ff] hover:bg-blue-100 border border-[#bfdbfe] dark:bg-[#1e3a8a] dark:text-[#dbeafe] dark:border-[#3b82f6] rounded-lg px-3 py-2 transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Yeni Müşteri Klasörü Aç</span>
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
                Yeni Müşteri Klasörü Kodu (Örn: DOSSIER-MEDTECH-2026) *
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
                Firma / Başvuru Klasörü Açıklaması
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
                className="bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-md px-4 py-2"
              >
                Klasörü Aç ve Seç
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
        <section className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <div className="border-b border-slate-200 bg-slate-50/70 text-slate-900 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Birleştirilmiş Çalışma Dosyası Özeti (Master Study Profile)
              </h3>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-white border border-slate-200 text-slate-700 font-medium">
                  {docCount} PDF Okundu
                </span>
                <span className="text-slate-300">•</span>
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-white border border-slate-200 text-slate-700 font-medium">
                  {studyCodeCount} Çalışma Kodu Tespit Edildi
                </span>
                <span className="text-slate-300">•</span>
                {glpWarningCount > 0 ? (
                  <button
                    type="button"
                    onClick={() => setShowCrossChecks((v) => !v)}
                    className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-semibold border bg-slate-100 hover:bg-slate-200 border-slate-300 text-slate-700 transition cursor-pointer"
                    title={t('Çapraz kontrol detaylarını göster / gizle', 'Show / hide cross-check details')}
                  >
                    <span>
                      {showCrossChecks
                        ? `${t('Çapraz Kontrol Uyarılarını Gizle', 'Hide Cross-Check Warnings')} (${glpWarningCount})`
                        : `${t('Çapraz Kontrol Uyarılarını Göster', 'Show Cross-Check Warnings')} (${glpWarningCount})`}
                    </span>
                  </button>
                ) : (
                  <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full font-semibold border bg-emerald-50 border-emerald-300 text-emerald-800">
                    0 GLP Denetim Uyarısı
                  </span>
                )}
              </div>
            </div>

            {canUpload && (
              <button
                type="button"
                onClick={goToPlanningFromDossier}
                className="inline-flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-medium rounded px-3.5 py-2 transition"
              >
                <CalendarPlus className="w-4 h-4" />
                Bu Verilerle Çalışma ve Plan Oluştur
              </button>
            )}
          </div>

          <div className="p-6 space-y-5">
            {/* 1) HER ZAMAN AÇIK: Çoklu Çalışma Kodu Seçici + Manuel Düzenleme / Otomatik Sıradaki Kodu Ata */}
            <div className="rounded-lg border border-blue-200 bg-blue-50/60 p-4 space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1">
                  <p className="text-xs font-bold text-blue-950 uppercase tracking-wider">
                    PLANLANACAK ÇALIŞMA KODU SEÇİMİ
                  </p>
                  <p className="text-xs text-slate-600">
                    {dossier.study_codes?.length > 1
                      ? `Sözleşme / dosya içinde ${dossier.study_codes.length} farklı çalışma kodu tespit edildi. Planlamak istediğiniz kodu seçin veya sağdan özelleştirin:`
                      : dossier.study_codes?.length === 1
                      ? 'Dosyada tespit edilen çalışma kodu:'
                      : 'Belgelerde henüz resmi çalışma kodu tespit edilmedi; aşağıdan elle girebilir veya sıradaki GLP kodunu atayabilirsiniz.'}
                  </p>
                </div>

                {/* Çalışma Kodunu Düzenle / Otomatik Sıradaki Kodu Ata */}
                {canUpload && (
                  <div className="nl-code-box flex flex-wrap items-center gap-2 bg-[#f1f5f9] text-[#334155] dark:bg-[#1e293b] dark:text-[#e2e8f0] border border-slate-300 dark:border-slate-700 rounded-lg px-2.5 py-1.5 shadow-xs">
                    <label
                      htmlFor="custom-study-code-input"
                      className="text-[11px] font-semibold text-[#334155] dark:text-[#e2e8f0] whitespace-nowrap"
                    >
                      Aktif Kod:
                    </label>
                    <input
                      id="custom-study-code-input"
                      type="text"
                      value={selectedStudyCode}
                      onChange={(e) => setSelectedStudyCode(e.target.value.toUpperCase())}
                      placeholder="GLP2026-XXX"
                      className="w-32 border border-slate-300 dark:border-slate-600 rounded px-2 py-1 text-xs font-mono font-bold text-[#0f172a] dark:text-[#f8fafc] bg-white dark:bg-[#0f172a] focus:outline-none focus:ring-2 focus:ring-blue-600"
                    />
                    <button
                      type="button"
                      onClick={() => setSelectedStudyCode(nextSuggestedGlpCode)}
                      title={`Sıradaki boş GLP çalışma kodunu (${nextSuggestedGlpCode}) otomatik ata`}
                      className="nl-blue-btn inline-flex items-center gap-1 text-[11px] font-semibold text-[#1d4ed8] bg-[#eff6ff] hover:bg-blue-100 border border-[#bfdbfe] dark:bg-[#1e3a8a] dark:text-[#dbeafe] dark:border-[#3b82f6] rounded px-2.5 py-1 transition whitespace-nowrap"
                    >
                      <Sparkles className="w-3 h-3" />
                      <span>Otomatik Sıradaki Kodu Ata ({nextSuggestedGlpCode})</span>
                    </button>
                  </div>
                )}
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
                            ? 'bg-slate-900 text-white border-blue-700 shadow-xs'
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

            {/* 2) VARSAYILAN GİZLİ / KAPATILABİLİR: GLP Çapraz Kontroller (Hayvan Menşei <-> FM.083) */}
            {showCrossChecks && dossier.cross_checks?.length > 0 && (
              <div className="space-y-2">
                {dossier.cross_checks.map((cc) => {
                  const isMatch = cc.status === 'MATCH';
                  const isMismatch = cc.status === 'MISMATCH';
                  return (
                    <div
                      key={cc.check}
                      className={`rounded-lg border px-4 py-3 text-xs flex flex-wrap items-start justify-between gap-3 ${
                        isMatch
                          ? 'border-emerald-300 bg-emerald-50 text-emerald-900'
                          : isMismatch
                          ? 'border-red-500 bg-red-50 text-red-900'
                          : 'border-amber-300 bg-amber-50 text-amber-900'
                      }`}
                    >
                      <div className="flex items-start gap-3 flex-1 min-w-[260px]">
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
                      <button
                        type="button"
                        onClick={dismissCrossChecks}
                        className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white hover:bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-700 shrink-0"
                      >
                        {t('✓ Kontrol Edildi / Kapat', '✓ Reviewed / Dismiss')}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {/* FAZ 7.1 — AKORDEON BUTONU (Varsayılan Kapalı) */}
            <div className="pt-1 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setShowDossierDetails((v) => !v)}
                className="w-full flex items-center justify-between px-4 py-3 rounded-lg bg-slate-100 hover:bg-slate-200/80 border border-slate-300 text-xs font-bold text-slate-800 transition"
              >
                <span className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-slate-500" />
                  <span>
                    Birleştirilen Belge Verilerini ve Kaynak PDF Detaylarını {showDossierDetails ? 'Gizle' : 'Göster'} ({docCount} Belge){' '}
                    {showDossierDetails ? '▴' : '▾'}
                  </span>
                </span>
                <span className="text-[11px] font-medium text-blue-700">
                  {showDossierDetails ? 'Daraltmak için tıklayın' : 'Sponsor, TIIS/CoA, Hayvan & 15 PDF listesini aç'}
                </span>
              </button>
            </div>

            {showDossierDetails && (
              <div className="space-y-6 pt-3">
                {/* Grup 1: Sponsor ve Çalışma Protokol Bilgileri */}
                <div className="space-y-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1.5">
                    <Building2 className="w-3.5 h-3.5 text-slate-500" />
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
                    <FlaskConical className="w-3.5 h-3.5 text-slate-500" />
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
                    <ShieldCheck className="w-3.5 h-3.5 text-slate-500" />
                    3. Test Sistemi (Hayvan Menşei & FM.083 Aklimatizasyon)
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    <MergedFieldCard item={f.animal_species_strain} />
                    <MergedFieldCard item={f.animal_count} />
                    <MergedFieldCard item={f.animal_birth_date} />
                    <MergedFieldCard item={f.acclimatization_start_date} />
                  </div>
                </div>

                {/* Tekil Belge Kartları */}
                <div className="space-y-3 pt-3 border-t border-slate-200">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-600">
                      Yüklenen Dosya Belgeleri ({items.length})
                    </h4>
                  </div>

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
                        className={`bg-white border rounded-lg shadow-xs overflow-hidden ${
                          effectiveStatus === 'FAILED' ? 'border-red-300' : 'border-slate-200'
                        }`}
                      >
                        <div className="px-5 py-3.5 flex flex-wrap items-center gap-3 border-b border-slate-100 bg-slate-50/50">
                          <div
                            className={`shrink-0 ${
                              'text-slate-500'
                            }`}
                          >
                            <FileIcon className="w-4 h-4" />
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
                              {d?.doc_summary ? <span>{d.doc_summary}</span> : <span>{fmtSize(it.size)}</span>}
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
                                disabled={isReparsing}
                                onClick={() => handleReparseSingle(doc)}
                                title="Bu PDF'i PyMuPDF + GPT-4o Vision ile yeniden analiz et"
                                className="nl-blue-btn inline-flex items-center gap-1 text-xs font-semibold text-[#1d4ed8] hover:text-blue-900 border border-[#bfdbfe] bg-[#eff6ff] hover:bg-blue-100 dark:bg-[#1e3a8a] dark:text-[#dbeafe] dark:border-[#3b82f6] rounded px-2.5 py-1 disabled:opacity-40 transition"
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

                        {effectiveStatus === 'FAILED' && (
                          <div className="px-5 py-3 text-xs text-red-800 bg-red-50 flex items-start gap-2">
                            <XCircle className="w-4 h-4 shrink-0 mt-px" />
                            <span>{it.error || 'Belge ayrıştırılamadı.'}</span>
                          </div>
                        )}

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
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Yeni açılmış ve henüz belgesi olmayan klasörler için Yükleme Kartı */}
      {!hasAnyDossierData && !loadingHistory && (
        <div
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
          className={`relative rounded-lg border border-dashed px-6 py-10 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
            !canUpload
              ? 'border-slate-200 bg-slate-100 cursor-not-allowed opacity-70'
              : dragging
              ? 'border-slate-900 bg-slate-50 cursor-pointer'
              : 'border-slate-300 bg-white hover:border-slate-500 hover:bg-slate-50 cursor-pointer'
          }`}
        >
          <div className="mx-auto mb-2 flex justify-center text-slate-400">
            <UploadCloud className="w-5 h-5" />
          </div>
          <p className="text-sm font-semibold text-slate-800">
            {!canUpload
              ? 'Belge yükleme yetkiniz yok'
              : dragging
              ? 'Bırakın, Vision OCR analizi başlasın'
              : 'Bu müşteri klasörüne henüz belge yüklenmedi — PDF belgelerini buraya sürükleyin veya tıklayıp seçin'}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            PDF, XLSX, PNG, JPG · en fazla {MAX_MB} MB · seçilen belgeler otomatik olarak{' '}
            <span className="font-mono font-semibold text-slate-700">{activeDossierKey}</span> klasörüne yüklenir ve analiz edilir.
          </p>
        </div>
      )}
    </div>
  );
}
