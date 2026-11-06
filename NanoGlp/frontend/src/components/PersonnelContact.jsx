import React, { useState } from 'react';
import { updatePersonnelContact, extractError } from '../services/api';

export default function PersonnelContact({ person, canEdit, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ email: '', phone: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      await updatePersonnelContact(person.personnel_id, { email: form.email.trim() || null, phone: form.phone.trim() || null });
      setEditing(false); await onSaved();
    } catch (err) { setError(extractError(err, 'İletişim bilgileri kaydedilemedi.')); }
    finally { setBusy(false); }
  };
  return <div className="text-xs px-3 py-2 space-y-1">
    <p>Kurumsal e-posta: {person.email || 'TBD'} · Telefon: {person.phone || 'TBD'}</p>
    {canEdit && !editing && <button type="button" className="text-blue-700" onClick={() => { setForm({email: person.email || '', phone: person.phone || ''}); setEditing(true); }}>İletişimi Düzenle</button>}
    {canEdit && editing && <form onSubmit={save} className="flex flex-wrap gap-2">
      <input aria-label="Kurumsal e-posta" type="email" value={form.email} onChange={e => setForm(prev => ({...prev, email: e.target.value}))} />
      <input aria-label="Telefon" type="tel" maxLength={60} value={form.phone} onChange={e => setForm(prev => ({...prev, phone: e.target.value}))} />
      <button disabled={busy} type="submit">Kaydet</button><button disabled={busy} type="button" onClick={() => setEditing(false)}>Vazgeç</button>
    </form>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
  </div>;
}
