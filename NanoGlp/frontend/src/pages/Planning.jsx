import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  CalendarPlus,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  Info,
  Lock,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Files,
  Eye,
  Sparkles,
  X,
  AlertTriangle,
  FileDown,
  UserCheck,
  Calendar as CalendarIcon,
  Clock,
  Layers,
  CheckCheck,
  Edit3,
  Search,
  RefreshCw,
} from 'lucide-react';
import ConflictAlert from '../components/ConflictAlert';
import GanttChart from '../components/GanttChart';
import {
  scheduleStudy,
  getTemplates,
  getPersonnel,
  getCalendar,
  getStudySchedule,
  approveStudyPlan,
  getBiologicalRevisionPreview,
  approveBiologicalRevision,
  applyConflictResolution,
  recomputeConflicts,
  downloadStudyPlanDocx,
  extractError,
} from '../services/api';
import { useAuth } from '../state/AuthContext';
import { usePreferences } from '../state/PreferencesContext';
import { fmtDateTime, fmtMinutes, fmtTime, todayISO, ROLE_SHORT } from '../utils/format';

const Chip = ({ children, tone = 'slate' }) => (
  <span
    className={`font-mono text-[11px] px-1.5 py-0.5 rounded ${
      tone === 'amber'
        ? 'bg-amber-50 text-amber-800 border border-amber-200'
        : tone === 'emerald'
          ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
          : 'bg-slate-100 text-slate-700'
    }`}
  >
    {children}
  </span>
);

