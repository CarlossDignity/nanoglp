import AnimalOrder from '../components/AnimalOrder';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Check, FileDown, Loader2, Plus, Trash2, UploadCloud, X } from 'lucide-react';
import {
  getSamples,
  getSample,
  createSample,
  updateSample,
  planSample,
  autoScheduleAllSamples,
  importSamplesExcel,
  exportSamplesExcel,
  sampleWorkflowAction,
  downloadSampleStudyPlan,
  getSampleDocuments,
  uploadSampleDocuments,
  extractError,
  extractBlobError,
} from '../services/api';
import { useAuth } from '../state/AuthContext';
import { usePreferences } from '../state/PreferencesContext';

/* ------------------------------------------------------------------ */
/* Yardımcılar                                                         */
/* ------------------------------------------------------------------ */
const fmtD = (iso) => {
  if (!iso) return '—';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return d && m && y ? `${d}.${m}.${y}` : '—';
};

const STATUS_META = {
  EXPECTED: { label: 'Beklenen', dot: 'bg-amber-400' },
  PLANNED: { label: 'Planlanan', dot: 'bg-blue-500' },
  ONGOING: { label: 'Devam eden', dot: 'bg-emerald-500' },
  COMPLETED: { label: 'Biten', dot: 'bg-slate-400' },
  CANCELLED: { label: 'İptal', dot: 'bg-red-400' },
};
const STATUS_ORDER = ['ONGOING', 'PLANNED', 'EXPECTED', 'COMPLETED', 'CANCELLED'];

// Operational Study status is independent of sample status and document signatures.
const OPERATIONAL_STATUS_LABELS = new Map([
  ['DRAFT', 'Taslak — plan onayı bekleniyor'],
  ['APPROVED', 'Onaylı'],
  ['IN_PROGRESS', 'Devam ediyor'],
  ['REPORTING', 'Raporlama'],
  ['COMPLETED', 'Tamamlandı'],
  ['CANCELLED', 'İptal edildi'],
]);

function OperationalStudyStatus({ study }) {
  const label = !study?.id
    ? 'Bağlı çalışma bulunmuyor'
    : OPERATIONAL_STATUS_LABELS.get(study.status) || `Bilinmeyen durum${study.status ? ` (${study.status})` : ''}`;
  return (
    <div data-testid="operational-study-status" className="mt-2 text-xs text-slate-700">
      <p>Operasyonel plan / çalışma durumu: <strong>{label}</strong></p>
      {study?.id && (
        <p className="mt-0.5 text-[11px] text-slate-500">
          {study.has_schedule === true ? 'Takvim oluşturulmuş' : study.has_schedule === false ? 'Takvim oluşturulmamış' : 'Takvim bilgisi bulunmuyor'}
        </p>
      )}
    </div>
  );
}

