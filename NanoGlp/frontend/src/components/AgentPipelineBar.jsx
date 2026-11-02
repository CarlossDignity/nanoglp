import React from 'react';
import {
  ScanText,
  Link2,
  UserCheck,
  GitCompareArrows,
  ClipboardCheck,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
} from 'lucide-react';

const TONES = {
  green: {
    ring: 'border-emerald-200 bg-emerald-50/60',
    icon: 'bg-emerald-100 text-emerald-600',
    badge: 'bg-emerald-100 text-emerald-800 border-emerald-200',
    line: 'bg-emerald-300',
  },
  amber: {
    ring: 'border-amber-200 bg-amber-50/70',
    icon: 'bg-amber-100 text-amber-600',
    badge: 'bg-amber-100 text-amber-800 border-amber-200',
    line: 'bg-amber-300',
  },
  red: {
    ring: 'border-red-200 bg-red-50/70',
    icon: 'bg-red-100 text-red-600',
    badge: 'bg-red-100 text-red-800 border-red-200',
    line: 'bg-red-300',
  },
  blue: {
    ring: 'border-blue-200 bg-blue-50/70',
    icon: 'bg-blue-100 text-blue-600',
    badge: 'bg-blue-100 text-blue-800 border-blue-200',
    line: 'bg-blue-300',
  },
  slate: {
    ring: 'border-slate-200 bg-slate-50',
    icon: 'bg-slate-100 text-slate-500',
    badge: 'bg-slate-100 text-slate-600 border-slate-200',
    line: 'bg-slate-300',
  },
};

/** Dossier verisinden (aggregate_dossier çıktısı) 5 adımlık denetim hattı durumunu türetir. */
export function buildPipelineSteps(dossier) {
  const totalDocs = dossier?.total_documents ?? 0;
  const codes = dossier?.study_codes || [];
  const sd = dossier?.sd_resolution;
  const birthCheck = (dossier?.cross_checks || []).find((c) => c.check === 'ANIMAL_BIRTH_DATE');

  // 3) SD denetimi
  let sdStep;
  if (sd?.status === 'HANDOVER_REQUIRED') {
    sdStep = {
      tone: 'amber',
      badge: 'Otomatik Devir Önerisi',
      detail: `${sd.document_sd_name} → ${sd.suggested_sd_name || 'aktif SD seçilmeli'}`,
      Badge: AlertTriangle,
    };
  } else if (sd?.status === 'MATCHED') {
    sdStep = {
      tone: 'green',
      badge: 'Aktif SD ile Eşleşti',
      detail: `${sd.document_sd_name} → ${sd.matched_sd_name}`,
      Badge: CheckCircle2,
    };
  } else {
    sdStep = {
      tone: 'slate',
      badge: 'Varsayılan SD Atandı',
      detail: sd?.suggested_sd_name || 'Belgede SD adı bulunamadı',
      Badge: CheckCircle2,
    };
  }

  // 4) Çapraz belge kontrolü
  let crossStep;
  if (birthCheck?.status === 'MISMATCH') {
    crossStep = { tone: 'red', badge: 'GLP Uyarısı Yakalandı', Badge: AlertTriangle };
  } else if (birthCheck?.status === 'MATCH') {
    crossStep = { tone: 'green', badge: 'Belgeler Uyumlu', Badge: CheckCircle2 };
  } else if (birthCheck?.status === 'INCOMPLETE') {
    crossStep = { tone: 'amber', badge: 'Tek Kaynak — Doğrulama Bekliyor', Badge: AlertTriangle };
  } else {
    crossStep = { tone: 'slate', badge: 'Karşılaştırılacak Belge Yok', Badge: AlertTriangle };
  }

  const ready = codes.length > 0;

  return [
    {
      key: 'ocr',
      Icon: ScanText,
      title: 'Vision OCR & Tablo Okuma',
      detail: `${totalDocs} Belge`,
      tone: totalDocs > 0 ? 'green' : 'slate',
      badge: totalDocs > 0 ? 'Tamamlandı' : 'Belge Bekleniyor',
      Badge: CheckCircle2,
    },
    {
      key: 'match',
      Icon: Link2,
      title: 'Sözleşme & TIIS Eşleştirme',
      detail: `${codes.length} Çalışma Kodu`,
      tone: codes.length > 0 ? 'green' : 'amber',
      badge: codes.length > 0 ? 'Tamamlandı' : 'Kod Tespit Edilemedi',
      Badge: codes.length > 0 ? CheckCircle2 : AlertTriangle,
    },
    {
      key: 'sd',
      Icon: UserCheck,
      title: 'SD Yetki & Devir Denetimi',
      detail: sdStep.detail,
      tone: sdStep.tone,
      badge: sdStep.badge,
      Badge: sdStep.Badge,
    },
    {
      key: 'cross',
      Icon: GitCompareArrows,
      title: 'Çapraz Belge Kontrolü',
      detail: 'Menşei vs FM.083 Yaş Farkı',
      tone: crossStep.tone,
      badge: crossStep.badge,
      Badge: crossStep.Badge,
    },
    {
      key: 'master',
      Icon: ClipboardCheck,
      title: 'Master Çalışma Profili & Şablon Hazırlığı',
      detail: dossier?.suggested_template_code || 'ISO_10993_23_IC',
      tone: ready ? 'blue' : 'amber',
      badge: ready ? 'Planlamaya Hazır' : 'Çalışma Kodu Bekleniyor',
      Badge: ready ? Sparkles : AlertTriangle,
    },
  ];
}

/** FAZ 7 — "AI Vision & GLP Denetim Hattı" (Agent Pipeline) yatay şeridi */
export default function AgentPipelineBar({ dossier }) {
  const steps = buildPipelineSteps(dossier);

  return (
    <div className="border-b border-slate-200/80 bg-white px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-blue-700" />
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
            AI Vision & GLP Denetim Hattı (Agent Pipeline)
          </h4>
        </div>
        <p className="text-[11px] text-slate-500">
          Yapay zeka okur ve önerir; GLP kararını her zaman SD / TFM onaylar.
        </p>
      </div>

      <ol className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {steps.map((s, idx) => {
          const t = TONES[s.tone];
          return (
            <li key={s.key} className="relative">
              <div className={`h-full rounded-xl border p-3.5 ${t.ring}`}>
                <div className="flex items-center justify-between mb-2.5">
                  <span className={`flex items-center justify-center w-8 h-8 rounded-full ${t.icon}`}>
                    <s.Icon className="w-4 h-4" />
                  </span>
                  <span className="text-[10px] font-bold text-slate-400 tabular-nums">ADIM {idx + 1}</span>
                </div>
                <p className="text-xs font-semibold text-slate-900 leading-snug">{s.title}</p>
                <p className="text-[11px] text-slate-600 mt-0.5 leading-snug break-words">{s.detail}</p>
                <span className={`mt-2.5 inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-md border ${t.badge}`}>
                  <s.Badge className="w-3 h-3" />
                  {s.badge}
                </span>
              </div>
              {idx < steps.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`hidden md:block absolute top-1/2 -right-3 w-3 h-0.5 ${t.line}`}
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
