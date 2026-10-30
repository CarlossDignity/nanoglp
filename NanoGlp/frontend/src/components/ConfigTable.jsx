import React, { useState } from 'react';
import { Pencil, Trash2, Plus, Save, X } from 'lucide-react';

/**
 * Satır içi düzenlenebilir yapılandırma tablosu.
 * columns: [{ key, label, type: 'text'|'number'|'select', options?, min?, max?, suffix?, className? }]
 * validate(values, editingId) → hata metni | null
 */
export default function ConfigTable({
  title, description, icon: Icon, columns, rows, newRowDefaults,
  onAdd, onUpdate, onDelete, validate, canEdit, lockedReason, emptyText,
}) {
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({});
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const startEdit = (row) => { setAdding(false); setEditingId(row.id); setDraft(row); setError(null); };
  const startAdd = () => { setEditingId(null); setAdding(true); setDraft(newRowDefaults); setError(null); };
  const cancel = () => { setEditingId(null); setAdding(false); setError(null); };

  const normalize = (values) =>
    Object.fromEntries(
      columns.map((c) => [c.key, c.type === 'number' ? Number(values[c.key]) : String(values[c.key] ?? '').trim()])
    );

  const save = () => {
    const values = normalize(draft);
    const err = validate(values, editingId);
    if (err) return setError(err);
    adding ? onAdd(values) : onUpdate(editingId, values);
    cancel();
  };

  const renderInput = (col) => {
    const common = {
      value: draft[col.key] ?? '',
      onChange: (e) => setDraft((d) => ({ ...d, [col.key]: e.target.value })),
      onKeyDown: (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') cancel(); },
      className: 'w-full border border-slate-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600',
      'aria-label': col.label,
    };
    if (col.type === 'select') {
      return (
        <select {...common} className={`${common.className} bg-white`}>
          {col.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    return (
      <div className="flex items-center gap-1.5">
        <input {...common} type={col.type === 'number' ? 'number' : 'text'} min={col.min} max={col.max} step={col.type === 'number' ? 1 : undefined} />
        {col.suffix && <span className="text-xs text-slate-500 whitespace-nowrap">{col.suffix}</span>}
      </div>
    );
  };

  const editorRow = (key) => (
    <tr key={key} className="bg-blue-50/60">
      {columns.map((c) => <td key={c.key} className="px-4 py-2 align-top">{renderInput(c)}</td>)}
      <td className="px-4 py-2 text-right whitespace-nowrap align-top">
        <button onClick={save} className="inline-flex items-center gap-1 text-xs font-medium bg-blue-700 hover:bg-blue-800 text-white rounded px-2.5 py-1.5">
          <Save className="w-3.5 h-3.5" /> Kaydet
        </button>
        <button onClick={cancel} className="ml-1 inline-flex items-center text-xs text-slate-600 border border-slate-300 rounded px-2 py-1.5 hover:bg-white" aria-label="İptal">
          <X className="w-3.5 h-3.5" />
        </button>
      </td>
    </tr>
  );

  const busy = adding || editingId !== null;

  return (
    <section className="bg-white border border-slate-200 rounded-lg shadow-sm">
      <div className="px-5 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
        <div className="flex items-start gap-2.5">
          {Icon && <Icon className="w-4 h-4 text-blue-700 mt-0.5" />}
          <div>
            <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
            {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
          </div>
        </div>
        <button
          onClick={startAdd}
          disabled={!canEdit || busy}
          title={!canEdit ? lockedReason : undefined}
          className="shrink-0 inline-flex items-center gap-1.5 text-xs font-medium border border-blue-700 text-blue-700 hover:bg-blue-50 disabled:border-slate-300 disabled:text-slate-400 disabled:hover:bg-transparent rounded-md px-3 py-1.5"
        >
          <Plus className="w-3.5 h-3.5" /> Ekle
        </button>
      </div>

      {error && <div className="mx-5 mt-3 p-2.5 rounded bg-red-50 border border-red-200 text-xs text-red-700">{error}</div>}

      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            {columns.map((c) => <th key={c.key} className={`text-left px-4 py-2.5 font-medium ${c.className || ''}`}>{c.label}</th>)}
            <th className="w-36" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {adding && editorRow('__new')}
          {rows.length === 0 && !adding && (
            <tr><td colSpan={columns.length + 1} className="px-4 py-6 text-center text-xs text-slate-400">{emptyText}</td></tr>
          )}
          {rows.map((row) =>
            editingId === row.id ? editorRow(row.id) : (
              <tr key={row.id} className="hover:bg-slate-50">
                {columns.map((c) => (
                  <td key={c.key} className="px-4 py-2.5 text-slate-700">
                    {c.type === 'number' ? <span className="font-semibold text-slate-900">{row[c.key]}</span> : row[c.key]}
                    {c.suffix && <span className="text-xs text-slate-500 ml-1">{c.suffix}</span>}
                  </td>
                ))}
                <td className="px-4 py-2.5 text-right whitespace-nowrap">
                  <button
                    onClick={() => startEdit(row)}
                    disabled={!canEdit || busy}
                    title={!canEdit ? lockedReason : 'Düzenle'}
                    className="p-1.5 rounded text-slate-500 hover:text-blue-700 hover:bg-blue-50 disabled:opacity-30 disabled:hover:bg-transparent"
                    aria-label="Düzenle"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => onDelete(row.id)}
                    disabled={!canEdit || busy}
                    title={!canEdit ? lockedReason : 'Sil'}
                    className="p-1.5 rounded text-slate-500 hover:text-red-700 hover:bg-red-50 disabled:opacity-30 disabled:hover:bg-transparent"
                    aria-label="Sil"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            )
          )}
        </tbody>
      </table>
    </section>
  );
}