const fmtIsoDate = (iso) => {
  if (!iso) return '—';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${d}.${m}.${y}`;
};

const CAP_DOT = { OK: 'bg-emerald-500', FLEX: 'bg-amber-400', EXCEEDED: 'bg-red-500' };

/** FAZ 8.1 — Kafes (Fiziksel + Dr. Anoop esneklik) ve 24-72s cihaz kapasite bilgi etiketleri. */
function CapacityTags({ info }) {
  if (!info || (!info.cage && !(info.equipment || []).length)) return null;
  const cage = info.cage;
  return (
    <div className="bg-white border border-slate-200 rounded-lg px-4 py-3 text-xs space-y-1.5">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Kapasite Kontrolü</p>
      {cage && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-slate-800">
          <span className={`w-1.5 h-1.5 rounded-full ${CAP_DOT[cage.level] || CAP_DOT.OK}`} />
          <span className="font-medium">{cage.room_label}</span>
          <span className="font-mono tabular-nums">
            {cage.required} kafes · en yoğun gün {cage.peak_total} / Fiziksel {cage.physical} · Planlama {cage.planning_capacity}
          </span>
          <span className="text-slate-500">(Dr. Anoop esneklik %{cage.flexibility_pct})</span>
          {cage.level === 'FLEX' && (
            <span className="border border-amber-300 bg-amber-50 text-amber-900 rounded px-1.5 py-0.5">
              Bilgi: esneklik payı kullanılıyor — çalışma engellenmedi
            </span>
          )}
          {cage.level === 'EXCEEDED' && (
            <span className="border border-red-300 bg-red-50 text-red-900 rounded px-1.5 py-0.5">
              Planlama kapasitesi aşıldı{cage.first_free_date ? ` — ilk uygun başlangıç ${fmtIsoDate(cage.first_free_date)}` : ''}
            </span>
          )}
        </p>
      )}
      {(info.equipment || []).map((eq) => (
        <p key={`${eq.equipment_code}-${eq.window_start}`} className="flex flex-wrap items-center gap-x-2 text-slate-800">
          <span className={`w-1.5 h-1.5 rounded-full ${CAP_DOT[eq.level] || CAP_DOT.OK}`} />
          <span className="font-medium">{eq.equipment_name}</span>
          <span className="font-mono text-[10px] text-slate-400">{eq.equipment_code}</span>
          <span className="font-mono tabular-nums">
            {eq.hours} saat · {eq.used} / {eq.capacity} eşzamanlı
          </span>
          {eq.level === 'EXCEEDED' && (
            <span className="border border-red-300 bg-red-50 text-red-900 rounded px-1.5 py-0.5">Cihaz kapasitesi aşıldı</span>
          )}
        </p>
      ))}
    </div>
  );
}

const DAY_NAMES_TR = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];

const STUDY_CODE_TEMPLATE_MAP = {
  'GLP2026-024': 'ISO_10993_5_CYTO',
  'GLP2026-026': 'ISO_10993_23_IC',
  'GLP2026-031': 'ISO_10993_10_SENS',
  'GLP2026-034': 'ISO_10993_11_ACUTE',
};

function toMondayISO(isoDate) {
  if (!isoDate) return todayISO();
  const [y, m, d] = isoDate.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  const day = dt.getDay(); // 0=Paz, 1=Pzt...
  const diff = day === 0 ? -6 : 1 - day;
  dt.setDate(dt.getDate() + diff);
  const yy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, '0');
  const dd = String(dt.getDate()).padStart(2, '0');
  return `${yy}-${mm}-${dd}`;
}

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

export default function Planning({ onScheduled }) {
  const { isReadOnly, isExecutive, role } = useAuth();
  const { t, tr, lang, formatStatusBadge } = usePreferences();
  const location = useLocation();
  const navigate = useNavigate();

  // FAZ 6: Belge Yükleme ekranından AI ile çıkarılan veriler (yalnızca öneri; kullanıcı doğrular)
  const [prefill, setPrefill] = useState(() => location.state?.prefill || null);

  const [templates, setTemplates] = useState([]);
  const [templateCode, setTemplateCode] = useState('');
  const [showTemplate, setShowTemplate] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isStudiesListOpen, setIsStudiesListOpen] = useState(true);
  const [studySearchQuery, setStudySearchQuery] = useState('');
  const [studyStatusFilter, setStudyStatusFilter] = useState('ALL');
  const [studyCode, setStudyCode] = useState(() => prefill?.study_code || '');
  const [startDate, setStartDate] = useState(() => prefill?.start_date || todayISO());
  const [activeSds, setActiveSds] = useState(() => prefill?.sd_resolution?.active_sds || []);
  const [selectedSdId, setSelectedSdId] = useState(
    () => String(prefill?.study_director_id || prefill?.sd_resolution?.suggested_sd_id || '')
  );

  // FAZ 6.3: Kalıcı Master Operasyon Takvimi state'i
  const [calendarData, setCalendarData] = useState({
    studies: [],
    all_steps: [],
    active_dates: [],
    active_weeks: [],
    default_focus_date: todayISO(),
    default_focus_week: toMondayISO(todayISO()),
  });
  const [loadingCalendar, setLoadingCalendar] = useState(true);
  const [viewMode, setViewMode] = useState('study'); // 'study' | 'weekly' | 'daily'
  const [weekStart, setWeekStart] = useState(() => toMondayISO(todayISO()));
  const [dailyDate, setDailyDate] = useState(() => todayISO());
  const [calendarStudyFilter, setCalendarStudyFilter] = useState('ALL');
  const [initialFocusApplied, setInitialFocusApplied] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [downloadingDocx, setDownloadingDocx] = useState(false);
  const [recomputingConflicts, setRecomputingConflicts] = useState(false);
  const [bioRevisionPreview, setBioRevisionPreview] = useState(null);
  const [loadingBioPreview, setLoadingBioPreview] = useState(false);
  const [approvingBioRevision, setApprovingBioRevision] = useState(false);
  const [bioRevisionReason, setBioRevisionReason] = useState('');
  const [bioRevisionError, setBioRevisionError] = useState(null);
  const [resolutionNotice, setResolutionNotice] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const loadCalendar = useCallback(
    async (preferredStudyId = null) => {
      setLoadingCalendar(true);
      try {
        const res = await getCalendar();
        const data = res.data || {};
        setCalendarData({
          studies: data.studies || [],
          all_steps: data.all_steps || [],
          active_dates: data.active_dates || [],
          active_weeks: data.active_weeks || [],
          default_focus_date: data.default_focus_date || todayISO(),
          default_focus_week: data.default_focus_week || toMondayISO(todayISO()),
        });

        if (!initialFocusApplied) {
          if (data.default_focus_week) setWeekStart(data.default_focus_week);
          if (data.default_focus_date) setDailyDate(data.default_focus_date);
          setInitialFocusApplied(true);
        }

        const studiesList = data.studies || [];
        if (studiesList.length > 0) {
          const searchParams = new URLSearchParams(location.search || window.location.search || '');
          const queryStudyId = searchParams.get('study_id');
          const queryStudyCode = (searchParams.get('study_code') || '').trim().toUpperCase();
          const targetId =
            preferredStudyId ||
            (queryStudyId ? Number(queryStudyId) : null) ||
            (queryStudyCode
              ? studiesList.find((s) => (s.study_code || '').toUpperCase() === queryStudyCode)?.study_id
              : null) ||
            location.state?.selectedStudyId ||
            result?.study_id ||
            (location.state?.focusDraft
              ? studiesList.find((s) => s.study_status === 'DRAFT')?.study_id
              : null);

          const matched =
            (targetId && studiesList.find((s) => s.study_id === Number(targetId))) ||
            studiesList.find((s) => s.study_status === 'DRAFT' && s.steps?.length > 0) ||
            studiesList.find((s) => s.steps?.length > 0) ||
            studiesList[0];

          if (matched) {
            setResult(matched);
            getStudySchedule(matched.study_id)
              .then((detailRes) => {
                if (detailRes?.data) setResult(detailRes.data);
              })
              .catch(() => {});
            if (!prefill) {
              if (matched.study_code) setStudyCode(matched.study_code);
              if (matched.acclimatization_start_date) setStartDate(matched.acclimatization_start_date);
              const tplCode =
                matched.template?.code ||
                STUDY_CODE_TEMPLATE_MAP[(matched.study_code || '').toUpperCase()];
              if (tplCode) setTemplateCode(tplCode);
              if (matched.study_director_id) setSelectedSdId(String(matched.study_director_id));
            }
          }
        }
      } catch (err) {
        setError(extractError(err, 'Kalıcı operasyon takvimi yüklenemedi.'));
      } finally {
        setLoadingCalendar(false);
      }
    },
    [initialFocusApplied, location.state, result?.study_id]
  );

  useEffect(() => {
    getTemplates()
      .then((res) => {
        setTemplates(res.data.templates);
        const suggested = prefill?.template_code;
        const exists = suggested && res.data.templates.some((t) => t.code === suggested);
        setTemplateCode(exists ? suggested : res.data.default);
      })
      .catch((err) => setError(extractError(err, 'Şablonlar alınamadı.')));

    getPersonnel()
      .then((res) => {
        const sds = (res.data || []).filter((p) => p.role === 'STUDY_DIRECTOR' && p.is_active !== false);
        if (sds.length > 0) {
          setActiveSds(sds);
          setSelectedSdId((curr) => curr || String(sds[0].id));
        }
      })
      .catch(() => {});

    loadCalendar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clearPrefill = () => {
    setPrefill(null);
    setStudyCode('');
    setStartDate(todayISO());
    navigate(location.pathname, { replace: true, state: null });
  };

  const prefillEdited =
    prefill && (studyCode !== (prefill.study_code || '') || startDate !== (prefill.start_date || todayISO()));

  const template = templates.find((t) => t.code === templateCode);

  const matchedFormStudy = useMemo(() => {
    const codeUpper = (studyCode || '').trim().toUpperCase();
    if (!codeUpper) return null;
    if (
      result &&
      (result.study_code || '').toUpperCase() === codeUpper &&
      result.acclimatization_start_date === startDate
    ) {
      return result;
    }
    return (
      calendarData.studies.find(
        (s) =>
          (s.study_code || '').toUpperCase() === codeUpper &&
          s.acclimatization_start_date === startDate
      ) || null
    );
  }, [studyCode, startDate, result, calendarData.studies]);

  // Gün 0 seçimine göre şablon önizlemesi: mevcut çalışmanın çözülmüş takvimi varsa onu baz alır
  const preview = useMemo(() => {
    if (!template || !startDate) return [];
    if (matchedFormStudy?.steps?.length === template.steps.length) {
      return template.steps.map((s, idx) => {
        const stStep = matchedFormStudy.steps[idx];
        const dt = stStep?.planned_start ? new Date(stStep.planned_start) : new Date(startDate);
        return {
          ...s,
          day: stStep?.study_day ?? s.day,
          date: dt,
          weekend: dt.getDay() === 0 || dt.getDay() === 6,
        };
      });
    }
    const [y, m, d] = startDate.split('-').map(Number);
    return template.steps.map((s) => {
      const dt = new Date(y, m - 1, d + s.day);
      return { ...s, date: dt, weekend: dt.getDay() === 0 || dt.getDay() === 6 };
    });
  }, [template, startDate, matchedFormStudy]);

  const weekendLocked = useMemo(() => {
    if (matchedFormStudy) {
      const activeWeekendConflicts = (matchedFormStudy.conflicts || []).filter(
        (c) => c.conflict_type === 'WEEKEND_OVERLAP'
      );
      if (activeWeekendConflicts.length === 0) return [];
    }
    return preview.filter((s) => s.weekend && s.is_biological_fixed_time);
  }, [preview, matchedFormStudy]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isReadOnly) return;
    setSubmitting(true);
    setError(null);
    try {
      const dossierExtras = prefill
        ? {
            ...(prefill.source_document_id ? { source_document_id: prefill.source_document_id } : {}),
            ...(prefill.source_document_ids ? { source_document_ids: prefill.source_document_ids } : {}),
            ...(prefill.test_type ? { test_type: prefill.test_type } : {}),
            ...(prefill.guideline ? { guideline: prefill.guideline } : {}),
            ...(prefill.sponsor_name ? { sponsor_name: prefill.sponsor_name } : {}),
            ...(prefill.sponsor_contact ? { sponsor_contact: prefill.sponsor_contact } : {}),
            ...(prefill.test_item_name ? { test_item_name: prefill.test_item_name } : {}),
            ...(prefill.test_item_batch || prefill.lot_batch_no
              ? { test_item_batch: prefill.test_item_batch || prefill.lot_batch_no }
              : {}),
            ...(prefill.test_item_storage_condition || prefill.storage_conditions
              ? { test_item_storage_condition: prefill.test_item_storage_condition || prefill.storage_conditions }
              : {}),
            ...(prefill.manufacture_date ? { manufacture_date: prefill.manufacture_date } : {}),
            ...(prefill.expiry_date ? { expiry_date: prefill.expiry_date } : {}),
            ...(prefill.physical_state ? { physical_state: prefill.physical_state } : {}),
            ...(prefill.sterility ? { sterility: prefill.sterility } : {}),
            ...(prefill.extraction_polar !== undefined && prefill.extraction_polar !== null
              ? { extraction_polar: prefill.extraction_polar }
              : {}),
            ...(prefill.extraction_polar_solvent ? { extraction_polar_solvent: prefill.extraction_polar_solvent } : {}),
            ...(prefill.extraction_non_polar !== undefined && prefill.extraction_non_polar !== null
              ? { extraction_non_polar: prefill.extraction_non_polar }
              : {}),
            ...(prefill.extraction_non_polar_solvent
              ? { extraction_non_polar_solvent: prefill.extraction_non_polar_solvent }
              : {}),
            ...(prefill.extraction_ratio ? { extraction_ratio: prefill.extraction_ratio } : {}),
            ...(prefill.extraction_conditions ? { extraction_conditions: prefill.extraction_conditions } : {}),
            ...(prefill.animal_species_strain ? { animal_species_strain: prefill.animal_species_strain } : {}),
            ...(prefill.animal_count ? { animal_count: prefill.animal_count } : {}),
            ...(prefill.animal_birth_date ? { animal_birth_date: prefill.animal_birth_date } : {}),
            ...(prefill.requested_start_period ? { requested_start_period: prefill.requested_start_period } : {}),
            ...(prefill.dossier_metadata ? { dossier_metadata: prefill.dossier_metadata } : {}),
          }
        : {};
      const res = await scheduleStudy({
        study_code: studyCode.trim(),
        acclimatization_start_date: startDate,
        template_code: templateCode,
        ...(selectedSdId ? { study_director_id: parseInt(selectedSdId, 10) } : {}),
        ...(prefill?.former_study_director_name
          ? { former_study_director_name: prefill.former_study_director_name }
          : {}),
        ...dossierExtras,
      });
      setResolutionNotice(null);
      setResult(res.data);
      if (res.data?.acclimatization_start_date) {
        setDailyDate(res.data.acclimatization_start_date);
        setWeekStart(toMondayISO(res.data.acclimatization_start_date));
      }
      await loadCalendar(res.data?.study_id);
      onScheduled?.();
    } catch (err) {
      setError(extractError(err, 'Planlama isteği başarısız oldu.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleApplyResolution = async (conflictId, resolution) => {
    setError(null);
    setResolutionNotice(null);
    try {
      const res = await applyConflictResolution(conflictId, {
        action: resolution.action,
        ...(resolution.target_user_id ? { target_user_id: resolution.target_user_id } : {}),
      });
      setResult(res.data);
      if (res.data?.resolution_applied?.message) {
        setResolutionNotice(res.data.resolution_applied.message);
      }
      await loadCalendar(res.data?.study_id);
      onScheduled?.();
    } catch (err) {
      setError(extractError(err, 'Çözüm uygulanırken hata oluştu.'));
    }
  };

  const handleApproveStudy = async () => {
    if (!result?.study_id || isReadOnly) return;
    setApproving(true);
    setError(null);
    setResolutionNotice(null);
    try {
      const res = await approveStudyPlan(result.study_id);
      setResult(res.data);
      setResolutionNotice(
        res.data?.approval_message ||
          `'${result.study_code}' çalışma planı onaylandı ve Aktif Çalışmalar (APPROVED) listesine alındı.`
      );
      await loadCalendar(res.data?.study_id);
      onScheduled?.();
    } catch (err) {
      setError(extractError(err, 'Çalışma planı onaylanırken hata oluştu.'));
    } finally {
      setApproving(false);
    }
  };

  const handleDownloadStudyPlan = async () => {
    if (!result?.study_id) return;
    setDownloadingDocx(true);
    setError(null);
    try {
      await downloadStudyPlanDocx(result.study_id, result.study_code);
    } catch (err) {
      setError(extractError(err, 'Study Plan (.docx) indirilemedi.'));
    } finally {
      setDownloadingDocx(false);
    }
  };

  const handleRecomputeAllConflicts = async () => {
    if (isReadOnly) return;
    setRecomputingConflicts(true);
    setError(null);
    setResolutionNotice(null);
    try {
      const res = await recomputeConflicts();
      const d = res.data || {};
      await loadCalendar(result?.study_id);
      if (result?.study_id) {
        const detail = await getStudySchedule(result.study_id).catch(() => null);
        if (detail?.data) setResult(detail.data);
      }
      onScheduled?.();
      setResolutionNotice(
        `Tüm çakışmalar yeniden hesaplandı: ${d.confirmed_conflicts ?? 0} gerçek çakışma, ${d.missing_info_conflicts ?? 0} eksik bilgi kaynaklı olası çakışma (${d.total_completed_steps ?? 0} geçmiş adım TAMAMLANDI).`
      );
    } catch (err) {
      setError(extractError(err, 'Çakışmalar yeniden hesaplanırken hata oluştu.'));
    } finally {
      setRecomputingConflicts(false);
    }
  };

  const handlePreviewBioRevision = async (targetStudyId = null) => {
    const sid = targetStudyId || result?.study_id;
    if (!sid) return;
    setLoadingBioPreview(true);
    setBioRevisionError(null);
    try {
      const res = await getBiologicalRevisionPreview(sid);
      setBioRevisionPreview(res.data || null);
    } catch (err) {
      setBioRevisionError(extractError(err, 'Biyolojik plan revizyonu önizlemesi alınamadı.'));
    } finally {
      setLoadingBioPreview(false);
    }
  };

  const handleApproveBioRevision = async () => {
    if (!result?.study_id || isReadOnly) return;
    const domVal =
      typeof document !== 'undefined'
        ? document.getElementById('bioRevisionReasonInput')?.value
        : '';
    const trimmedReason = (bioRevisionReason || domVal || '').trim();
    if (!trimmedReason) {
      setBioRevisionError('Biyolojik plan revizyonunu onaylamak için gerekçe girilmesi zorunludur.');
      return;
    }
    setApprovingBioRevision(true);
    setBioRevisionError(null);
    setError(null);
    setResolutionNotice(null);
    try {
      const res = await approveBiologicalRevision(result.study_id, {
        reason: trimmedReason,
        preview_token: bioRevisionPreview?.preview_token || undefined,
      });
      if (res.data) {
        setResult(res.data);
      }
      setBioRevisionReason('');
      await handlePreviewBioRevision(result.study_id);
      await loadCalendar(result.study_id);
      onScheduled?.();
      setResolutionNotice(
        `'${result.study_code}' için SD biyolojik plan revizyonu onaylandı ve uygun bekleyen adımların yeni saatleri resmî takvime işlendi.`
      );
    } catch (err) {
      setBioRevisionError(extractError(err, 'Biyolojik plan revizyonu onaylanırken hata oluştu.'));
    } finally {
      setApprovingBioRevision(false);
    }
  };

  const syncFormWithStudy = (st) => {
    if (!st) return;
    if (st.study_code) setStudyCode(st.study_code);
    if (st.acclimatization_start_date) {
      setStartDate(st.acclimatization_start_date);
      setDailyDate(st.acclimatization_start_date);
      setWeekStart(toMondayISO(st.acclimatization_start_date));
    }
    const tplCode =
      st.template?.code ||
      STUDY_CODE_TEMPLATE_MAP[(st.study_code || '').toUpperCase()];
    if (tplCode) setTemplateCode(tplCode);
    if (st.study_director_id) setSelectedSdId(String(st.study_director_id));
  };

  const handleSelectStudyCard = (st) => {
    if (st?.study_id !== result?.study_id) {
      setBioRevisionPreview(null);
      setBioRevisionError(null);
      setBioRevisionReason('');
    }
    setResult(st);
    setError(null);
    setResolutionNotice(null);
    syncFormWithStudy(st);
    if (st?.study_id) {
      getStudySchedule(st.study_id)
        .then((detailRes) => {
          if (detailRes?.data) setResult(detailRes.data);
        })
        .catch(() => {});
    }
  };

  const filteredStudiesList = useMemo(() => {
    const q = (studySearchQuery || '').trim().toLowerCase();
    return (calendarData.studies || []).filter((st) => {
      if (studyStatusFilter === 'DRAFT' && st.study_status !== 'DRAFT') return false;
      if (studyStatusFilter === 'APPROVED' && st.study_status === 'DRAFT') return false;
      if (studyStatusFilter === 'CRITICAL' && !(st.critical_conflicts > 0)) return false;
      if (!q) return true;
      const hay = `${st.study_code || ''} ${st.title || ''} ${st.sponsor_name || ''} ${st.test_item_name || ''} ${st.study_director_name || ''}`.toLowerCase();
      return hay.includes(q);
    });
  }, [calendarData.studies, studySearchQuery, studyStatusFilter]);

  const studyFilterCounts = useMemo(() => {
    const list = calendarData.studies || [];
    return {
      ALL: list.length,
      DRAFT: list.filter((s) => s.study_status === 'DRAFT').length,
      APPROVED: list.filter((s) => s.study_status !== 'DRAFT').length,
      CRITICAL: list.filter((s) => s.critical_conflicts > 0).length,
    };
  }, [calendarData.studies]);

  const handleLoadIntoForm = (st) => {
    syncFormWithStudy(st);
    setIsFormOpen(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const hasConflicts = result && result.total_conflicts > 0;
  const conflictStepIds = useMemo(
    () => new Set((result?.conflicts || []).flatMap((c) => c.step_ids || (c.step_id ? [c.step_id] : []))),
    [result]
  );

  // Haftalık takvim 7 gün (Pzt..Paz) hesaplaması
  const weekDays = useMemo(() => {
    const monday = toMondayISO(weekStart);
    return Array.from({ length: 7 }, (_, i) => {
      const iso = addDaysISO(monday, i);
      return {
        iso,
        dayName: DAY_NAMES_TR[i],
        isWeekend: i >= 5,
      };
    });
  }, [weekStart]);

  const filteredAllSteps = useMemo(() => {
    if (calendarStudyFilter === 'ALL') return calendarData.all_steps;
    return calendarData.all_steps.filter((s) => s.study_code === calendarStudyFilter);
  }, [calendarData.all_steps, calendarStudyFilter]);

  const stepsByDay = useMemo(() => {
    const map = {};
    for (const s of filteredAllSteps) {
      const d = (s.planned_start || '').slice(0, 10);
      if (!map[d]) map[d] = [];
      map[d].push(s);
    }
    return map;
  }, [filteredAllSteps]);

  // Günlük saatlik akış (08:00 - 18:00)
  const dailySteps = useMemo(() => stepsByDay[dailyDate] || [], [stepsByDay, dailyDate]);
  const hourlySlots = useMemo(() => {
    const hours = Array.from({ length: 11 }, (_, idx) => 8 + idx); // 08:00 .. 18:00
    return hours.map((h) => {
      const slotStart = new Date(`${dailyDate}T${String(h).padStart(2, '0')}:00:00`);
      const slotEnd = new Date(`${dailyDate}T${String(h + 1).padStart(2, '0')}:00:00`);
      const matching = dailySteps.filter((s) => {
        const ps = new Date(s.planned_start);
        const pe = new Date(s.planned_end);
        return ps < slotEnd && pe > slotStart;
      });
      return {
        hourLabel: `${String(h).padStart(2, '0')}:00`,
        steps: matching,
      };
    });
  }, [dailyDate, dailySteps]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            Çoklu Çalışma Planlama & Kalıcı Master Operasyon Takvimi
          </h2>
          <p className="text-sm text-slate-500">
            Kayıtlı taslak ve onaylı çalışmaların takvimleri kalıcı olarak saklanır; çakışma çözümleri, haftalık/günlük
            akış ve çalışma onayları tek ekrandan yönetilir.
          </p>
        </div>

        {/* Görünüm Sekmeleri ve Çakışmaları Yeniden Hesapla */}
        <div className="flex flex-wrap items-center gap-2">
          {!isReadOnly && (
            <button
              type="button"
              disabled={recomputingConflicts}
              onClick={handleRecomputeAllConflicts}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-900 bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 shadow-xs transition disabled:opacity-60"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${recomputingConflicts ? 'animate-spin' : ''}`} />
              <span>{t('Çakışmaları Yeniden Hesapla', 'Recompute Conflicts')}</span>
            </button>
          )}
          <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-xs">
            <button
              type="button"
              onClick={() => setViewMode('study')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                viewMode === 'study'
                  ? 'bg-slate-900 text-white shadow-xs'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Çalışma Detay & Gantt</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode('weekly')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                viewMode === 'weekly'
                  ? 'bg-slate-900 text-white shadow-xs'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <CalendarIcon className="w-3.5 h-3.5" />
              <span>Haftalık Master Takvim (Pzt–Paz)</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode('daily')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                viewMode === 'daily'
                  ? 'bg-slate-900 text-white shadow-xs'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Clock className="w-3.5 h-3.5" />
              <span>Günlük Saatlik Akış (08:00–18:00)</span>
            </button>
          </div>
        </div>
      </div>

      {/* FAZ 6.3 & 8.4: Kayıtlı & Taslak Çalışmalar Açılır/Kapanır (Collapsible) Seçim Paneli */}
      <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
        <button
          type="button"
          data-testid="toggle-studies-list-btn"
          onClick={() => setIsStudiesListOpen((v) => !v)}
          className="w-full px-4 py-3 flex flex-wrap items-center justify-between gap-2 text-left hover:bg-slate-50 transition"
        >
          <div className="flex items-center gap-2">
            {isStudiesListOpen ? (
              <ChevronDown className="w-4 h-4 text-slate-500" />
            ) : (
              <ChevronRight className="w-4 h-4 text-slate-500" />
            )}
            <CalendarIcon className="w-4 h-4 text-slate-500" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-800">
              Kayıtlı & Taslak Çalışmalar ({calendarData.studies.length})
            </h3>
            {result?.study_code && (
              <span className="font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                Seçili: {result.study_code}
              </span>
            )}
          </div>
          <span className="text-[11px] text-slate-500">
            {isStudiesListOpen
              ? 'Paneli daraltmak için tıklayın'
              : 'Çalışma listesini, arama ve filtreleri açmak için tıklayın'}
          </span>
        </button>

        {isStudiesListOpen && (
          <div className="border-t border-slate-200 p-4 space-y-3">
            {/* Hızlı Arama ve Durum Filtreleri */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="relative flex-1 min-w-[240px] max-w-md">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  value={studySearchQuery}
                  onChange={(e) => setStudySearchQuery(e.target.value)}
                  placeholder="GLP kodu, test, sponsor ara..."
                  className="w-full border border-slate-300 rounded-md pl-8 pr-7 py-1.5 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-slate-900"
                />
                {studySearchQuery && (
                  <button
                    type="button"
                    onClick={() => setStudySearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                    title="Aramayı temizle"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { key: 'ALL', label: 'Tümü' },
                  { key: 'DRAFT', label: 'Taslak' },
                  { key: 'APPROVED', label: 'Onaylı' },
                  { key: 'CRITICAL', label: 'Kritik Çakışmalı' },
                ].map((f) => {
                  const active = studyStatusFilter === f.key;
                  return (
                    <button
                      key={f.key}
                      type="button"
                      onClick={() => setStudyStatusFilter(f.key)}
                      className={`px-2.5 py-1 rounded-md text-xs font-semibold border transition ${
                        active
                          ? 'bg-slate-900 text-white border-slate-900'
                          : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      {f.label} ({studyFilterCounts[f.key] ?? 0})
                    </button>
                  );
                })}
              </div>
            </div>

            {loadingCalendar && calendarData.studies.length === 0 ? (
              <p className="text-xs text-slate-400 py-2">Kayıtlı çalışmalar yükleniyor…</p>
            ) : filteredStudiesList.length === 0 ? (
              <p className="text-xs text-slate-500 py-2">
                Arama veya filtre kriterlerine uygun çalışma bulunamadı.
              </p>
            ) : (
              <div className="max-h-[420px] overflow-y-auto pr-1 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredStudiesList.map((st) => {
                  const isSelected = result?.study_id === st.study_id;
                  const isDraft = st.study_status === 'DRAFT';
                  return (
                    <div
                      key={st.study_id}
                      data-testid={`study-card-${st.study_code}`}
                      onClick={() => handleSelectStudyCard(st)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') handleSelectStudyCard(st);
                      }}
                      className={`cursor-pointer rounded-lg border p-3.5 transition text-left flex flex-col justify-between gap-2 ${
                        isSelected
                          ? 'border-blue-500 bg-blue-50/50 shadow-xs'
                          : 'border-slate-200 hover:border-blue-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="space-y-1.5 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <span
                            className="font-mono text-xs font-bold text-slate-900 truncate max-w-[165px]"
                            title={st.study_code}
                          >
                            {st.study_code}
                          </span>
                          <div className="shrink-0 flex flex-wrap items-center justify-end gap-1">
                            {st.critical_conflicts > 0 ? (
                              <span className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded bg-red-600 text-white">
                                {st.critical_conflicts} KRİTİK
                              </span>
                            ) : st.warning_conflicts > 0 ? (
                              <span className="shrink-0 text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500 text-white">
                                {st.warning_conflicts} UYARI
                              </span>
                            ) : (
                              <span className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded border border-[#6ee7b7] bg-[#ecfdf5] text-[#065f46] dark:bg-[#062e22] dark:text-[#a7f3d0] dark:border-emerald-500/45">
                                Çakışmasız
                              </span>
                            )}
                            <span
                              className={`shrink-0 text-[10px] font-bold px-2 py-0.5 rounded border ${
                                isDraft
                                  ? 'bg-amber-50 text-amber-800 border-amber-300'
                                  : 'bg-[#ecfdf5] text-[#065f46] border-[#6ee7b7] dark:bg-[#062e22] dark:text-[#a7f3d0] dark:border-emerald-500/45'
                              }`}
                            >
                              {isDraft ? 'TASLAK' : 'ONAYLI'}
                            </span>
                          </div>
                        </div>

                        <p className="text-xs font-medium text-slate-700 truncate" title={st.title}>
                          {st.title}
                        </p>
                        {st.sponsor_name && (
                          <p className="text-[11px] text-slate-500 truncate">Sponsor: {st.sponsor_name}</p>
                        )}
                      </div>

                      <div className="pt-2 border-t border-slate-200/70 flex items-center justify-between text-[11px] text-slate-600">
                        <span>
                          Gün 0: <strong>{st.acclimatization_start_date}</strong> · {st.total_new_steps} adım
                        </span>
                        {isDraft && !isReadOnly && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleLoadIntoForm(st);
                            }}
                            className="inline-flex items-center gap-1 text-blue-700 hover:underline font-medium shrink-0"
                            title="Bu taslağın kodunu ve tarihini yukarıdaki forma aktar"
                          >
                            <Edit3 className="w-3 h-3" />
                            <span>Forma Aktar</span>
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {isReadOnly && (
        <div className="flex items-center gap-2.5 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
          <Eye className="w-4 h-4 text-amber-700 shrink-0" />
          <span>
            <strong>{isExecutive || role !== 'QA' ? 'Üst Yönetim İzleme Görünümü (Salt Okunur):' : 'Kalite Güvence (QA) Salt Okunur Modu:'}</strong> Haftalık/Günlük takvimleri, çakışma detaylarını ve iş yükünü inceleyebilir, Study Plan Taslağı İndir (.docx) butonunu kullanabilirsiniz; planlama ve onaylama işlemleri kapalıdır.

          </span>
        </div>
      )}

      {prefill && viewMode === 'study' && (
        <div className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-3 text-xs text-blue-900">
          <div className="flex items-start gap-2.5">
            <Sparkles className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
            <div className="flex-1 space-y-1">
              <p>
                <strong>
                  {prefill.from_dossier
                    ? 'Birleştirilmiş Çalışma Dosyası Özeti (Master Study Profile) aktarıldı:'
                    : 'Form belgeden otomatik dolduruldu:'}
                </strong>{' '}
                <span className="font-mono">{prefill.source_filename}</span>
                {prefill.source_document_id && !prefill.from_dossier && ` (Belge #${prefill.source_document_id})`}
                {prefill.test_type && <> · Test: <strong>{prefill.test_type}</strong></>}
                {prefill.guideline && <> · Kılavuz: <strong>{prefill.guideline}</strong></>}
              </p>
              {(prefill.sponsor_name ||
                prefill.test_item_name ||
                prefill.test_item_batch ||
                prefill.extraction_polar !== null ||
                prefill.extraction_non_polar !== null ||
                prefill.animal_species_strain) && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-1.5 pb-1">
                  {prefill.sponsor_name && (
                    <div className="bg-white/80 rounded border border-blue-200 px-2.5 py-1.5">
                      <span className="block text-[10px] uppercase text-blue-600 font-semibold">Sponsor</span>
                      <span className="font-medium text-slate-800">{prefill.sponsor_name}</span>
                    </div>
                  )}
                  {prefill.test_item_name && (
                    <div className="bg-white/80 rounded border border-blue-200 px-2.5 py-1.5">
                      <span className="block text-[10px] uppercase text-blue-600 font-semibold">Test Maddesi & Lot</span>
                      <span className="font-medium text-slate-800">
                        {prefill.test_item_name}
                        {(prefill.test_item_batch || prefill.lot_batch_no) &&
                          ` (Lot: ${prefill.test_item_batch || prefill.lot_batch_no})`}
                      </span>
                    </div>
                  )}
                  {(prefill.extraction_polar !== null || prefill.extraction_non_polar !== null) && (
                    <div className="bg-white/80 rounded border border-blue-200 px-2.5 py-1.5">
                      <span className="block text-[10px] uppercase text-blue-600 font-semibold">Ekstraksiyon</span>
                      <span className="font-medium text-slate-800">
                        Polar:{' '}
                        {prefill.extraction_polar === true
                          ? `Evet (${prefill.extraction_polar_solvent || 'Salin'})`
                          : prefill.extraction_polar === false
                            ? 'Hayır'
                            : '—'}
                        {' · '}
                        Apolar:{' '}
                        {prefill.extraction_non_polar === true
                          ? `Evet (${prefill.extraction_non_polar_solvent || 'Yağ'})`
                          : prefill.extraction_non_polar === false
                            ? 'Hayır'
                            : '—'}
                      </span>
                    </div>
                  )}
                  {(prefill.animal_species_strain || prefill.animal_count) && (
                    <div className="bg-white/80 rounded border border-blue-200 px-2.5 py-1.5">
                      <span className="block text-[10px] uppercase text-blue-600 font-semibold">Hayvan Bilgisi</span>
                      <span className="font-medium text-slate-800">
                        {prefill.animal_species_strain || '—'}
                        {prefill.animal_count && ` (${prefill.animal_count})`}
                      </span>
                    </div>
                  )}
                </div>
              )}
              <p className="text-blue-800">
                Değerler yapay zeka önerisidir. Göndermeden önce belgeyle karşılaştırın; gönderim, tüm çalışma dosyası
                profilini çalışmaya kaydeder ve denetim izine işler.
              </p>
              {prefill.sd_resolution?.requires_handover && (
                <div className="mt-2 rounded-md border border-amber-400 bg-amber-50 px-3 py-2.5 text-amber-950 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-start gap-2">
                    <UserCheck className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
                    <span>
                      <strong>SD Devir Uyarısı:</strong> {prefill.sd_resolution.message}
                    </span>
                  </div>
                  {activeSds.length > 0 && (
                    <select
                      aria-label="Çalışmayı devralacak aktif SD"
                      value={selectedSdId}
                      onChange={(e) => setSelectedSdId(e.target.value)}
                      className="border border-amber-400 bg-white text-slate-900 font-semibold rounded px-2.5 py-1 text-xs"
                    >
                      {activeSds.map((sd) => (
                        <option key={sd.id} value={sd.id}>
                          {sd.full_name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
              {(prefill.evidence?.study_code || prefill.evidence?.requested_start_date) && (
                <ul className="text-[11px] text-blue-700 italic space-y-0.5 pt-0.5">
                  {prefill.evidence?.study_code && <li>“{prefill.evidence.study_code}”</li>}
                  {prefill.evidence?.requested_start_date && <li>“{prefill.evidence.requested_start_date}”</li>}
                </ul>
              )}
              {prefill.needs_review && (
                <p className="text-amber-800 font-medium flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5" /> AI bu belge için manuel doğrulama önerdi.
                </p>
              )}
              {(!prefill.study_code || !prefill.start_date) && (
                <p className="text-amber-800 font-medium flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5" /> Belgede bulunamayan alanları elle doldurun.
                </p>
              )}
              {prefillEdited && <p className="text-slate-600">Not: Önerilen değerlerden en az biri elle değiştirildi.</p>}
            </div>
            <button
              type="button"
              onClick={clearPrefill}
              className="text-blue-700 hover:text-blue-900"
              title="Ön doldurmayı temizle"
              aria-label="Ön doldurmayı temizle"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Yeni Çalışma Ekleme / Taslak Yeniden Analiz Formu (Yalnızca Çalışma Detay sekmesinde, varsayılan daraltılmış) */}
      {viewMode === 'study' && !isReadOnly && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <button
            type="button"
            onClick={() => setIsFormOpen((v) => !v)}
            className="w-full px-5 py-3.5 flex flex-wrap items-center justify-between gap-2 text-left hover:bg-slate-50 transition"
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-blue-800">
              {isFormOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              <span>Seçili Çalışmanın Başlangıç Tarihini (Gün 0) Değiştir veya Manuel Simülasyon Yap</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              {studyCode && (
                <span className="font-mono font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                  {studyCode} · Gün 0: {startDate}
                </span>
              )}
              <span>{isFormOpen ? 'Paneli Daralt' : 'Formu Aç'}</span>
            </div>
          </button>

          {isFormOpen && (
            <form onSubmit={handleSubmit} className="border-t border-slate-200">
              <div className="p-5 grid grid-cols-1 md:grid-cols-[1.3fr_1fr_1fr_auto] gap-4 items-end">
                <div>
                  <label htmlFor="template" className="block text-xs font-medium text-slate-700 mb-1.5">
                    Test Şablonu
                  </label>
                  <select
                    id="template"
                    value={templateCode}
                    onChange={(e) => setTemplateCode(e.target.value)}
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
                  >
                    {templates.map((t) => (
                      <option key={t.code} value={t.code}>
                        {t.standard} — {t.title}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="studyCode" className="block text-xs font-medium text-slate-700 mb-1.5">
                    Çalışma Kodu (Yeni veya Mevcut Taslak)
                  </label>
                  <input
                    id="studyCode"
                    required
                    disabled={isReadOnly}
                    value={studyCode}
                    onChange={(e) => {
                      const val = e.target.value;
                      setStudyCode(val);
                      const upper = val.trim().toUpperCase();
                      if (STUDY_CODE_TEMPLATE_MAP[upper]) {
                        setTemplateCode(STUDY_CODE_TEMPLATE_MAP[upper]);
                      }
                      const existing = calendarData.studies.find(
                        (s) => (s.study_code || '').toUpperCase() === upper
                      );
                      if (existing?.acclimatization_start_date) {
                        setStartDate(existing.acclimatization_start_date);
                      }
                    }}
                    placeholder="GLP2026-026"
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:bg-slate-100"
                  />
                </div>
                <div>
                  <label htmlFor="startDate" className="block text-xs font-medium text-slate-700 mb-1.5">
                    Aklimatizasyon Başlangıcı (Gün 0)
                  </label>
                  <input
                    id="startDate"
                    type="date"
                    required
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                  />
                </div>
                <button
                  type="submit"
                  disabled={isReadOnly || submitting || !templateCode}
                  title={isReadOnly ? 'QA rolü salt okunur yetkiye sahiptir' : undefined}
                  className="flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 disabled:bg-slate-300 disabled:text-slate-500 text-white text-sm font-medium rounded-md px-5 py-2.5"
                >
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <CalendarPlus className="w-4 h-4" />}
                  {isReadOnly ? 'Salt Okunur (QA)' : submitting ? 'Analiz ediliyor…' : 'Planla ve Analiz Et'}
                </button>
              </div>

              {template && (
                <div className="border-t border-slate-200">
                  <button
                    type="button"
                    onClick={() => setShowTemplate((v) => !v)}
                    className="w-full flex items-center gap-2 px-5 py-2.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    {showTemplate ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                    Şablon önizlemesi — {template.steps.length} adım (seçilen Gün 0'a göre)
                    {weekendLocked.length > 0 && (
                      <span className="ml-2 text-amber-700 font-semibold">
                        ⚠ {weekendLocked.length} kilitli adım hafta sonuna düşüyor
                      </span>
                    )}
                  </button>
                  {showTemplate && (
                    <table className="w-full text-xs">
                      <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-xs">
                        <tr>
                          <th className="text-left px-5 py-2 font-semibold">Gün</th>
                          <th className="text-left px-5 py-2 font-semibold">Tarih</th>
                          <th className="text-left px-5 py-2 font-semibold">Adım</th>
                          <th className="text-left px-5 py-2 font-semibold">Saat / Süre</th>
                          <th className="text-left px-5 py-2 font-semibold">Rol</th>
                          <th className="text-left px-5 py-2 font-semibold">Kilit</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {preview.map((s) => (
                          <tr
                            key={s.order}
                            className={
                              weekendLocked.some((w) => w.order === s.order) ? 'bg-amber-50' : ''
                            }
                          >
                            <td className="px-5 py-2 font-mono font-semibold text-slate-700">G{s.day}</td>
                            <td
                              className={`px-5 py-2 ${
                                weekendLocked.some((w) => w.order === s.order)
                                  ? 'text-amber-700 font-medium'
                                  : 'text-slate-600'
                              }`}
                            >
                              {s.date.toLocaleDateString('tr-TR', { weekday: 'short', day: '2-digit', month: '2-digit' })}
                            </td>
                            <td className="px-5 py-2 text-slate-800">{s.name}</td>
                            <td className="px-5 py-2 text-slate-600 whitespace-nowrap">
                              {s.start} • {fmtMinutes(s.duration_minutes)}
                            </td>
                            <td className="px-5 py-2 text-slate-600">
                              {s.roles.map((r) => ROLE_SHORT[r] || r).join(' + ')}
                            </td>
                            <td className="px-5 py-2">
                              {s.is_biological_fixed_time ? (
                                <span className="inline-flex items-center gap-1 text-blue-700 font-medium">
                                  <Lock className="w-3 h-3" /> ±{s.tolerance_minutes} dk
                                </span>
                              ) : (
                                <span className="text-slate-400">Esnek</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  <p className="px-5 py-2.5 text-[11px] text-slate-500 flex items-start gap-1.5 border-t border-slate-100">
                    <Info className="w-3.5 h-3.5 mt-px shrink-0" />
                    Saat, süre ve tolerans değerleri sistem varsayılanıdır; protokole göre SD tarafından teyit edilmelidir.
                    Kod sistemde yoksa DRAFT çalışma açılır. Onaylı çalışmalar yeniden planlanamaz.
                  </p>
                </div>
              )}
            </form>
          )}
        </div>
      )}

      {error && <div className="p-4 rounded-md bg-red-50 border border-red-300 text-sm text-red-800">{error}</div>}

      {resolutionNotice && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-xs text-emerald-900 flex items-center gap-2.5">
          <CheckCircle2 className="w-4 h-4 text-emerald-700 shrink-0" />
          <span className="font-semibold">{resolutionNotice}</span>
        </div>
      )}

      {/* =====================================================================
          SEKME 1: SEÇİLİ ÇALIŞMA DETAY, ÇAKIŞMA ÇÖZÜM MERKEZİ, ONAY VE GANTT
         ===================================================================== */}
      {viewMode === 'study' && result && (
        <>
          {/* Seçili Çalışma Üst Aksiyon ve Onay Kartı */}
          <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-xs flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-base font-bold text-slate-900">{result.study_code}</span>
                <span
                  className={`text-xs font-bold px-2.5 py-0.5 rounded border ${
                    result.study_status === 'DRAFT'
                      ? 'bg-amber-50 text-amber-800 border-amber-300'
                      : 'bg-emerald-50 text-emerald-800 border-emerald-300'
                  }`}
                >
                  {result.study_status === 'DRAFT' ? 'TASLAK (DRAFT)' : 'ONAYLI / AKTİF (APPROVED)'}
                </span>
                {result.study_director_name && (
                  <span className="text-xs text-slate-600">
                    · Aktif SD: <strong>{result.study_director_name}</strong>
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-600">
                {result.title || `${result.template?.standard} ${result.template?.title}`}
                {result.sponsor_name && <> · Sponsor: <strong>{result.sponsor_name}</strong></>}
                {result.test_item_name && <> · Test Maddesi: <strong>{result.test_item_name}</strong></>}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              {result.study_status === 'DRAFT' && !isReadOnly && (
                <button
                  type="button"
                  disabled={approving || result.critical_conflicts > 0 || !result.steps?.length}
                  onClick={handleApproveStudy}
                  title={
                    result.critical_conflicts > 0
                      ? 'Planı onaylamak için önce aşağıdaki kritik çakışmaları çözün.'
                      : 'Taslak çalışma planını onaylayarak Aktif Çalışmalar (APPROVED) listesine alır.'
                  }
                  className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 disabled:text-slate-500 text-white text-xs font-bold px-4 py-2.5 rounded-lg shadow-xs transition"
                >
                  {approving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <CheckCheck className="w-4 h-4" />
                  )}
                  <span>Planı Onayla ve Aktif Çalışmalara Al (APPROVE)</span>
                </button>
              )}

              <button
                type="button"
                disabled={downloadingDocx}
                onClick={handleDownloadStudyPlan}
                className="inline-flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold px-4 py-2.5 rounded-lg shadow-xs transition disabled:opacity-50"
              >
                {downloadingDocx ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <FileDown className="w-3.5 h-3.5" />
                )}
                <span>Study Plan Taslağı İndir (.docx)</span>
              </button>
            </div>
          </div>

          {result.auto_schedule_notice?.text && (
            <div className="bg-white border border-slate-200 border-l-2 border-l-amber-500 rounded-lg px-4 py-2.5 text-xs text-slate-800">
              {result.auto_schedule_notice.text}
            </div>
          )}
          <CapacityTags info={result.capacity_info} />

          {hasConflicts ? (
            <ConflictAlert
              conflicts={result.conflicts}
              steps={result.steps}
              isReadOnly={isReadOnly}
              onApplyResolution={handleApplyResolution}
              title={
                result.critical_conflicts > 0
                  ? `${result.study_code}: ${result.critical_conflicts} kritik çakışma — tek tık çözüm seçin`
                  : `${result.study_code}: ${
                      result.warning_conflicts || result.total_conflicts
                    } HAFTA SONU / MESAİ UYARISI — KARAR DESTEK SEÇENEKLERİ`
              }
            />
          ) : (
            <div className="rounded-lg border border-[#6ee7b7] bg-[#ecfdf5] dark:bg-[#062e22] dark:border-emerald-500/45 p-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="w-5 h-5 text-[#047857] dark:text-[#a7f3d0]" />
                <p className="text-sm text-[#065f46] dark:text-[#ecfdf5]">
                  <strong>{result.study_code}</strong> çakışmasız planlandı ({result.template?.standard}).{' '}
                  {result.total_new_steps} adım takvime yerleştirildi
                  {result.study_director_name && (
                    <>
                      {' '}
                      · Aktif SD: <strong>{result.study_director_name}</strong>
                    </>
                  )}
                  {result.study_status === 'DRAFT'
                    ? '; onaylanarak aktif çalışmalara alınmaya hazırdır.'
                    : '; çalışma ONAYLI (APPROVED) statüsündedir.'}
                </p>
              </div>
            </div>
          )}

          {/* Biyolojik Plan Revizyonu (SD Onayı) ve Kaynak Sapma İzleme Kartı */}
          {((result.source_deviations && result.source_deviations.length > 0) ||
            (result.revision_proposals && result.revision_proposals.length > 0) ||
            (result.ineligible_revision_steps && result.ineligible_revision_steps.length > 0) ||
            (result.biological_revisions && result.biological_revisions.length > 0) ||
            (result.steps || []).some((s) => s.actual_reference_time)) && (
            <div
              data-testid="bio-revision-section"
              className="bg-white border border-indigo-200 rounded-lg shadow-xs overflow-hidden"
            >
              <div className="px-5 py-3.5 bg-indigo-50/70 border-b border-indigo-200 flex flex-wrap items-center justify-between gap-3">
                <div className="space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Clock className="w-4 h-4 text-indigo-700" />
                    <h3 className="text-sm font-bold text-indigo-950">
                      Biyolojik Plan Revizyonu ve Referans Saat Sapma Yönetimi (SD Onayı)
                    </h3>
                    {result.revision_proposals?.length > 0 && (
                      <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-300">
                        {result.revision_proposals.length} Uygun Adım Revizyon Bekliyor
                      </span>
                    )}
                    {(result.source_deviations || []).some((sd) => sd.sd_revision_approved) && (
                      <span
                        data-testid="bio-sd-approved-badge"
                        className="text-[11px] font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 border border-emerald-300"
                      >
                        SD Onaylı Revizyon Uygulandı
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-600">
                    Gerçek biyolojik referans saatine göre bağımlı gözlem adımlarının önerilen yeni saatlerini
                    önizleyin, engelleri denetleyin ve Çalışma Yöneticisi (SD) gerekçesiyle resmî takvime işleyin.
                  </p>
                </div>

                <button
                  type="button"
                  data-testid="preview-bio-revision-btn"
                  disabled={loadingBioPreview}
                  onClick={() => handlePreviewBioRevision(result.study_id)}
                  className="inline-flex items-center gap-1.5 bg-indigo-700 hover:bg-indigo-800 disabled:bg-slate-300 text-white text-xs font-semibold px-3.5 py-2 rounded-md shadow-xs transition"
                >
                  {loadingBioPreview ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Eye className="w-3.5 h-3.5" />
                  )}
                  <span>Revizyon Önizlemesi</span>
                </button>
              </div>

              <div className="p-5 space-y-4 text-xs">
                {/* Kaynak Biyolojik Referans Adımı ve Korunan Geçmiş Sapma */}
                {(result.source_deviations || []).map((src) => (
                  <div
                    key={src.step_id || src.step_order}
                    data-testid="bio-source-summary"
                    className="rounded-md border border-slate-200 bg-slate-50 p-3.5 flex flex-wrap items-center justify-between gap-3"
                  >
                    <div className="space-y-1">
                      <div className="font-semibold text-slate-900">
                        Kaynak Referans Adımı: #{src.step_order} — {src.step_name}
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-slate-700">
                        <span>
                          Planlanan Referans:{' '}
                          <strong className="font-mono">{fmtDateTime(src.planned_reference_time)}</strong>
                        </span>
                        <span data-testid="bio-source-actual-ref">
                          Gerçek Kaynak Referans:{' '}
                          <strong className="font-mono text-indigo-900">
                            {fmtDateTime(src.actual_reference_time)}
                          </strong>
                        </span>
                        <span>
                          Tolerans: <strong>±{src.biological_tolerance_minutes} dk</strong>
                        </span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        data-testid="bio-source-deviation-badge"
                        className={`font-mono font-bold px-2.5 py-1 rounded border ${
                          src.exceeds_tolerance
                            ? 'bg-amber-50 text-amber-900 border-amber-300'
                            : 'bg-emerald-50 text-emerald-900 border-emerald-300'
                        }`}
                      >
                        Kaynak Sapma: {src.deviation_minutes > 0 ? `+${src.deviation_minutes}` : src.deviation_minutes} dk
                      </span>
                      <span className="text-[11px] text-slate-500 italic">
                        (Orijinal kaynak planı ve geçmiş sapma kaydı korunur)
                      </span>
                    </div>
                  </div>
                ))}

                {/* Onaylanmış Biyolojik Revizyon Geçmişi */}
                {result.biological_revisions?.length > 0 && (
                  <div
                    data-testid="bio-revision-history"
                    className="rounded-md border border-emerald-300 bg-emerald-50/70 p-3.5 space-y-2"
                  >
                    <div className="font-bold text-emerald-950 flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4 text-emerald-700" />
                      <span>Kaydedilmiş SD Biyolojik Plan Revizyonu Kararı</span>
                    </div>
                    {result.biological_revisions.map((rev, idx) => (
                      <div
                        key={rev.revision_id || idx}
                        className="border-t border-emerald-200/80 pt-2 first:border-t-0 first:pt-0 text-emerald-950 space-y-1"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span>
                            Onaylayan: <strong>{rev.approved_by_name}</strong> ({rev.approved_by_role})
                          </span>
                          <span>·</span>
                          <span>
                            Kaynak Referans:{' '}
                            <strong className="font-mono">{fmtDateTime(rev.source_actual_reference_time)}</strong>
                          </span>
                          {rev.old_target_end_date !== rev.new_target_end_date && rev.new_target_end_date && (
                            <>
                              <span>·</span>
                              <span>
                                Çalışma Bitiş Tarihi:{' '}
                                <strong className="font-mono">
                                  {rev.old_target_end_date} → {rev.new_target_end_date}
                                </strong>
                              </span>
                            </>
                          )}
                        </div>
                        <div data-testid="bio-approved-reason" className="text-emerald-900">
                          SD Onay Gerekçesi: <strong>{rev.reason}</strong>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {bioRevisionError && (
                  <div
                    data-testid="bio-revision-error"
                    className="rounded-md border border-red-300 bg-red-50 px-3.5 py-2.5 text-red-900 font-medium"
                  >
                    {bioRevisionError}
                  </div>
                )}

                {/* Revizyon Önizleme Paneli */}
                {bioRevisionPreview && (
                  <div
                    data-testid="bio-revision-preview-panel"
                    className="rounded-md border border-indigo-200 bg-white p-4 space-y-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2.5">
                      <div>
                        <h4 className="font-bold text-slate-900 text-xs">
                          Revizyon Önizlemesi — {bioRevisionPreview.study_code}
                        </h4>
                        <p className="text-[11px] text-slate-500">
                          Bu önizleme salt-okunurdur; onaylanana kadar resmî çalışma takvimini veya durumunu değiştirmez.
                        </p>
                      </div>
                      {bioRevisionPreview.target_end_date_changed && (
                        <span
                          data-testid="bio-preview-end-date"
                          className="font-mono text-[11px] font-bold px-2.5 py-1 rounded bg-indigo-50 text-indigo-900 border border-indigo-200"
                        >
                          Hedef Bitiş Tarihi: {bioRevisionPreview.current_target_end_date} →{' '}
                          {bioRevisionPreview.proposed_target_end_date}
                        </span>
                      )}
                    </div>

                    {/* Etkilenen ve Uygun Olmayan Bağımlı Adımlar Tablosu */}
                    {bioRevisionPreview.all_dependent_steps?.length > 0 ? (
                      <div className="overflow-x-auto border border-slate-200 rounded-md">
                        <table className="w-full text-xs">
                          <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider text-[11px]">
                            <tr>
                              <th className="text-left px-3 py-2 font-semibold">Adım</th>
                              <th className="text-left px-3 py-2 font-semibold">Durum</th>
                              <th className="text-left px-3 py-2 font-semibold">Çalışma Günü</th>
                              <th className="text-left px-3 py-2 font-semibold">Mevcut Plan (Başlangıç–Bitiş)</th>
                              <th className="text-left px-3 py-2 font-semibold">Önerilen Plan (Başlangıç–Bitiş)</th>
                              <th className="text-left px-3 py-2 font-semibold">Uygunluk / Neden</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {bioRevisionPreview.all_dependent_steps.map((st) => (
                              <tr
                                key={st.step_id || st.step_order}
                                data-testid={`bio-preview-step-row-${st.step_order}`}
                                className={st.eligible ? 'bg-indigo-50/30' : 'bg-slate-50 text-slate-500'}
                              >
                                <td className="px-3 py-2 font-medium text-slate-900">
                                  #{st.step_order} — {st.step_name}
                                </td>
                                <td className="px-3 py-2 font-mono">{st.status}</td>
                                <td
                                  data-testid={`bio-preview-day-${st.step_order}`}
                                  className="px-3 py-2 font-mono font-semibold"
                                >
                                  G{st.current_study_day}
                                  {st.day_changed && (
                                    <span className="ml-1 text-indigo-700 font-bold">
                                      → G{st.proposed_study_day} (Yeni Gün)
                                    </span>
                                  )}
                                </td>
                                <td className="px-3 py-2 font-mono whitespace-nowrap">
                                  {fmtDateTime(st.current_planned_start)} – {fmtTime(st.current_planned_end)}
                                </td>
                                <td
                                  data-testid={`bio-preview-proposed-${st.step_order}`}
                                  className="px-3 py-2 font-mono font-semibold text-indigo-900 whitespace-nowrap"
                                >
                                  {fmtDateTime(st.expected_start)} – {fmtTime(st.expected_end)}
                                </td>
                                <td className="px-3 py-2">
                                  {st.eligible ? (
                                    <span className="inline-flex items-center px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 font-semibold">
                                      Güncellenmeye Uygun
                                    </span>
                                  ) : (
                                    <span
                                      data-testid={`bio-preview-ineligible-${st.step_order}`}
                                      className="inline-flex items-center px-2 py-0.5 rounded bg-amber-100 text-amber-900 font-medium"
                                    >
                                      Değiştirilemez: {st.ineligible_reason}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-slate-600 italic">Bu çalışmada bağımlı biyolojik gözlem adımı bulunamadı.</p>
                    )}

                    {/* Yeni Saatlerde Oluşan / Devam Eden Engeller */}
                    {bioRevisionPreview.blocking_conflicts?.length > 0 ? (
                      <div
                        data-testid="bio-preview-blockers"
                        className="rounded-md border border-red-300 bg-red-50 p-3.5 space-y-2 text-red-950"
                      >
                        <div className="font-bold flex items-center gap-1.5 text-red-900">
                          <AlertTriangle className="w-4 h-4 shrink-0" />
                          <span>
                            Önerilen Yeni Saatlerde Kritik Planlama / Kapasite Engelleri (
                            {bioRevisionPreview.blocking_conflicts.length})
                          </span>
                        </div>
                        <ul className="list-disc list-inside space-y-1 text-red-900">
                          {bioRevisionPreview.blocking_conflicts.map((bc, idx) => (
                            <li key={idx}>
                              <strong>{bc.title}:</strong> {bc.description}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <div
                        data-testid="bio-preview-no-blockers"
                        className="rounded-md border border-emerald-200 bg-emerald-50 px-3.5 py-2 text-emerald-900 flex items-center gap-2"
                      >
                        <CheckCircle2 className="w-4 h-4 text-emerald-700 shrink-0" />
                        <span>
                          Önerilen saatlerde kritik personel çakışması, 9 saat iş yükü aşımı, cihaz veya oda/kafes
                          kapasitesi engeli bulunmamaktadır.
                        </span>
                      </div>
                    )}

                    {/* SD Revizyon Onay Formu */}
                    {!isReadOnly && (
                      <div className="border-t border-slate-200 pt-3.5 space-y-3">
                        <div>
                          <label
                            htmlFor="bioRevisionReasonInput"
                            className="block text-xs font-semibold text-slate-800 mb-1"
                          >
                            Çalışma Yöneticisi (SD) Revizyon Onay Gerekçesi (Zorunlu)
                          </label>
                          <input
                            id="bioRevisionReasonInput"
                            type="text"
                            data-testid="bio-revision-reason-input"
                            value={bioRevisionReason}
                            onChange={(e) => setBioRevisionReason(e.target.value)}
                            placeholder="Örn: Dozlama +180 dk geciktiği için 24/48/72. saat gözlemleri gerçek referansa göre revize edildi."
                            className="w-full border border-slate-300 rounded-md px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-600"
                          />
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-[11px] text-slate-500">
                            {bioRevisionPreview.status_reason ||
                              `${bioRevisionPreview.affected_steps?.length || 0} uygun PENDING adım resmî takvimde güncellenecektir.`}
                          </span>
                          <button
                            type="button"
                            data-testid="approve-bio-revision-btn"
                            disabled={
                              approvingBioRevision ||
                              !bioRevisionPreview.can_approve_revision
                            }
                            onClick={handleApproveBioRevision}
                            className="inline-flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 disabled:text-slate-500 text-white text-xs font-bold px-4 py-2 rounded-md shadow-xs transition"
                          >
                            {approvingBioRevision ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <CheckCheck className="w-3.5 h-3.5" />
                            )}
                            <span>Revizyonu Onayla ve Takvime İşle</span>
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid gap-2 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-slate-500" />
              <span className="font-medium">Dokunulmayan onaylı çalışmalar:</span>
              {result.untouched_approved_studies?.length ? (
                result.untouched_approved_studies.map((c) => (
                  <Chip key={c} tone="emerald">
                    {c}
                  </Chip>
                ))
              ) : (
                <span className="italic">yok</span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Files className="w-4 h-4 text-slate-500" />
              <span className="font-medium">Kıyaslanan diğer taslaklar:</span>
              {result.compared_draft_studies?.length ? (
                result.compared_draft_studies.map((c) => (
                  <Chip key={c} tone="amber">
                    {c}
                  </Chip>
                ))
              ) : (
                <span className="italic">yok</span>
              )}
            </div>
            {result.superseded_conflicts > 0 && (
              <p className="text-slate-500">
                Önceki analizden {result.superseded_conflicts} çakışma kaydı “SUPERSEDED” notuyla kapatıldı (denetim
                izinde saklanır).
              </p>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-lg shadow-xs">
            <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-800">
                Üretilen Takvim — {result.study_code} ({result.template?.standard} {result.template?.title})
              </h3>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (result.acclimatization_start_date) {
                      setWeekStart(toMondayISO(result.acclimatization_start_date));
                    }
                    setViewMode('weekly');
                  }}
                  className="text-xs font-medium text-blue-700 hover:underline"
                >
                  Haftalık Master Takvimde Gör →
                </button>
              </div>
            </div>
            <div className="p-5">
              <GanttChart
                steps={result.steps}
                conflictStepIds={conflictStepIds}
                mode={hasConflicts ? 'conflict' : 'draft'}
                conflictCount={result.total_conflicts}
              />
            </div>
            <table className="w-full text-sm border-t border-slate-200">
              <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left px-5 py-2.5 font-semibold">Gün</th>
                  <th className="text-left px-5 py-2.5 font-semibold">Adım</th>
                  <th className="text-left px-5 py-2.5 font-semibold">Başlangıç</th>
                  <th className="text-left px-5 py-2.5 font-semibold">Süre</th>
                  <th className="text-left px-5 py-2.5 font-semibold">Atanan</th>
                  <th className="text-left px-5 py-2.5 font-semibold">Kilit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.steps.map((s) => {
                  const flagged = conflictStepIds.has(s.id);
                  return (
                    <tr
                      key={s.id}
                      data-testid={`schedule-step-row-${s.step_order}`}
                      className={flagged ? 'bg-red-50' : ''}
                    >
                      <td
                        data-testid={`schedule-step-day-${s.step_order}`}
                        className="px-5 py-2.5 font-mono text-xs text-slate-600"
                      >
                        G{s.study_day}
                      </td>
                      <td className="px-5 py-2.5 text-slate-800">
                        <div>
                          {s.step_name}
                          {flagged && (
                            <span className="ml-2 text-[10px] font-bold text-white bg-red-600 px-1.5 py-0.5 rounded">
                              ÇAKIŞMA
                            </span>
                          )}
                        </div>
                        {s.actual_reference_time && (
                          <div
                            data-testid={`schedule-step-ref-${s.step_order}`}
                            className="mt-0.5 text-[11px] font-mono text-indigo-800"
                          >
                            Gerçek Ref: {fmtDateTime(s.actual_reference_time)} (
                            {s.reference_deviation_minutes > 0
                              ? `+${s.reference_deviation_minutes}`
                              : s.reference_deviation_minutes}{' '}
                            dk)
                          </div>
                        )}
                      </td>
                      <td
                        data-testid={`schedule-step-planned-${s.step_order}`}
                        className="px-5 py-2.5 text-xs text-slate-600 whitespace-nowrap font-mono"
                      >
                        {fmtDateTime(s.planned_start)} – {fmtTime(s.planned_end)}
                      </td>
                      <td className="px-5 py-2.5 text-xs text-slate-600">{fmtMinutes(s.duration_minutes)}</td>
                      <td className="px-5 py-2.5 text-xs text-slate-700">
                        {s.assignees.length ? (
                          s.assignees.map((a) => `${a.full_name} (${ROLE_SHORT[a.role] || a.role})`).join(', ')
                        ) : (
                          <span className="text-red-600 font-medium">Atanmadı</span>
                        )}
                      </td>
                      <td className="px-5 py-2.5 text-xs">
                        {s.is_biological_fixed_time ? (
                          <span className="text-blue-700 font-medium">
                            Biyolojik ±{s.biological_tolerance_minutes} dk
                          </span>
                        ) : (
                          <span className="text-slate-400">Esnek</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* =====================================================================
          SEKME 2: HAFTALIK MASTER TAKVİM (PAZARTESİ - PAZAR GRİD)
         ===================================================================== */}
      {viewMode === 'weekly' && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Haftalık Master Operasyon Takvimi ({fmtWeekRangeTR(weekStart)})
                </h3>
                <p className="text-xs text-slate-500">
                  Tüm çalışmaların (Taslak ve Onaylı) Pazartesi–Pazar görev dağılımı ve sorumlu personelleri.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={calendarStudyFilter}
                  onChange={(e) => setCalendarStudyFilter(e.target.value)}
                  className="border border-slate-300 rounded-md px-2.5 py-1.5 text-xs bg-white font-medium text-slate-700"
                >
                  <option value="ALL">Tüm Çalışmalar ({calendarData.studies.length})</option>
                  {calendarData.studies.map((st) => (
                    <option key={st.study_id} value={st.study_code}>
                      {st.study_code} ({st.study_status === 'DRAFT' ? 'TASLAK' : 'ONAYLI'})
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  onClick={() => setWeekStart((w) => addDaysISO(w, -7))}
                  className="inline-flex items-center gap-1 border border-slate-300 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Önceki Hafta
                </button>
                <input
                  type="date"
                  value={weekStart}
                  onChange={(e) => setWeekStart(toMondayISO(e.target.value))}
                  className="border border-slate-300 rounded-md px-2.5 py-1 text-xs"
                />
                <button
                  type="button"
                  onClick={() => setWeekStart((w) => addDaysISO(w, 7))}
                  className="inline-flex items-center gap-1 border border-slate-300 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Sonraki Hafta <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {calendarData.active_weeks.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-[11px] font-semibold text-slate-500 mr-1">Görev Olan Haftalar:</span>
                {calendarData.active_weeks.map((wk) => {
                  const active = wk === toMondayISO(weekStart);
                  return (
                    <button
                      key={wk}
                      type="button"
                      onClick={() => setWeekStart(wk)}
                      className={`text-[11px] font-medium px-2.5 py-1 rounded-full border transition ${
                        active
                          ? 'bg-slate-900 text-white border-blue-700'
                          : 'bg-slate-50 text-slate-700 border-slate-300 hover:bg-blue-50 hover:border-blue-300'
                      }`}
                    >
                      {fmtWeekRangeTR(wk)}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-7 divide-y md:divide-y-0 md:divide-x divide-slate-200">
            {weekDays.map((wd) => {
              const daySteps = stepsByDay[wd.iso] || [];
              return (
                <div
                  key={wd.iso}
                  className={`min-h-[260px] flex flex-col ${wd.isWeekend ? 'bg-amber-50/30' : 'bg-white'}`}
                >
                  <div
                    className={`px-3 py-2.5 border-b border-slate-200 flex items-center justify-between ${
                      wd.isWeekend ? 'bg-amber-50/70' : 'bg-slate-50'
                    }`}
                  >
                    <div>
                      <p className={`text-xs font-bold ${wd.isWeekend ? 'text-amber-900' : 'text-slate-800'}`}>
                        {wd.dayName}
                      </p>
                      <p className="text-[11px] font-mono text-slate-500">{wd.iso}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setDailyDate(wd.iso);
                        setViewMode('daily');
                      }}
                      className="text-[10px] font-semibold px-2 py-0.5 rounded bg-white border border-slate-200 text-blue-700 hover:bg-blue-50"
                      title="Bu günün saatlik akışını aç"
                    >
                      {daySteps.length} görev
                    </button>
                  </div>

                  <div className="p-2.5 space-y-2 flex-1">
                    {daySteps.length === 0 ? (
                      <p className="text-[11px] text-slate-400 italic text-center py-8">Planlı görev yok</p>
                    ) : (
                      daySteps.map((s) => (
                        <div
                          key={s.id}
                          onClick={() => {
                            const found = calendarData.studies.find((st) => st.study_id === s.study_id);
                            if (found) {
                              setResult(found);
                              setViewMode('study');
                            }
                          }}
                          className={`cursor-pointer rounded-lg border p-2.5 text-xs space-y-1.5 shadow-xs transition hover:shadow ${
                            s.has_conflict
                              ? 'border-red-400 bg-red-50'
                              : s.study_status === 'DRAFT'
                                ? 'border-amber-300 bg-amber-50/50'
                                : 'border-emerald-300 bg-emerald-50/50'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-800">
                              {s.study_code}
                            </span>
                            <span className="text-[10px] font-semibold text-slate-600">
                              {fmtTime(s.planned_start)}–{fmtTime(s.planned_end)}
                            </span>
                          </div>
                          <p className="font-semibold text-slate-900 leading-snug flex items-start gap-1">
                            {s.is_biological_fixed_time && <Lock className="w-3 h-3 text-blue-700 shrink-0 mt-0.5" />}
                            <span>
                              G{s.study_day}: {s.step_name}
                            </span>
                          </p>
                          <p className="text-[11px] text-slate-600">
                            {s.assignee_names?.join(', ') || 'Atanmadı'} • {fmtMinutes(s.duration_minutes)}
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* =====================================================================
          SEKME 3: GÜNLÜK SAATLİK AKIŞ (08:00 - 18:00)
         ===================================================================== */}
      {viewMode === 'daily' && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <div className="p-4 border-b border-slate-200 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Günlük Saatlik Operasyon Akışı — {fmtShortDateTR(dailyDate)} ({dailyDate})
                </h3>
                <p className="text-xs text-slate-500">
                  08:00 – 18:00 mesai dilimlerinde yürütülen tüm GLP çalışma adımları, süreleri ve personel atamaları.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setDailyDate((d) => addDaysISO(d, -1))}
                  className="inline-flex items-center gap-1 border border-slate-300 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Önceki Gün
                </button>
                <input
                  type="date"
                  value={dailyDate}
                  onChange={(e) => setDailyDate(e.target.value)}
                  className="border border-slate-300 rounded-md px-2.5 py-1 text-xs"
                />
                <button
                  type="button"
                  onClick={() => setDailyDate((d) => addDaysISO(d, 1))}
                  className="inline-flex items-center gap-1 border border-slate-300 rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  Sonraki Gün <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {calendarData.active_dates.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-[11px] font-semibold text-slate-500 mr-1">Görev Olan Tarihlere Git:</span>
                {calendarData.active_dates.map((dt) => {
                  const active = dt === dailyDate;
                  return (
                    <button
                      key={dt}
                      type="button"
                      onClick={() => setDailyDate(dt)}
                      className={`text-[11px] font-medium px-2.5 py-1 rounded-full border transition ${
                        active
                          ? 'bg-slate-900 text-white border-blue-700'
                          : 'bg-slate-50 text-slate-700 border-slate-300 hover:bg-blue-50 hover:border-blue-300'
                      }`}
                    >
                      {fmtShortDateTR(dt)}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="divide-y divide-slate-100">
            {hourlySlots.map((slot) => (
              <div key={slot.hourLabel} className="grid grid-cols-[90px_1fr] items-stretch">
                <div className="px-4 py-3 bg-slate-50 border-r border-slate-200 font-mono text-xs font-semibold text-slate-600 flex items-center">
                  {slot.hourLabel}
                </div>
                <div className="p-2.5 flex flex-wrap gap-2 items-center min-h-[52px]">
                  {slot.steps.length === 0 ? (
                    <span className="text-[11px] text-slate-300 pl-2">—</span>
                  ) : (
                    slot.steps.map((s) => (
                      <div
                        key={`${slot.hourLabel}-${s.id}`}
                        onClick={() => {
                          const found = calendarData.studies.find((st) => st.study_id === s.study_id);
                          if (found) {
                            setResult(found);
                            setViewMode('study');
                          }
                        }}
                        className={`cursor-pointer rounded-lg border px-3 py-2 text-xs flex flex-wrap items-center gap-3 shadow-xs ${
                          s.has_conflict
                            ? 'border-red-400 bg-red-50 text-red-950'
                            : s.study_status === 'DRAFT'
                              ? 'border-amber-300 bg-amber-50 text-slate-900'
                              : 'border-emerald-300 bg-emerald-50 text-slate-900'
                        }`}
                      >
                        <span className="font-mono font-bold text-[11px] px-1.5 py-0.5 rounded bg-white border border-slate-200">
                          {s.study_code}
                        </span>
                        <span className="font-semibold flex items-center gap-1">
                          {s.is_biological_fixed_time && <Lock className="w-3.5 h-3.5 text-slate-500" />}
                          G{s.study_day}: {s.step_name}
                        </span>
                        <span className="text-slate-600">
                          {fmtTime(s.planned_start)}–{fmtTime(s.planned_end)} ({fmtMinutes(s.duration_minutes)})
                        </span>
                        <span className="font-medium text-blue-800">
                          👤 {s.assignee_names?.join(', ') || 'Atanmadı'}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
