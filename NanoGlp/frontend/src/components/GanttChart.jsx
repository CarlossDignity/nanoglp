import React from 'react';
import { Lock, AlertTriangle, FileWarning } from 'lucide-react';
import { fmtDateTime, fmtMinutes } from '../utils/format';

const DAY_MS = 86400000;
const STRIPES_RED = 'repeating-linear-gradient(45deg, #dc2626 0 6px, #991b1b 6px 12px)';
const STRIPES_BAND = 'repeating-linear-gradient(135deg, rgba(255,255,255,0.12) 0 10px, transparent 10px 20px)';

/**
 * Bağımlılıksız Gantt.
 *  - mode="conflict": kırmızı "ÇAKIŞMA VAR" bandı + diyagonal filigran; çakışan adımlar kırmızı çizgili.
 *  - mode="draft":    gri "TASLAK / DRAFT" bandı + soluk filigran.
 */
export default function GanttChart({ steps = [], conflictStepIds = new Set(), mode = null, conflictCount = 0 }) {
  if (!steps.length) return null;

  const starts = steps.map((s) => new Date(s.planned_start).getTime());
  const ends = steps.map((s) => new Date(s.planned_end).getTime());
  const rangeStart = new Date(Math.min(...starts));
  rangeStart.setHours(0, 0, 0, 0);
  const rangeEnd = new Date(Math.max(...ends));
  rangeEnd.setHours(24, 0, 0, 0);
  const totalMs = rangeEnd - rangeStart;
  const dayCount = Math.round(totalMs / DAY_MS);
  const firstStudyDay = Math.min(...steps.map((s) => s.study_day ?? 0));
  const pct = (t) => ((t - rangeStart.getTime()) / totalMs) * 100;

  const isConflict = mode === 'conflict';
  const flaggedCount = steps.filter((s) => conflictStepIds.has(s.id)).length;

  return (
    <div className={`rounded-md overflow-hidden border ${isConflict ? 'border-red-600 border-2' : 'border-slate-200'}`}>
      {mode && (
        <div
          className={`flex items-center justify-center gap-2 py-2 text-xs font-bold tracking-[0.25em] uppercase text-white ${
            isConflict ? 'bg-red-600' : 'bg-slate-600'
          }`}
          style={{ backgroundImage: STRIPES_BAND }}
        >
          {isConflict ? <AlertTriangle className="w-4 h-4" /> : <FileWarning className="w-4 h-4" />}
          {isConflict
            ? `Taslak · Çakışma Var — ${conflictCount} kayıt / ${flaggedCount} adım etkilendi`
            : 'Taslak / Draft — SD onayı bekliyor'}
        </div>
      )}

      <div className="relative overflow-x-auto bg-white">
        <div className="min-w-[820px] relative p-4">
          {mode && (
            <div className="pointer-events-none select-none absolute inset-0 flex items-center justify-center overflow-hidden z-10">
              <span
                className={`whitespace-nowrap font-black tracking-widest -rotate-12 ${
                  isConflict ? 'text-red-600/15 text-7xl' : 'text-slate-500/10 text-8xl'
                }`}
              >
                {isConflict ? 'ÇAKIŞMA VAR · TASLAK' : 'TASLAK / DRAFT'}
              </span>
            </div>
          )}

          {/* Gün başlıkları: tarih + çalışma günü */}
          <div className="flex ml-72 border-b border-slate-200 text-[10px] text-slate-500">
            {Array.from({ length: dayCount }).map((_, i) => {
              const d = new Date(rangeStart.getTime() + i * DAY_MS);
              const weekend = d.getDay() === 0 || d.getDay() === 6;
              return (
                <div
                  key={i}
                  className={`flex-1 text-center py-1 border-l border-slate-100 ${weekend ? 'bg-amber-50 text-amber-700' : ''}`}
                >
                  <div className="font-semibold text-slate-700">G{firstStudyDay + i}</div>
                  <div>{d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit' })}</div>
                </div>
              );
            })}
          </div>

          {steps.map((s) => {
            const st = new Date(s.planned_start).getTime();
            const en = new Date(s.planned_end).getTime();
            const left = pct(st);
            const width = Math.max(pct(en) - left, 0.8);
            const bio = s.is_biological_fixed_time;
            const flagged = conflictStepIds.has(s.id);
            const names = (s.assignees || []).map((a) => a.full_name).join(', ');

            return (
              <div
                key={s.id}
                className={`flex items-center border-b h-14 ${flagged ? 'bg-red-50 border-red-200' : 'border-slate-100'}`}
              >
                <div className="w-72 shrink-0 pr-3 text-xs pl-1">
                  <p
                    className={`font-medium truncate flex items-center gap-1 ${flagged ? 'text-red-800' : 'text-slate-800'}`}
                    title={s.step_name}
                  >
                    {flagged && <AlertTriangle className="w-3.5 h-3.5 text-red-600 shrink-0" />}
                    {bio && !flagged && <Lock className="w-3 h-3 text-blue-700 shrink-0" />}
                    <span className="font-mono text-[10px] px-1 rounded bg-slate-100 text-slate-600 shrink-0">
                      G{s.study_day}
                    </span>
                    <span className="truncate">{s.step_name}</span>
                  </p>
                  <p className="text-[10px] text-slate-500 truncate" title={names}>
                    {fmtDateTime(s.planned_start)} • {fmtMinutes(s.duration_minutes)} • {names || 'Atanmadı'}
                  </p>
                </div>
                <div className="relative flex-1 h-full">
                  {Array.from({ length: dayCount }).map((_, i) => (
                    <div
                      key={i}
                      className="absolute top-0 bottom-0 border-l border-slate-100"
                      style={{ left: `${(i / dayCount) * 100}%` }}
                    />
                  ))}
                  <div
                    className={`absolute top-4 h-6 rounded-sm min-w-[8px] ${
                      flagged ? 'ring-2 ring-red-300' : bio ? 'bg-blue-700 ring-2 ring-blue-300' : 'bg-slate-400'
                    }`}
                    style={{ left: `${left}%`, width: `${width}%`, ...(flagged ? { backgroundImage: STRIPES_RED } : {}) }}
                    title={`${s.step_name}\n${fmtDateTime(s.planned_start)} → ${fmtDateTime(s.planned_end)}${
                      bio ? `\nBiyolojik kilit (±${s.biological_tolerance_minutes} dk)` : ''
                    }${flagged ? '\n⚠ ÇAKIŞMA' : ''}`}
                  />
                </div>
              </div>
            );
          })}

          <div className="flex flex-wrap items-center gap-4 ml-72 mt-3 text-[11px] text-slate-600">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-blue-700 ring-2 ring-blue-300" /> Biyolojik kilitli
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-slate-400" /> Esnek
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ backgroundImage: STRIPES_RED }} /> Çakışan adım
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 bg-amber-50 border border-amber-200" /> Hafta sonu
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