const Dot = ({ cls }) => <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${cls}`} />;

const inputCls =
  'w-full border border-slate-300 rounded px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-600 disabled:bg-slate-50';

const blankToNull = (v) => (v === '' || v === undefined ? null : v);

/* ------------------------------------------------------------------ */
/* Çekmece bileşenleri                                                  */
/* ------------------------------------------------------------------ */

const DOC_ACCEPT = ['pdf', 'png', 'jpg', 'jpeg', 'xlsx', 'txt', 'csv'];

/** FAZ 8.2 — Çekmeceden TIIS / CoA / FM.083 PDF yükleme ve otomatik doldurma alanı. */
function DocUpload({ busy, onFiles, compact = false, result, docs, canApplyDiff, onApplyDiff }) {
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);
  const pick = (list) => {
    const files = Array.from(list || []);
    if (files.length) onFiles(files);
  };
  return (
    <div className={compact ? 'mb-4' : 'px-6 py-4 border-b border-slate-200 bg-slate-50/60'}>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".pdf,.png,.jpg,.jpeg,.xlsx,.txt,.csv"
        className="hidden"
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = '';
        }}
      />
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files);
        }}
        className={`border border-dashed rounded-lg px-4 ${compact ? 'py-2.5' : 'py-3.5'} flex flex-wrap items-center justify-between gap-3 ${
          drag ? 'border-slate-900 bg-white' : 'border-slate-300 bg-white'
        }`}
      >
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-900">
            {compact ? 'Belgeden Doldur (TIIS / CoA / FM.083 PDF)' : 'Çalışma Belgelerini (TIIS / CoA / FM.083 PDF) Yükle & Otomatik Doldur'}
          </p>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Lot / Seri No, SKT, Üretim Tarihi, Saklama Koşulu, Sponsor, Test Maddesi ve Polar / Apolar çözücüler PDF'ten okunarak
            çalışma kaydına yazılır. Dosyaları buraya sürükleyin veya seçin.
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-1.5 border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-50 rounded px-2.5 py-1.5 text-xs font-medium text-slate-700 whitespace-nowrap"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5 text-slate-500" />}
          {busy ? 'Vision OCR okuyor…' : 'PDF Seç'}
        </button>
      </div>

      {!compact && docs?.length > 0 && !result && (
        <ul className="mt-2.5 space-y-1">
          {docs.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-x-2 text-[11px] text-slate-600">
              <span className={`w-1.5 h-1.5 rounded-full ${d.status === 'FAILED' ? 'bg-red-500' : d.status === 'NEEDS_REVIEW' ? 'bg-amber-400' : 'bg-emerald-500'}`} />
              <span className="font-mono text-slate-800">{d.filename}</span>
              <span>{d.category_label || '—'}</span>
            </li>
          ))}
        </ul>
      )}

      {result && (
        <div className="mt-3 border border-slate-200 bg-white rounded-lg text-xs divide-y divide-slate-100">
          {result.documents.map((d) => (
            <div key={`${d.filename}-${d.id || 'x'}`} className="px-3 py-2 flex flex-wrap items-center gap-x-2">
              <span className={`w-1.5 h-1.5 rounded-full ${d.ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
              <span className="font-mono text-slate-900">{d.filename}</span>
              {d.ok ? <span className="text-slate-500">{d.category_label || 'GLP belgesi'}</span> : <span className="text-red-700">{d.error}</span>}
            </div>
          ))}
          {result.applied.length > 0 && (
            <div className="px-3 py-2">
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500 mb-1">Otomatik doldurulan alanlar</p>
              <ul className="space-y-0.5">
                {result.applied.map((a) => (
                  <li key={a.field} className="flex flex-wrap gap-x-2 text-slate-700">
                    <span className="text-slate-500">{a.label}:</span>
                    <span className="font-mono text-slate-900">{String(a.value)}</span>
                    <span className="text-[11px] text-slate-400">← {a.source_filename}</span>
                  </li>
                ))}
              </ul>
              {result.propagated_to?.length > 0 && (
                <p className="mt-1 text-[11px] text-slate-500">
                  Ortak numune: {result.propagated_to.join(', ')} kayıtlarının boş alanlarına da yayıldı.
                </p>
              )}
            </div>
          )}
          {result.applied.length === 0 && result.differences.length === 0 && result.ok_count > 0 && (
            <p className="px-3 py-2 text-slate-500">Belgelerden doldurulacak yeni bir alan bulunamadı (alanlar zaten dolu veya belgede yok).</p>
          )}
          {result.differences.length > 0 && (
            <div className="px-3 py-2">
              <p className="text-[11px] font-medium uppercase tracking-wider text-amber-700 mb-1">Kayıt ile belge farklı — ezilmedi</p>
              <ul className="space-y-1">
                {result.differences.map((d) => (
                  <li key={d.field} className="flex flex-wrap items-center gap-x-2 text-slate-700">
                    <span className="text-slate-500">{d.label}:</span>
                    <span className="font-mono">{String(d.current)}</span>
                    <span className="text-slate-400">→ belge:</span>
                    <span className="font-mono text-slate-900">{String(d.document_value)}</span>
                    {canApplyDiff(d.field) && (
                      <button type="button" onClick={() => onApplyDiff(d)} className="text-blue-700 hover:underline">
                        Belgedeki değeri uygula
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, hint, children, actions }) {
  const { t } = usePreferences();
  return (
    <section className="border-b border-slate-200 px-6 py-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{t(title)}</h4>
          {hint && <p className="text-[11px] text-slate-400 mt-0.5">{t(hint)}</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">{actions}</div>
      </div>
      {children}
    </section>
  );
}

function Field({ label, value, mono = false, wide = false }) {
  const { t } = usePreferences();
  return (
    <div className={wide ? 'col-span-2' : ''}>
      <dt className="text-[11px] text-slate-500">{t(label)}</dt>
      <dd className={`text-xs text-slate-900 mt-0.5 break-words ${mono ? 'font-mono tabular-nums' : ''}`}>
        {value === null || value === undefined || value === '' ? <span className="text-slate-300">—</span> : typeof value === 'string' ? t(value) : value}
      </dd>
    </div>
  );
}

function FormField({ label, children, wide = false }) {
  const { t } = usePreferences();
  return (
    <label className={`block ${wide ? 'col-span-2' : ''}`}>
      <span className="block text-[11px] text-slate-500 mb-1">{t(label)}</span>
      {children}
    </label>
  );
}

const LinkBtn = ({ onClick, children, disabled, strong }) => {
  const { t } = usePreferences();
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`text-xs disabled:opacity-40 ${strong ? 'font-semibold text-blue-700 hover:text-blue-900' : 'text-slate-600 hover:text-slate-900'}`}
    >
      {typeof children === 'string' ? t(children) : children}
    </button>
  );
};

/* ------------------------------------------------------------------ */
/* Sayfa                                                                */
/* ------------------------------------------------------------------ */
export default function SampleTracking() {
  const navigate = useNavigate();
  const location = useLocation();
  const { allowedMenus } = useAuth();
  const { t } = usePreferences();
  const canOpenPlanning = allowedMenus.includes('planning');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [bulkResult, setBulkResult] = useState(null);
  const [busy, setBusy] = useState({});
  const [filter, setFilter] = useState({ status: 'ALL', glp: 'ALL', q: '', sd: 'ALL', overdue: false, subPhase: 'ALL' });

  const [drawerId, setDrawerId] = useState(null); // number | 'new' | null
  const [detail, setDetail] = useState(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [editing, setEditing] = useState(null); // 'sales' | 'trm' | 'plan' | null
  const [form, setForm] = useState({});
  const [applyRelated, setApplyRelated] = useState(true);
  const [saving, setSaving] = useState(false);
  const [drawerError, setDrawerError] = useState(null);
  const [lastPlan, setLastPlan] = useState(null);
  const [docBusy, setDocBusy] = useState(false);
  const [docResult, setDocResult] = useState(null);
  const [docList, setDocList] = useState([]);
  const fileRef = useRef(null);

  const perms = data?.permissions || {};

  const load = useCallback(async () => {
    try {
      const res = await getSamples();
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(extractError(err, 'Numune ve çalışma kayıtları alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setBusyKey = (k, v) => setBusy((b) => ({ ...b, [k]: v }));

  /* ---------------- Liste hesapları ---------------- */
  const items = data?.items || [];
  const summary = data?.summary;

  const filtered = useMemo(() => {
    const q = filter.q.trim().toLowerCase();
    return items
      .filter((i) => (filter.glp === 'ALL' ? true : (i.glp_type || 'GLP') === filter.glp))
      .filter((i) => (filter.status === 'ALL' ? true : i.status === filter.status))
      .filter((i) => {
        if (filter.subPhase === 'IN_EXPERIMENT') return i.status === 'ONGOING' && i.ongoing_phase === 'IN_EXPERIMENT';
        if (filter.subPhase === 'IN_REPORTING_QA') return i.status === 'ONGOING' && i.ongoing_phase === 'IN_REPORTING_QA';
        if (filter.subPhase === 'OVERDUE_DRAFT') return i.is_draft_report_overdue === true;
        return true;
      })
      .filter((i) => (filter.sd === 'ALL' ? true : (i.study_director_name || 'Atanmamış') === filter.sd))
      .filter((i) => (filter.overdue ? i.is_overdue : true))
      .filter((i) =>
        !q
          ? true
          : [
              i.study_code,
              i.requested_analysis,
              i.test_item_name,
              i.sponsor_name,
              i.billing_company,
              i.test_item_code,
              i.study_director_name,
              i.sales_manager,
              i.quote_no,
              i.animal_consumable_status,
              i.payment_status,
            ]
              .filter(Boolean)
              .some((s) => String(s).toLowerCase().includes(q))
      )
      .sort((a, b) => {
        if ((a.glp_type || 'GLP') !== (b.glp_type || 'GLP')) {
          return (a.glp_type || 'GLP') === 'GLP' ? -1 : 1;
        }
        if (a.serial_no != null && b.serial_no != null && a.serial_no !== b.serial_no) {
          return a.serial_no - b.serial_no;
        }
        return STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || b.study_code.localeCompare(a.study_code);
      });
  }, [items, filter]);

  const glpFilteredItems = useMemo(
    () => items.filter((i) => (filter.glp === 'ALL' ? true : (i.glp_type || 'GLP') === filter.glp)),
    [items, filter.glp]
  );
  const countBy = (s) => glpFilteredItems.filter((i) => i.status === s).length;
  const countByGlp = (g) => items.filter((i) => (i.glp_type || 'GLP') === g).length;

  useEffect(() => {
    const code = location.state?.highlightStudyCode;
    if (!code || !items.length) return;
    const match = items.find((i) => i.study_code === code);
    if (match) {
      setFilter((f) => ({ ...f, q: code }));
      openDrawer(match.id);
    }
  }, [location.state?.highlightStudyCode, items.length]);

  /* ---------------- Çekmece ---------------- */
  const openDrawer = async (id) => {
    setDrawerId(id);
    setEditing(null);
    setDrawerError(null);
    setLastPlan(null);
    setDocResult(null);
    setDocList([]);
    if (id !== 'new') {
      getSampleDocuments(id).then((r) => setDocList(r.data?.documents || [])).catch(() => {});
    }
    if (id === 'new') {
      setDetail({ contacts: [], related: [], workflow: [], dates: {}, status: 'EXPECTED' });
      setEditing('sales');
      setForm({
        study_code: summary?.next_glp_code || 'GLP2026-083',
        glp_type: 'GLP',
        contacts: [{ name: '', email: '' }],
      });
      return;
    }
    setDrawerLoading(true);
    try {
      const res = await getSample(id);
      setDetail(res.data);
    } catch (err) {
      setDrawerError(extractError(err, 'Detay alınamadı.'));
    } finally {
      setDrawerLoading(false);
    }
  };

  const closeDrawer = () => {
    setDrawerId(null);
    setDetail(null);
    setEditing(null);
  };

  const refreshAll = async (id = drawerId) => {
    await load();
    if (id && id !== 'new') {
      try {
        const res = await getSample(id);
        setDetail(res.data);
      } catch {
        /* yut */
      }
    }
  };

  const startEdit = (section) => {
    const d = detail || {};
    setDrawerError(null);
    setEditing(section);
    setApplyRelated(true);
    if (section === 'sales') {
      setForm({
        requested_analysis: d.requested_analysis || '',
        test_item_name: d.test_item_name || '',
        billing_company: d.billing_company || '',
        sponsor_name: d.sponsor_name || '',
        contacts: (d.contacts?.length ? d.contacts : [{ name: '', email: '' }]).map((c) => ({ ...c })),
        quote_no: d.quote_no || '',
        sales_manager: d.sales_manager || '',
        study_agreement_date: d.study_agreement_date || '',
        payment_status: d.payment_status || '',
        expected_arrival_date: d.expected_arrival_date || '',
      });
    } else if (section === 'trm') {
      setForm({
        sample_status: d.sample_status || 'Bekleniyor',
        test_item_code: d.test_item_code || '',
        istanbul_arrival_date: d.istanbul_arrival_date || '',
        lab_arrival_date: d.lab_arrival_date || '',
        received_quantity: d.received_quantity || '',
        animal_consumable_status: d.animal_consumable_status || '',
        animal_procurement_date: d.animal_procurement_date || '',
        lot_no: d.lot_no || '',
        expiry_date: d.expiry_date || '',
        storage_condition: d.storage_condition || '',
        sample_note: d.sample_note || '',
        manufacture_date: d.manufacture_date || '',
        extraction_polar_solvent: d.extraction_polar_solvent || '',
        extraction_non_polar_solvent: d.extraction_non_polar_solvent || '',
      });
    } else if (section === 'plan') {
      setForm({ template_code: d.template_code || '', study_director_name: d.study_director_name || '' });
    }
  };

  const saveEdit = async () => {
    setSaving(true);
    setDrawerError(null);
    try {
      let payload;
      if (editing === 'sales') {
        payload = {
          requested_analysis: form.requested_analysis,
          test_item_name: form.test_item_name,
          billing_company: form.billing_company,
          sponsor_name: form.sponsor_name,
          contacts: (form.contacts || []).filter((c) => (c.name || '').trim() || (c.email || '').trim()),
          quote_no: form.quote_no,
          sales_manager: form.sales_manager,
          study_agreement_date: blankToNull(form.study_agreement_date),
          payment_status: blankToNull(form.payment_status),
          expected_arrival_date: blankToNull(form.expected_arrival_date),
        };
      } else if (editing === 'trm') {
        payload = {
          sample_status: form.sample_status,
          test_item_code: form.test_item_code,
          istanbul_arrival_date: blankToNull(form.istanbul_arrival_date),
          lab_arrival_date: blankToNull(form.lab_arrival_date),
          received_quantity: form.received_quantity,
          animal_consumable_status: blankToNull(form.animal_consumable_status),
          animal_procurement_date: blankToNull(form.animal_procurement_date),
          lot_no: form.lot_no,
          expiry_date: form.expiry_date,
          storage_condition: form.storage_condition,
          sample_note: form.sample_note,
          manufacture_date: form.manufacture_date,
          extraction_polar_solvent: form.extraction_polar_solvent,
          extraction_non_polar_solvent: form.extraction_non_polar_solvent,
          apply_to_related: Boolean(applyRelated && detail?.related?.length),
        };
      } else {
        payload = { template_code: blankToNull(form.template_code), study_director_name: form.study_director_name };
      }

      if (drawerId === 'new') {
        const code = (form.study_code || '').trim();
        if (!code) {
          setDrawerError('Çalışma kodu (GLP No) zorunludur.');
          setSaving(false);
          return;
        }
        const res = await createSample({ ...payload, study_code: code });
        setNotice(`${res.data.study_code} kaydı oluşturuldu.`);
        await load();
        setDrawerId(res.data.id);
        setDetail(res.data);
        setEditing(null);
      } else {
        const res = await updateSample(drawerId, payload);
        const prop = res.data.propagated_to || [];
        setNotice(
          prop.length
            ? `${res.data.study_code} güncellendi; ortak numuneyi kullanan ${prop.join(', ')} kayıtları da güncellendi.`
            : `${res.data.study_code} güncellendi.`
        );
        setDetail(res.data);
        setEditing(null);
        await load();
      }
    } catch (err) {
      setDrawerError(extractError(err, 'Kayıt kaydedilemedi.'));
    } finally {
      setSaving(false);
    }
  };

  const handleDocFiles = async (files) => {
    const bad = files.filter((f) => !DOC_ACCEPT.includes((f.name.split('.').pop() || '').toLowerCase()));
    if (bad.length) {
      setDrawerError(`Desteklenmeyen dosya türü: ${bad.map((b) => b.name).join(', ')} (PDF, PNG, JPG, XLSX, TXT, CSV).`);
      return;
    }
    setDocBusy(true);
    setDrawerError(null);
    setDocResult(null);
    try {
      const res = await uploadSampleDocuments(drawerId, files);
      setDocResult(res.data);
      setDetail(res.data.sample);
      setNotice(
        `${res.data.sample.study_code}: ${res.data.ok_count} belge okundu, ${res.data.applied.length} alan otomatik dolduruldu` +
          (res.data.failed_count ? `, ${res.data.failed_count} belge okunamadı.` : '.')
      );
      const lst = await getSampleDocuments(drawerId);
      setDocList(lst.data?.documents || []);
      await load();
    } catch (err) {
      setDrawerError(extractError(err, 'Belgeler yüklenemedi veya okunamadı.'));
    } finally {
      setDocBusy(false);
    }
  };

  const SALES_ATTRS = ['sponsor_name', 'test_item_name'];
  const TRM_ATTRS = ['lot_no', 'expiry_date', 'manufacture_date', 'storage_condition', 'extraction_polar_solvent', 'extraction_non_polar_solvent'];
  const canApplyDiff = (field) =>
    (SALES_ATTRS.includes(field) && perms.can_edit_sales) || (TRM_ATTRS.includes(field) && perms.can_edit_trm);
  const applyDiff = async (d) => {
    try {
      const res = await updateSample(drawerId, { [d.field]: d.document_value });
      setDetail(res.data);
      setDocResult((r) => (r ? { ...r, differences: r.differences.filter((x) => x.field !== d.field) } : r));
      await load();
    } catch (err) {
      setDrawerError(extractError(err, 'Alan güncellenemedi.'));
    }
  };

  const doWorkflow = async (step, body) => {
    setBusyKey(`wf-${step}`, true);
    setDrawerError(null);
    try {
      const res = await sampleWorkflowAction(drawerId, step, body);
      setDetail(res.data);
      await load();
    } catch (err) {
      setDrawerError(extractError(err, 'İş akışı adımı güncellenemedi.'));
    } finally {
      setBusyKey(`wf-${step}`, false);
    }
  };

  /* ---------------- Satır aksiyonları ---------------- */
  const handleWorkflowOrPlan = async (row) => {
    setError(null);
    setNotice(null);
    if (row.scheduled && row.study?.id) {
      if (canOpenPlanning) navigate('/planning', { state: { selectedStudyId: row.study.id } });
      else openDrawer(row.id);
      return;
    }
    if (!perms.can_plan) {
      openDrawer(row.id);
      setNotice('Bu çalışmanın takvimi henüz oluşturulmadı; yetkili bir Çalışma Yöneticisi / Planlama Koordinatörü planlamalıdır.');
      return;
    }
    setBusyKey(`plan-${row.id}`, true);
    try {
      const res = await planSample(row.id);
      const p = res.data.plan;
      setLastPlan(p);
      await load();
      if (canOpenPlanning) {
        navigate('/planning', { state: { selectedStudyId: p.study_id } });
      } else {
        await openDrawer(row.id);
        setLastPlan(p);
      }
    } catch (err) {
      setError(extractError(err, 'Otomatik takvim oluşturulamadı.'));
    } finally {
      setBusyKey(`plan-${row.id}`, false);
    }
  };

  const handleDocx = async (row) => {
    setError(null);
    setBusyKey(`docx-${row.id}`, true);
    try {
      await downloadSampleStudyPlan(row.id, row.study_code);
      await load();
    } catch (err) {
      setError(await extractBlobError(err, 'Study Plan indirilemedi.'));
    } finally {
      setBusyKey(`docx-${row.id}`, false);
    }
  };

  const handleAutoAll = async () => {
    setError(null);
    setNotice(null);
    setBulkResult(null);
    setBusyKey('all', true);
    try {
      const res = await autoScheduleAllSamples();
      setData(res.data.data);
      setBulkResult(res.data);
      setNotice(
        res.data.scheduled === 0 && res.data.failed === 0
          ? 'Takvimi çıkarılmamış planlanan çalışma bulunmuyor.'
          : `${res.data.scheduled} çalışma otomatik takvimlendi${res.data.failed ? `, ${res.data.failed} çalışma takvimlenemedi` : ''}.`
      );
    } catch (err) {
      setError(extractError(err, 'Toplu otomatik takvim oluşturulamadı.'));
    } finally {
      setBusyKey('all', false);
    }
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError(null);
    setNotice(null);
    setImportResult(null);
    setBusyKey('import', true);
    try {
      const res = await importSamplesExcel(file);
      setData(res.data.data);
      const r = res.data;
      setImportResult(r);
      setNotice(
        `${file.name}: ${r.created} yeni, ${r.updated} değişen, ${r.unchanged ?? 0} değişmeyen, ${r.failed ?? r.errors?.length ?? 0} hatalı, ${r.review_required ?? 0} inceleme gerektiren kayıt.` +
          (r.errors?.length ? ` Uyarılar: ${r.errors.slice(0, 3).join(' • ')}${r.errors.length > 3 ? ' …' : ''}` : '')
      );
    } catch (err) {
      setError(extractError(err, 'Dosya içe aktarılamadı.'));
    } finally {
      setBusyKey('import', false);
    }
  };

  const handleExportExcel = async () => {
    setError(null);
    setBusyKey('export', true);
    try {
      await exportSamplesExcel();
      setNotice(t('93 çalışmanın güncel takip listesi Excel (.xlsx) olarak indirildi.', 'Current tracking list of 93 studies downloaded as Excel (.xlsx).'));
    } catch (err) {
      setError(await extractBlobError(err, t('Excel dosyası indirilemedi.', 'Excel file could not be downloaded.')));
    } finally {
      setBusyKey('export', false);
    }
  };

  /* ---------------- Render ---------------- */
  const ghostBtn =
    'inline-flex items-center gap-1.5 border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:hover:bg-white rounded px-2.5 py-1.5 text-xs font-medium text-slate-700 whitespace-nowrap';
  const solidBtn =
    'inline-flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 disabled:opacity-40 rounded px-3 py-1.5 text-xs font-medium text-white whitespace-nowrap';

  const sdList = summary?.by_study_director || [];

  return (
    <div className="space-y-5">
      {/* Başlık + üst aksiyonlar */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">Numune &amp; Çalışma Takip</h2>
          <p className="text-sm text-slate-500">
            Numune kabulünden final rapora kadar tüm GLP çalışmaları — tek satırda durum, takvim ve 11 adımlı iş akışı.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={handleImport} />
          <button type="button" className={ghostBtn} disabled={busy.export} onClick={handleExportExcel}>
            {busy.export ? <Loader2 className="w-3 h-3 animate-spin" /> : <FileDown className="w-3.5 h-3.5 text-emerald-600" />}
            📥 Excel (.xlsx) İndir
          </button>
          {perms.can_import && (
            <button type="button" className={ghostBtn} disabled={busy.import} onClick={() => fileRef.current?.click()}>
              {busy.import && <Loader2 className="w-3 h-3 animate-spin" />}
              Excel (.xlsx / .csv) İçe Aktar
            </button>
          )}
          {perms.can_plan && (
            <button type="button" className={solidBtn} disabled={busy.all} onClick={handleAutoAll}>
              {busy.all && <Loader2 className="w-3 h-3 animate-spin" />}
              Tüm Planlananları Otomatik Takvimle
            </button>
          )}
          {perms.can_import && (
            <button type="button" className={ghostBtn} onClick={() => openDrawer('new')}>
              <Plus className="w-3 h-3" /> Yeni Kayıt
            </button>
          )}
        </div>
      </div>

      {error && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 rounded">{error}</div>}
      {notice && (
        <div className="border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 rounded flex items-start justify-between gap-3">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-slate-400 hover:text-slate-700" aria-label="Kapat">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      {importResult && (
        <details className="border rounded p-3 text-xs bg-white">
          <summary>Excel aktarım farkları ve inceleme notları</summary>
          <div className="overflow-auto max-h-96">
            <table className="w-full text-left mt-2">
              <thead><tr><th>Çalışma</th><th>Alan / kayıt</th><th>Eski değer</th><th>Excel değeri</th><th>Sonuç</th></tr></thead>
              <tbody>{[...(importResult.changes || []), ...(importResult.reviews || [])].map((row, i) => (
                <tr key={i} className="border-t">
                  <td>{row.study_code}</td><td>{row.field} ({row.target})</td>
                  <td className="break-all">{JSON.stringify(row.old_value)}</td>
                  <td className="break-all">{JSON.stringify(row.excel_value)}</td>
                  <td>{row.reason || 'Güncellendi'}</td>
                </tr>
              ))}</tbody>
            </table>
            {(importResult.scheduling || []).map(row => <p key={row.study_code}>{row.study_code}: {row.reason}</p>)}
            {(importResult.errors || []).map((error, i) => <p key={i} className="text-red-700">{error}</p>)}
          </div>
        </details>
      )}
      {bulkResult?.results?.length > 0 && (
        <div className="border border-slate-200 bg-white rounded text-xs divide-y divide-slate-100">
          {bulkResult.results.map((r) => (
            <div key={r.study_code} className="px-3 py-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono font-semibold text-slate-900">{r.study_code}</span>
              {r.ok ? (
                <>
                  <span className="font-mono tabular-nums text-slate-600">
                    {fmtD(r.start)} → {fmtD(r.end)}
                  </span>
                  <span className="text-slate-500">
                    {r.critical_conflicts ? `${r.critical_conflicts} kritik` : '0 kritik'} · {r.warning_conflicts || 0} uyarı
                  </span>
                  {r.auto_schedule_notice?.text && <span className="text-amber-800">{r.auto_schedule_notice.text}</span>}
                </>
              ) : (
                <span className="text-red-700">{r.error}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Özet şeridi */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] border border-slate-200 bg-white rounded-lg overflow-hidden">
        <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-slate-200">
          {[
            { key: 'expected', label: 'Beklenen Numune', dot: STATUS_META.EXPECTED.dot, sub: 'Numune henüz gelmedi' },
            {
              key: 'planned',
              label: 'Planlanan Çalışma',
              dot: STATUS_META.PLANNED.dot,
              sub: `Otomatik planlanacak${summary?.planned_unscheduled ? ` · ${summary.planned_unscheduled} takvimsiz` : ''}`,
            },
            {
              key: 'ongoing',
              label: 'Devam Eden Çalışma',
              dot: STATUS_META.ONGOING.dot,
              sub: summary
                ? t(
                    `${summary.ongoing_in_experiment ?? 11} Sahada Deneyde · ${summary.ongoing_in_reporting ?? 22} Rapor / QA Aşamasında`,
                    `${summary.ongoing_in_experiment ?? 11} In Experiment · ${summary.ongoing_in_reporting ?? 22} In Reporting / QA`
                  )
                : 'Test / raporlama sürüyor',
            },
            { key: 'overdue', label: 'Gecikmiş İş', dot: 'bg-red-500', sub: 'Numune veya rapor süresi geçti', alert: true },
          ].map((cardItem) => (
            <button
              key={cardItem.key}
              type="button"
              onClick={() =>
                cardItem.key === 'overdue'
                  ? setFilter((f) => ({ ...f, status: 'ALL', subPhase: 'ALL', overdue: !f.overdue }))
                  : setFilter((f) => ({
                      ...f,
                      overdue: false,
                      subPhase: 'ALL',
                      status: f.status === cardItem.key.toUpperCase() ? 'ALL' : cardItem.key.toUpperCase(),
                    }))
              }
              className="text-left px-5 py-3.5 hover:bg-slate-50"
            >
              <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">
                <Dot cls={cardItem.dot} /> {cardItem.label}
              </span>
              <span className={`block mt-1 text-2xl font-semibold tabular-nums ${cardItem.alert && summary?.overdue ? 'text-red-700' : 'text-slate-900'}`}>
                {summary ? summary[cardItem.key] : '—'}
              </span>
              <span className="block text-[11px] text-slate-500 font-medium mt-0.5">{cardItem.sub}</span>
            </button>
          ))}
        </div>
        <div className="border-t lg:border-t-0 lg:border-l border-slate-200 px-5 py-3.5 min-w-[270px]">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">Çalışma Yöneticisi Bazında Açık Çalışmalar</p>
          <ul className="mt-1.5 space-y-0.5">
            {sdList.map((s) => (
              <li key={s.name}>
                <button
                  type="button"
                  onClick={() => setFilter((f) => ({ ...f, sd: f.sd === s.name ? 'ALL' : s.name }))}
                  className={`w-full flex items-center justify-between gap-6 text-xs py-0.5 ${
                    filter.sd === s.name ? 'text-blue-700 font-semibold' : 'text-slate-700 hover:text-slate-900'
                  }`}
                >
                  <span className={s.name === 'Atanmamış' ? 'text-slate-500 italic' : ''}>{s.name}</span>
                  <span className="font-mono tabular-nums">{s.open_count}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Filtre çubuğu */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <input
          type="search"
          value={filter.q}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })}
          placeholder="GLP no, test maddesi, sponsor, TI kodu ara…"
          className="w-72 border border-slate-300 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-600"
        />
        <div className="inline-flex items-center border border-slate-200 bg-white rounded p-0.5 text-xs">
          {[
            { key: 'ALL', label: 'Tümü', n: items.length },
            { key: 'GLP', label: 'GLP', n: countByGlp('GLP') },
            { key: 'NON-GLP', label: 'Non-GLP', n: countByGlp('NON-GLP') },
          ].map((g) => (
            <button
              key={g.key}
              type="button"
              onClick={() => setFilter({ ...filter, glp: g.key })}
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
                filter.glp === g.key ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {g.label}
              <span className={`font-mono tabular-nums ${filter.glp === g.key ? 'text-slate-300' : 'text-slate-400'}`}>{g.n}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {[{ key: 'ALL', label: 'Tüm Durumlar', n: glpFilteredItems.length }, ...STATUS_ORDER.map((s) => ({ key: s, label: STATUS_META[s].label, n: countBy(s) }))].map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => setFilter({ ...filter, status: c.key, subPhase: 'ALL' })}
              className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs ${
                filter.status === c.key && filter.subPhase === 'ALL' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {c.key !== 'ALL' && <Dot cls={STATUS_META[c.key].dot} />}
              {c.label}
              <span className={`font-mono tabular-nums ${filter.status === c.key && filter.subPhase === 'ALL' ? 'text-slate-300' : 'text-slate-400'}`}>{c.n}</span>
            </button>
          ))}
        </div>

        {/* FAZ 9.3: Sahada Deneyde (11) · Rapor / QA Aşamasında (22) · Taslak Raporu Geciken (17) hızlı alt filtre hapları */}
        <div className="flex flex-wrap items-center gap-1.5 border-l border-slate-200 pl-3">
          {[
            {
              key: 'IN_EXPERIMENT',
              label: t('Sahada Deneyde', 'In Experiment'),
              count: summary?.ongoing_in_experiment ?? 11,
              activeCls: 'bg-emerald-600 text-white border-emerald-600',
              idleCls: 'border-emerald-200 bg-emerald-50/70 text-emerald-800 hover:bg-emerald-100',
            },
            {
              key: 'IN_REPORTING_QA',
              label: t('Rapor / QA Aşamasında', 'In Reporting / QA'),
              count: summary?.ongoing_in_reporting ?? 22,
              activeCls: 'bg-blue-600 text-white border-blue-600',
              idleCls: 'border-blue-200 bg-blue-50/70 text-blue-800 hover:bg-blue-100',
            },
            {
              key: 'OVERDUE_DRAFT',
              label: t('Taslak Raporu Geciken', 'Overdue Draft Report'),
              count: summary?.ongoing_overdue_draft ?? 17,
              activeCls: 'bg-red-600 text-white border-red-600',
              idleCls: 'border-red-200 bg-red-50/70 text-red-800 hover:bg-red-100',
            },
          ].map((p) => {
            const active = filter.subPhase === p.key;
            return (
              <button
                key={p.key}
                type="button"
                onClick={() =>
                  setFilter((f) => ({
                    ...f,
                    status: active ? 'ALL' : 'ONGOING',
                    overdue: false,
                    subPhase: active ? 'ALL' : p.key,
                  }))
                }
                className={`inline-flex items-center gap-1.5 border rounded-full px-2.5 py-0.5 text-[11px] font-medium transition ${
                  active ? p.activeCls : p.idleCls
                }`}
              >
                <span>{p.label}</span>
                <span className="font-mono font-semibold tabular-nums">({p.count})</span>
              </button>
            );
          })}
        </div>

        {(filter.sd !== 'ALL' || filter.overdue || filter.subPhase !== 'ALL') && (
          <button
            type="button"
            onClick={() => setFilter({ ...filter, sd: 'ALL', overdue: false, subPhase: 'ALL' })}
            className="text-xs text-blue-700 hover:underline"
          >
            {filter.sd !== 'ALL' ? `ÇY: ${filter.sd}` : ''}
            {filter.overdue ? ' · Gecikmiş' : ''}
            {filter.subPhase !== 'ALL' ? ` · ${filter.subPhase}` : ''} — filtreyi temizle
          </button>
        )}
      </div>

      {/* Tablo */}
      <div className="border border-slate-200 bg-white rounded-lg overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="border-b border-slate-200 text-[11px] uppercase tracking-wider text-slate-500 bg-slate-50/60">
            <tr>
              <th className="text-left px-4 py-2.5 font-medium">Çalışma</th>
              <th className="text-left px-3 py-2.5 font-medium">Test maddesi / Sponsor</th>
              <th className="text-left px-3 py-2.5 font-medium">Numune</th>
              <th className="text-left px-3 py-2.5 font-medium">Çalışma Yöneticisi</th>
              <th className="text-left px-3 py-2.5 font-medium">Takvim</th>
              <th className="text-left px-3 py-2.5 font-medium">Durum</th>
              <th className="text-left px-3 py-2.5 font-medium">İş akışı</th>
              <th className="px-4 py-2.5 text-right font-medium">Aksiyonlar</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-slate-400">
                  Yükleniyor…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-slate-400">
                  Filtreye uyan numune / çalışma kaydı yok.
                </td>
              </tr>
            ) : (
              filtered.map((r) => {
                const sm = STATUS_META[r.status];
                const prog = r.workflow_progress || { done: r.progress, total: 11 };
                return (
                  <tr key={r.id} onClick={() => openDrawer(r.id)} className="hover:bg-slate-50/80 cursor-pointer">
                    <td className="px-4 py-2.5 align-top">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {r.serial_no != null && (
                          <span className="font-mono text-[10px] text-slate-400 tabular-nums">#{r.serial_no}</span>
                        )}
                        <span className="font-mono text-[12px] font-semibold text-slate-900">{r.study_code}</span>
                        {(r.glp_type || 'GLP') === 'NON-GLP' && (
                          <span className="border border-slate-300 bg-slate-50 rounded px-1 py-0.5 text-[10px] font-mono text-slate-600">
                            NON-GLP
                          </span>
                        )}
                      </div>
                      <p className="text-slate-500 mt-0.5 max-w-[230px] truncate" title={r.requested_analysis}>
                        {r.requested_analysis || '—'}
                      </p>
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <p className="text-slate-900">{r.test_item_name || '—'}</p>
                      <p className="text-slate-500 mt-0.5">{r.sponsor_name || '—'}</p>
                    </td>
                    <td className="px-3 py-2.5 align-top whitespace-nowrap">
                      <span className="font-mono text-slate-800">{r.test_item_code || '—'}</span>
                      <p className="mt-0.5 flex items-center gap-1.5 text-slate-500">
                        <Dot cls={(r.sample_status || '').toLowerCase().startsWith('kabul') ? 'bg-emerald-500' : 'bg-amber-400'} />
                        {r.sample_status || 'Bekleniyor'}
                      </p>
                      {r.animal_status_code === 'CONSUMABLES_PENDING' && (
                        <span className="mt-1 inline-flex items-center rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                          {t('⚠️ Sarf Malzeme Bekleniyor', '⚠️ Consumables Pending')}
                        </span>
                      )}
                      {r.animal_status_code === 'QUARANTINE' && (
                        <span className="mt-1 inline-flex items-center rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
                          {t('Karantina (+7g)', 'Quarantine (+7d)')}
                        </span>
                      )}
                      {r.animal_status_code === 'REUSE' && (
                        <span className="mt-1 inline-flex items-center rounded border border-purple-200 bg-purple-50 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
                          {t('Tekrar Kullanım (Vet/HADYEK)', 'Animal Reuse (Vet/IACUC)')}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 align-top text-slate-800 whitespace-nowrap">
                      {r.study_director_name || <span className="text-slate-400 italic">Atanmamış</span>}
                    </td>
                    <td className="px-3 py-2.5 align-top whitespace-nowrap font-mono tabular-nums text-slate-700">
                      {r.dates.start ? (
                        <>
                          {fmtD(r.dates.start)} → {fmtD(r.dates.end)}
                          {!r.scheduled && <p className="font-sans text-[10px] text-slate-400">tarihler elle girilmiş</p>}
                        </>
                      ) : (
                        <span className="font-sans text-slate-400">Takvim yok</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 align-top whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5 text-slate-800">
                        <Dot cls={sm.dot} />
                        {sm.label}
                      </span>
                      {r.status === 'ONGOING' && (
                        <div className="mt-1">
                          {r.ongoing_phase === 'IN_REPORTING_QA' ? (
                            <span className="inline-flex items-center rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                              {t('Rapor / QA Bekliyor', 'Reporting / QA Pending')}
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                              {t('Deney Sürüyor', 'Experiment Active')}
                            </span>
                          )}
                        </div>
                      )}
                      {r.is_overdue && (
                        <p className="mt-0.5 text-[11px] font-medium text-red-700" title={r.overdue_reasons.join('\n')}>
                          Gecikmiş
                        </p>
                      )}
                      {r.is_contract_deadline_exceeded && (
                        <span
                          className="mt-0.5 inline-flex items-center rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700"
                          title={`Müşteri Taahhüt Tarihi: ${fmtD(r.contract_commitment_date)}`}
                        >
                          {t('Sözleşme Termini Aşılıyor', 'Contract Deadline Exceeded')}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 align-top">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono tabular-nums text-slate-600">
                          {prog.done}/{prog.total}
                        </span>
                        {prog.abroad > 0 && (
                          <span className="border border-amber-200 bg-amber-50 rounded px-1 py-0.2 text-[10px] text-amber-800">
                            yurt dışı
                          </span>
                        )}
                      </div>
                      <div className="mt-1 h-0.5 w-16 bg-slate-100">
                        <div className="h-full bg-slate-700" style={{ width: `${(prog.done / prog.total) * 100}%` }} />
                      </div>
                    </td>
                    <td className="px-4 py-2.5 align-top text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <div className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleWorkflowOrPlan(r)}
                          disabled={busy[`plan-${r.id}`]}
                          className={ghostBtn}
                        >
                          {busy[`plan-${r.id}`] && <Loader2 className="w-3 h-3 animate-spin" />}
                          İş Akışı &amp; Takvimi Gör / Planla
                        </button>
                        <button type="button" onClick={() => handleDocx(r)} disabled={busy[`docx-${r.id}`]} className={ghostBtn}>
                          {busy[`docx-${r.id}`] ? <Loader2 className="w-3 h-3 animate-spin" /> : <FileDown className="w-3 h-3" />}
                          Study Plan İndir (.docx)
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-400">
        {filtered.length} / {items.length} kayıt · Bir satıra tıklayarak sağdan açılan detay ve 11 adımlı iş akışı çekmecesini görüntüleyin.
      </p>

      {/* ============================================================= */}
      {/* SAĞDAN KAYAN ÇEKMECE                                            */}
      {/* ============================================================= */}
      {drawerId !== null && (
        <>
          <div className="fixed inset-0 bg-slate-900/20 z-40" onClick={closeDrawer} />
          <aside className="fixed top-0 right-0 bottom-0 z-50 w-full max-w-[640px] bg-white border-l border-slate-200 shadow-2xl flex flex-col">
            <header className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
              <div className="min-w-0">
                {drawerId === 'new' ? (
                  <h3 className="text-sm font-semibold text-slate-900">Yeni numune / çalışma kaydı</h3>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-slate-900">{detail?.study_code}</span>
                      {detail?.status && (
                        <span className="inline-flex items-center gap-1.5 text-xs text-slate-700">
                          <Dot cls={STATUS_META[detail.status].dot} />
                          {STATUS_META[detail.status].label}
                        </span>
                      )}
                      {detail?.status === 'ONGOING' && detail?.ongoing_phase_label && (
                        <span
                          className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                            detail.ongoing_phase === 'IN_REPORTING_QA'
                              ? 'border-blue-200 bg-blue-50 text-blue-700'
                              : 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          }`}
                        >
                          {t(
                            detail.ongoing_phase_label,
                            detail.ongoing_phase === 'IN_REPORTING_QA' ? 'Reporting / QA Pending' : 'Experiment Active'
                          )}
                        </span>
                      )}
                      {detail?.animal_status_badge && (
                        <span
                          className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                            detail.animal_status_code === 'CONSUMABLES_PENDING'
                              ? 'border-amber-300 bg-amber-50 text-amber-800'
                              : detail.animal_status_code === 'QUARANTINE'
                              ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                              : 'border-purple-200 bg-purple-50 text-purple-700'
                          }`}
                        >
                          {t(detail.animal_status_badge)}
                        </span>
                      )}
                      {detail?.is_contract_deadline_exceeded && (
                        <span className="inline-flex items-center rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
                          {t('Sözleşme Termini Aşılıyor', 'Contract Deadline Exceeded')}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5 truncate">
                      {detail?.requested_analysis || '—'} · {detail?.test_item_name || '—'}
                    </p>
                    {!drawerLoading && detail && <OperationalStudyStatus study={detail.study} />}
                    {detail?.overdue_reasons?.length > 0 && (
                      <p className="text-[11px] text-red-700 mt-1">{detail.overdue_reasons.join(' · ')}</p>
                    )}
                  </>
                )}
              </div>
              <button type="button" onClick={closeDrawer} className="text-slate-400 hover:text-slate-800" aria-label="Kapat">
                <X className="w-4 h-4" />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto">
              {drawerError && (
                <div className="mx-6 mt-4 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 rounded">{drawerError}</div>
              )}
              {drawerLoading || !detail ? (
                <p className="p-8 text-center text-xs text-slate-400">Yükleniyor…</p>
              ) : (
                <>
                  {drawerId !== 'new' && perms.can_upload_documents && (
                    <DocUpload
                      busy={docBusy}
                      onFiles={handleDocFiles}
                      result={docResult}
                      docs={docList}
                      canApplyDiff={canApplyDiff}
                      onApplyDiff={applyDiff}
                    />
                  )}

                  {/* a) Satış bilgileri */}
                  <Section
                    title="a) Satış Bilgileri"
                    hint="Bu bölümü Satış rolü düzenler."
                    actions={
                      editing === 'sales' ? (
                        <>
                          {drawerId !== 'new' && <LinkBtn onClick={() => setEditing(null)}>Vazgeç</LinkBtn>}
                          <LinkBtn strong onClick={saveEdit} disabled={saving}>
                            {saving ? 'Kaydediliyor…' : 'Kaydet'}
                          </LinkBtn>
                        </>
                      ) : (
                        perms.can_edit_sales && <LinkBtn onClick={() => startEdit('sales')}>Düzenle</LinkBtn>
                      )
                    }
                  >
                    {editing === 'sales' ? (
                      <div className="grid grid-cols-2 gap-3">
                        {drawerId === 'new' && (
                          <FormField label="Çalışma kodu (GLP No) *" wide>
                            <div className="space-y-1.5">
                              <input
                                className={`${inputCls} font-mono`}
                                value={form.study_code || ''}
                                onChange={(e) => setForm({ ...form, study_code: e.target.value.toUpperCase() })}
                                placeholder={summary?.next_glp_code || 'GLP2026-083'}
                              />
                              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                                <span className="text-slate-500">{t('Sıradaki otomatik kod:', 'Next auto code:')}</span>
                                <button
                                  type="button"
                                  onClick={() => setForm({ ...form, study_code: summary?.next_glp_code || 'GLP2026-083', glp_type: 'GLP' })}
                                  className="font-mono font-semibold rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-blue-700 hover:bg-blue-100"
                                >
                                  {summary?.next_glp_code || 'GLP2026-083'} (GLP)
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setForm({ ...form, study_code: summary?.next_non_glp_code || 'NGLP-2026-012', glp_type: 'NON-GLP' })}
                                  className="font-mono font-semibold rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-slate-700 hover:bg-slate-100"
                                >
                                  {summary?.next_non_glp_code || 'NGLP-2026-012'} (Non-GLP)
                                </button>
                              </div>
                            </div>
                          </FormField>
                        )}
                        <FormField label="Talep edilen analiz" wide>
                          <input className={inputCls} value={form.requested_analysis || ''} onChange={(e) => setForm({ ...form, requested_analysis: e.target.value })} />
                        </FormField>
                        <FormField label="Test maddesinin adı">
                          <input className={inputCls} value={form.test_item_name || ''} onChange={(e) => setForm({ ...form, test_item_name: e.target.value })} />
                        </FormField>
                        <FormField label="Sponsor">
                          <input className={inputCls} value={form.sponsor_name || ''} onChange={(e) => setForm({ ...form, sponsor_name: e.target.value })} />
                        </FormField>
                        <FormField label="Fatura edilecek firma">
                          <input className={inputCls} value={form.billing_company || ''} onChange={(e) => setForm({ ...form, billing_company: e.target.value })} />
                        </FormField>
                        <FormField label="Teklif no">
                          <input className={`${inputCls} font-mono`} value={form.quote_no || ''} onChange={(e) => setForm({ ...form, quote_no: e.target.value })} />
                        </FormField>
                        <FormField label="Satış yöneticisi">
                          <input className={inputCls} value={form.sales_manager || ''} onChange={(e) => setForm({ ...form, sales_manager: e.target.value })} />
                        </FormField>
                        <FormField label="Sözleşme tarihi">
                          <input type="date" className={inputCls} value={form.study_agreement_date || ''} onChange={(e) => setForm({ ...form, study_agreement_date: e.target.value })} />
                        </FormField>
                        <FormField label="Ödeme durumu">
                          <select className={inputCls} value={form.payment_status || ''} onChange={(e) => setForm({ ...form, payment_status: e.target.value })}>
                            <option value="">Belirtilmedi</option>
                            <option value="Ön ödeme alındı">Ön ödeme alındı</option>
                            <option value="Ödeme yapılmadı.">Ödeme yapılmadı.</option>
                            <option value="Ödeme yapıldı.">Ödeme yapıldı.</option>
                          </select>
                        </FormField>
                        <FormField label="Beklenen geliş tarihi">
                          <input type="date" className={inputCls} value={form.expected_arrival_date || ''} onChange={(e) => setForm({ ...form, expected_arrival_date: e.target.value })} />
                        </FormField>
                        <div className="col-span-2">
                          <span className="block text-[11px] text-slate-500 mb-1">İlgili kişiler (isim ve e-posta)</span>
                          <div className="space-y-1.5">
                            {(form.contacts || []).map((c, idx) => (
                              <div key={idx} className="flex items-center gap-1.5">
                                <input
                                  className={inputCls}
                                  placeholder="Ad Soyad"
                                  value={c.name || ''}
                                  onChange={(e) => {
                                    const next = [...form.contacts];
                                    next[idx] = { ...next[idx], name: e.target.value };
                                    setForm({ ...form, contacts: next });
                                  }}
                                />
                                <input
                                  className={inputCls}
                                  placeholder="e-posta"
                                  value={c.email || ''}
                                  onChange={(e) => {
                                    const next = [...form.contacts];
                                    next[idx] = { ...next[idx], email: e.target.value };
                                    setForm({ ...form, contacts: next });
                                  }}
                                />
                                <button
                                  type="button"
                                  className="text-slate-400 hover:text-red-700 p-1"
                                  onClick={() => setForm({ ...form, contacts: form.contacts.filter((_, i) => i !== idx) })}
                                  aria-label="Kişiyi kaldır"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ))}
                          </div>
                          <button
                            type="button"
                            className="mt-1.5 text-xs text-blue-700 hover:underline"
                            onClick={() => setForm({ ...form, contacts: [...(form.contacts || []), { name: '', email: '' }] })}
                          >
                            + Kişi ekle
                          </button>
                        </div>
                      </div>
                    ) : (
                      <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
                        <Field label="Talep edilen analiz" value={detail.requested_analysis} wide />
                        <Field label="Test maddesinin adı" value={detail.test_item_name} />
                        <Field label="Sponsor" value={detail.sponsor_name} />
                        <Field label="Fatura edilecek firma" value={detail.billing_company} />
                        <Field label="Teklif no" value={detail.quote_no} mono />
                        <Field label="Satış yöneticisi" value={detail.sales_manager} />
                        <Field label="Sözleşme tarihi" value={detail.study_agreement_date && fmtD(detail.study_agreement_date)} mono />
                        <Field
                          label="Müşteri taahhüt tarihi"
                          value={
                            detail.contract_commitment_date ? (
                              <span className="inline-flex flex-wrap items-center gap-1.5">
                                <span className="font-mono tabular-nums">{fmtD(detail.contract_commitment_date)}</span>
                                {detail.is_contract_deadline_exceeded && (
                                  <span className="rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-sans font-semibold text-red-700">
                                    {t('Sözleşme Termini Aşılıyor', 'Contract Deadline Exceeded')}
                                  </span>
                                )}
                              </span>
                            ) : null
                          }
                        />
                        <Field
                          label="Ödeme durumu"
                          value={
                            detail.payment_status ? (
                              <span
                                className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${
                                  detail.payment_status.toLowerCase().includes('yapıldı') && !detail.payment_status.toLowerCase().includes('yapılmadı')
                                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                                    : detail.payment_status.toLowerCase().includes('ön ödeme')
                                    ? 'border-blue-200 bg-blue-50 text-blue-700'
                                    : 'border-amber-200 bg-amber-50 text-amber-800'
                                }`}
                              >
                                {t(detail.payment_status)}
                              </span>
                            ) : null
                          }
                        />
                        <Field label="Test laboratuvarı" value={detail.test_laboratory} />
                        <Field label="Beklenen geliş tarihi" value={detail.expected_arrival_date && fmtD(detail.expected_arrival_date)} mono />
                        <Field
                          label="İlgili kişiler"
                          wide
                          value={
                            detail.contacts?.length
                              ? detail.contacts.map((c, i) => (
                                  <span key={i} className="block">
                                    {c.name || '—'} {c.email && <span className="font-mono text-slate-500">&lt;{c.email}&gt;</span>}
                                  </span>
                                ))
                              : null
                          }
                        />
                      </dl>
                    )}
                  </Section>

                  {drawerId !== 'new' && (
                    <>
                      {/* b) Numune kabul — TRM */}
                      <Section
                        title="b) Numune Kabul — Test ve Referans Madde"
                        hint="Bu bölümü TRM Kabul rolü düzenler."
                        actions={
                          editing === 'trm' ? (
                            <>
                              <LinkBtn onClick={() => setEditing(null)}>Vazgeç</LinkBtn>
                              <LinkBtn strong onClick={saveEdit} disabled={saving}>
                                {saving ? 'Kaydediliyor…' : 'Kaydet'}
                              </LinkBtn>
                            </>
                          ) : (
                            perms.can_edit_trm && <LinkBtn onClick={() => startEdit('trm')}>Düzenle</LinkBtn>
                          )
                        }
                      >
                        {perms.can_upload_documents && editing !== 'trm' && (
                          <DocUpload busy={docBusy} onFiles={handleDocFiles} compact canApplyDiff={canApplyDiff} onApplyDiff={applyDiff} />
                        )}
                        {editing === 'trm' ? (
                          <div className="grid grid-cols-2 gap-3">
                            <FormField label="Numune durumu">
                              <select className={inputCls} value={form.sample_status || ''} onChange={(e) => setForm({ ...form, sample_status: e.target.value })}>
                                <option value="Bekleniyor">Bekleniyor</option>
                                <option value="Kabul edildi">Kabul edildi</option>
                              </select>
                            </FormField>
                            <FormField label="Test madde kodu">
                              <input className={`${inputCls} font-mono`} value={form.test_item_code || ''} onChange={(e) => setForm({ ...form, test_item_code: e.target.value.toUpperCase() })} placeholder="TI-2026-0016" />
                            </FormField>
                            <FormField label="İstanbul'a geliş tarihi">
                              <input type="date" className={inputCls} value={form.istanbul_arrival_date || ''} onChange={(e) => setForm({ ...form, istanbul_arrival_date: e.target.value })} />
                            </FormField>
                            <FormField label="Laboratuvara geliş tarihi">
                              <input type="date" className={inputCls} value={form.lab_arrival_date || ''} onChange={(e) => setForm({ ...form, lab_arrival_date: e.target.value })} />
                            </FormField>
                            <FormField label="Teslim alınan miktar">
                              <input className={inputCls} value={form.received_quantity || ''} onChange={(e) => setForm({ ...form, received_quantity: e.target.value })} placeholder="30 adet / 30 pieces" />
                            </FormField>
                            <FormField label="Hayvan / sarf malzeme durumu">
                              <select className={inputCls} value={form.animal_consumable_status || ''} onChange={(e) => setForm({ ...form, animal_consumable_status: e.target.value })}>
                                <option value="">Belirtilmedi</option>
                                <option value="Mevcut">Mevcut</option>
                                <option value="Mevcut (Karantina)">Mevcut (Karantina)</option>
                                <option value="Mevcut (Tekrar kullanım)">Mevcut (Tekrar kullanım)</option>
                                <option value="Sarf malzemeler bekleniyor.">Sarf malzemeler bekleniyor.</option>
                              </select>
                            </FormField>
                            <FormField label="Hayvan / sarf temin tarihi">
                              <input type="date" className={inputCls} value={form.animal_procurement_date || ''} onChange={(e) => setForm({ ...form, animal_procurement_date: e.target.value })} />
                            </FormField>
                            <FormField label="Lot / seri no">
                              <input className={`${inputCls} font-mono`} value={form.lot_no || ''} onChange={(e) => setForm({ ...form, lot_no: e.target.value })} />
                            </FormField>
                            <FormField label="SKT">
                              <input className={inputCls} value={form.expiry_date || ''} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} placeholder="11.2027" />
                            </FormField>
                            <FormField label="Saklama koşulu">
                              <input className={inputCls} value={form.storage_condition || ''} onChange={(e) => setForm({ ...form, storage_condition: e.target.value })} />
                            </FormField>
                            <FormField label="Üretim tarihi">
                              <input className={inputCls} value={form.manufacture_date || ''} onChange={(e) => setForm({ ...form, manufacture_date: e.target.value })} placeholder="11.2025" />
                            </FormField>
                            <FormField label="Polar ekstraksiyon çözücüsü">
                              <input className={inputCls} value={form.extraction_polar_solvent || ''} onChange={(e) => setForm({ ...form, extraction_polar_solvent: e.target.value })} placeholder="%0.9 NaCl" />
                            </FormField>
                            <FormField label="Apolar ekstraksiyon çözücüsü">
                              <input className={inputCls} value={form.extraction_non_polar_solvent || ''} onChange={(e) => setForm({ ...form, extraction_non_polar_solvent: e.target.value })} placeholder="Susam yağı" />
                            </FormField>
                            <FormField label="Numune notu" wide>
                              <textarea rows={2} className={inputCls} value={form.sample_note || ''} onChange={(e) => setForm({ ...form, sample_note: e.target.value })} />
                            </FormField>
                            {detail.related?.length > 0 && (
                              <label className="col-span-2 flex items-start gap-2 text-xs text-slate-700">
                                <input type="checkbox" className="mt-0.5" checked={applyRelated} onChange={(e) => setApplyRelated(e.target.checked)} />
                                <span>
                                  Aynı numuneyi kullanan diğer çalışmalarda da güncelle (
                                  <span className="font-mono">{detail.related.map((r) => r.study_code).join(', ')}</span>)
                                </span>
                              </label>
                            )}
                          </div>
                        ) : (
                          <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
                            <Field
                              label="Numune durumu"
                              value={
                                <span className="inline-flex items-center gap-1.5">
                                  <Dot cls={(detail.sample_status || '').toLowerCase().startsWith('kabul') ? 'bg-emerald-500' : 'bg-amber-400'} />
                                  {detail.sample_status || 'Bekleniyor'}
                                </span>
                              }
                            />
                            <Field label="Test madde kodu" value={detail.test_item_code} mono />
                            <Field label="İstanbul'a geliş tarihi" value={detail.istanbul_arrival_date && fmtD(detail.istanbul_arrival_date)} mono />
                            <Field label="Laboratuvara geliş tarihi" value={detail.lab_arrival_date && fmtD(detail.lab_arrival_date)} mono />
                            <Field label="Teslim alınan miktar" value={detail.received_quantity} />
                            <Field label="Lot / seri no" value={detail.lot_no} mono />
                            <Field label="SKT" value={detail.expiry_date} />
                            <Field label="Saklama koşulu" value={detail.storage_condition} />
                            <Field label="Üretim tarihi" value={detail.manufacture_date} />
                            <Field label="Polar ekstraksiyon çözücüsü" value={detail.extraction_polar_solvent && `${detail.extraction_polar_solvent}`} />
                            <Field label="Apolar ekstraksiyon çözücüsü" value={detail.extraction_non_polar_solvent} />
                            <Field
                              label="Hayvan / sarf malzeme durumu"
                              value={
                                detail.animal_consumable_status ? (
                                  <span className="inline-flex flex-wrap items-center gap-1.5">
                                    <span>{t(detail.animal_consumable_status)}</span>
                                    {detail.animal_status_badge && (
                                      <span
                                        className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                                          detail.animal_status_code === 'CONSUMABLES_PENDING'
                                            ? 'border-amber-300 bg-amber-50 text-amber-800'
                                            : detail.animal_status_code === 'QUARANTINE'
                                            ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                                            : 'border-purple-200 bg-purple-50 text-purple-700'
                                        }`}
                                      >
                                        {t(detail.animal_status_badge)}
                                      </span>
                                    )}
                                  </span>
                                ) : null
                              }
                            />
                            <Field label="Hayvan / sarf temin tarihi" value={detail.animal_procurement_date && fmtD(detail.animal_procurement_date)} mono />
                            <Field label="Numune notu" value={detail.sample_note} wide />
                            {detail.document_autofill && (
                              <p className="col-span-2 text-[11px] text-slate-400">
                                Son otomatik doldurma: {detail.document_autofill.by} · {fmtD(detail.document_autofill.at)} ·{' '}
                                {detail.document_autofill.source_documents?.length || 0} belge
                              </p>
                            )}
                            <div className="col-span-2">
                              <dt className="text-[11px] text-slate-500">Aynı numuneyi kullanan diğer çalışmalar</dt>
                              <dd className="mt-1 flex flex-wrap gap-1.5">
                                {detail.related?.length ? (
                                  detail.related.map((r) => (
                                    <button
                                      key={r.id}
                                      type="button"
                                      onClick={() => openDrawer(r.id)}
                                      className="font-mono text-[11px] border border-slate-200 hover:border-slate-400 rounded px-1.5 py-0.5 text-slate-700"
                                      title={r.requested_analysis}
                                    >
                                      {r.study_code}
                                    </button>
                                  ))
                                ) : (
                                  <span className="text-xs text-slate-300">—</span>
                                )}
                              </dd>
                            </div>
                          </dl>
                        )}
                      </Section>

                      {/* c) Otomatik takvim ve rapor tarihleri */}
                      <Section
                        title="c) Otomatik Takvim & Rapor Tarihleri"
                        hint="Tarihler çalışma takvimi oluşturulduğunda sistem tarafından hesaplanır."
                        actions={
                          editing === 'plan' ? (
                            <>
                              <LinkBtn onClick={() => setEditing(null)}>Vazgeç</LinkBtn>
                              <LinkBtn strong onClick={saveEdit} disabled={saving}>
                                {saving ? 'Kaydediliyor…' : 'Kaydet'}
                              </LinkBtn>
                            </>
                          ) : (
                            perms.can_assign_planning && <LinkBtn onClick={() => startEdit('plan')}>Şablon / ÇY ata</LinkBtn>
                          )
                        }
                      >
                        {editing === 'plan' && (
                          <div className="grid grid-cols-2 gap-3 mb-4">
                            <FormField label="Test şablonu">
                              <select className={inputCls} value={form.template_code || ''} onChange={(e) => setForm({ ...form, template_code: e.target.value })}>
                                <option value="">Analiz adından otomatik belirle</option>
                                {(data?.templates || []).map((t) => (
                                  <option key={t.code} value={t.code}>
                                    {t.label} ({t.cage_count} kafes)
                                  </option>
                                ))}
                              </select>
                            </FormField>
                            <FormField label="Çalışma Yöneticisi">
                              <select className={inputCls} value={form.study_director_name || ''} onChange={(e) => setForm({ ...form, study_director_name: e.target.value })}>
                                <option value="">Atanmamış</option>
                                {(data?.study_directors || []).map((n) => (
                                  <option key={n} value={n}>
                                    {n}
                                  </option>
                                ))}
                              </select>
                            </FormField>
                          </div>
                        )}
                        <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
                          <Field label="Çalışma başlangıç (Gün 0)" value={detail.dates?.start && fmtD(detail.dates.start)} mono />
                          <Field label="Test bitiş tarihi" value={detail.dates?.end && fmtD(detail.dates.end)} mono />
                          <Field
                            label={detail.requires_quarantine ? 'Taslak rapor teslim (bitiş + 3g + 7g karantina)' : 'Taslak rapor teslim (bitiş + 3 gün)'}
                            value={detail.dates?.draft_report && fmtD(detail.dates.draft_report)}
                            mono
                          />
                          <Field
                            label={detail.requires_quarantine ? 'Final rapor gönderim (bitiş + 7g + 7g karantina)' : 'Final rapor gönderim (bitiş + 7 gün)'}
                            value={detail.dates?.final_report && fmtD(detail.dates.final_report)}
                            mono
                          />
                          <Field
                            label="Standart TAT süresi"
                            value={
                              detail.effective_tat_days
                                ? `${detail.effective_tat_days} ${t('gün', 'days')}${detail.requires_quarantine ? ` (${t('Karantina +7g dahil', 'Incl. +7d Quarantine')})` : ''}`
                                : null
                            }
                          />
                          <Field label="Çalışma Yöneticisi" value={detail.study_director_name} />
                          <Field label="Test şablonu" value={detail.template_code} mono wide />
                        </dl>
                        {detail.auto_schedule_notice && (
                          <p className="mt-3 border-l-2 border-amber-500 pl-3 text-xs text-slate-800">{detail.auto_schedule_notice}</p>
                        )}
                        {lastPlan?.capacity_info?.cage && (
                          <p className="mt-2 text-xs text-slate-600 flex items-center gap-1.5">
                            <Dot cls={{ OK: 'bg-emerald-500', FLEX: 'bg-amber-400', EXCEEDED: 'bg-red-500' }[lastPlan.capacity_info.cage.level]} />
                            {lastPlan.capacity_info.cage.message}
                          </p>
                        )}
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          {perms.can_plan && detail.study?.status !== 'APPROVED' && detail.study?.status !== 'IN_PROGRESS' && (
                            <button
                              type="button"
                              className={ghostBtn}
                              disabled={busy[`plan-${detail.id}`]}
                              onClick={async () => {
                                setBusyKey(`plan-${detail.id}`, true);
                                setDrawerError(null);
                                try {
                                  const res = await planSample(detail.id);
                                  setLastPlan(res.data.plan);
                                  setDetail(res.data.sample);
                                  await load();
                                } catch (err) {
                                  setDrawerError(extractError(err, 'Otomatik takvim oluşturulamadı.'));
                                } finally {
                                  setBusyKey(`plan-${detail.id}`, false);
                                }
                              }}
                            >
                              {busy[`plan-${detail.id}`] && <Loader2 className="w-3 h-3 animate-spin" />}
                              {detail.scheduled ? 'Takvimi Yeniden Hesapla' : 'Otomatik Taslak Takvim Oluştur'}
                            </button>
                          )}
                          {detail.scheduled && detail.study?.id && canOpenPlanning && (
                            <button
                              type="button"
                              className={ghostBtn}
                              onClick={() => navigate('/planning', { state: { selectedStudyId: detail.study.id } })}
                            >
                              Planlama Ekranında Aç
                            </button>
                          )}
                          <button type="button" className={ghostBtn} onClick={() => handleDocx(detail)} disabled={busy[`docx-${detail.id}`]}>
                            {busy[`docx-${detail.id}`] ? <Loader2 className="w-3 h-3 animate-spin" /> : <FileDown className="w-3 h-3" />}
                            Study Plan İndir (.docx)
                          </button>
                        </div>
                      </Section>

                      {/* d) 11 adımlı iş akışı */}
                      <section className="px-6 py-5">
                        <div className="mb-4">
                          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">d) 11 Adımlı Numune İş Akışı</h4>
                          <p className="text-[11px] text-slate-400 mt-0.5">
                            {detail.progress}/11 adım tamamlandı · Onay imzaları basan kişinin adı ve tarihiyle kaydedilir.
                          </p>
                        </div>
                        <ol>
                          {(detail.workflow || []).map((s, idx) => {
                            const last = idx === detail.workflow.length - 1;
                            const stateCls =
                              s.state === 'done'
                                ? 'bg-slate-900 border-slate-900 text-white'
                                : s.overdue
                                ? 'bg-white border-red-500'
                                : s.state === 'current'
                                ? 'bg-white border-blue-600 ring-2 ring-blue-100'
                                : 'bg-white border-slate-300';
                            return (
                              <li key={s.no} data-testid={`workflow-step-${s.no}`} className="flex gap-3">
                                <div className="flex flex-col items-center">
                                  <span className={`w-4 h-4 rounded-full border flex items-center justify-center shrink-0 mt-0.5 ${stateCls}`}>
                                    {s.state === 'done' && <Check className="w-2.5 h-2.5" />}
                                  </span>
                                  {!last && <span className={`w-px flex-1 my-1 ${s.state === 'done' ? 'bg-slate-400' : 'bg-slate-200'}`} />}
                                </div>
                                <div className="pb-5 flex-1 min-w-0">
                                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                                    <p className={`text-xs ${s.state === 'done' ? 'text-slate-500' : 'text-slate-900 font-medium'}`}>
                                      <span className="font-mono text-slate-400 mr-1.5">{String(s.no).padStart(2, '0')}</span>
                                      {s.title}
                                      {s.marker && (
                                        <span className={`ml-2 font-mono text-[10px] px-1.5 py-0.5 rounded border ${
                                          s.marker === '+'
                                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                            : s.marker === '-'
                                            ? 'bg-slate-50 text-slate-500 border-slate-200'
                                            : 'bg-purple-50 text-purple-700 border-purple-200'
                                        }`}>
                                          {s.marker === '+' ? '+ Tamamlandı' : s.marker === '-' ? '- Bekliyor' : s.marker}
                                        </span>
                                      )}
                                      {s.no === 10 && (s.payment_status || detail.payment_status) && (
                                        <span
                                          className={`ml-2 inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
                                            String(s.payment_status || detail.payment_status)
                                              .toLowerCase()
                                              .includes('yapıldı') &&
                                            !String(s.payment_status || detail.payment_status)
                                              .toLowerCase()
                                              .includes('yapılmadı')
                                              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                                              : String(s.payment_status || detail.payment_status)
                                                  .toLowerCase()
                                                  .includes('ön ödeme')
                                              ? 'border-blue-200 bg-blue-50 text-blue-700'
                                              : 'border-amber-200 bg-amber-50 text-amber-800'
                                          }`}
                                        >
                                          {t(s.payment_status || detail.payment_status)}
                                        </span>
                                      )}
                                    </p>
                                    <span className="text-[11px] text-slate-400">{s.owner}</span>
                                  </div>
                                  <p className="text-[11px] mt-0.5 text-slate-500 font-mono tabular-nums">
                                    {s.done
                                      ? `${s.done_by ? `${s.done_by} · ` : ''}${s.done_at ? fmtD(s.done_at) : ''}`
                                      : s.due_date
                                      ? `${s.overdue ? 'Gecikti · ' : 'Hedef '}${fmtD(s.due_date)}`
                                      : ''}
                                  </p>

                                  {s.no === 6 && (
                                    <p className="mt-1.5 text-[11px] text-slate-600">
                                      ÇY/KG/TBY belge imzaları operasyonel plan onayından ayrı kaydedilir.
                                      {detail.study?.status === 'DRAFT' && ' Görevleri yürütmek için planlama ekranında plan onayı gerekir.'}
                                    </p>
                                  )}
                                  {s.no === 11 && (
                                    <p className="mt-1.5 text-[11px] text-slate-600">
                                      Final rapor onayı belge iş akışına aittir; operasyonel çalışmayı otomatik olarak tamamlamaz.
                                    </p>
                                  )}

                                  {s.no === 3 ? (
                                    <AnimalOrder key={detail.id} step={s} busy={busy['wf-3']} onAction={body => doWorkflow(3, body)} />
                                  ) : s.kind === 'approval' ? (
                                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                                      {s.approvals.map((a) => (
                                        <span key={a.key} className="inline-flex items-center gap-1.5 border border-slate-200 rounded px-1.5 py-1 text-[11px]">
                                          <span className="font-semibold text-slate-700">{a.label}</span>
                                          {a.signed ? (
                                            <>
                                              <Check className="w-3 h-3 text-slate-900" />
                                              <span className="text-slate-600">
                                                {a.by} · <span className="font-mono">{fmtD(a.at)}</span>
                                              </span>
                                              {a.can_sign && (
                                                <button
                                                  type="button"
                                                  className="text-slate-400 hover:text-red-700"
                                                  onClick={() => doWorkflow(s.no, { action: 'revoke', approver: a.key })}
                                                >
                                                  geri al
                                                </button>
                                              )}
                                            </>
                                          ) : a.can_sign ? (
                                            <button
                                              type="button"
                                              disabled={busy[`wf-${s.no}`]}
                                              className="font-semibold text-blue-700 hover:text-blue-900 disabled:opacity-40"
                                              onClick={() => doWorkflow(s.no, { action: 'sign', approver: a.key })}
                                            >
                                              {a.label} Onayla
                                            </button>
                                          ) : (
                                            <span className="text-slate-400">{a.full} bekleniyor</span>
                                          )}
                                        </span>
                                      ))}
                                    </div>
                                  ) : (
                                    s.can_edit && (
                                      <div className="mt-1.5">
                                        {s.done ? (
                                          <LinkBtn onClick={() => doWorkflow(s.no, { action: 'undo' })} disabled={busy[`wf-${s.no}`]}>
                                            Geri al
                                          </LinkBtn>
                                        ) : (
                                          <button
                                            type="button"
                                            disabled={busy[`wf-${s.no}`]}
                                            onClick={() => doWorkflow(s.no, { action: 'complete' })}
                                            className="border border-slate-300 hover:bg-slate-50 disabled:opacity-40 rounded px-2 py-0.5 text-[11px] font-medium text-slate-700"
                                          >
                                            Tamamlandı olarak işaretle
                                          </button>
                                        )}
                                      </div>
                                    )
                                  )}
                                </div>
                              </li>
                            );
                          })}
                        </ol>
                      </section>
                    </>
                  )}
                </>
              )}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
