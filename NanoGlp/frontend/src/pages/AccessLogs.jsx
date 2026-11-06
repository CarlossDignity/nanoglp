import React, { useEffect, useState } from 'react';
import { getAccessLogs, extractError } from '../services/api';
import { useAuth } from '../state/AuthContext';

const localDate = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/Istanbul', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());
export const formatAccessTime = value => new Intl.DateTimeFormat('tr-TR', {
  timeZone: 'Europe/Istanbul', dateStyle: 'short', timeStyle: 'medium',
}).format(new Date(value));
const inputClass = 'rounded border border-slate-300 bg-white px-2 py-1';
const buttonClass = 'rounded border border-slate-300 px-3 py-1 disabled:opacity-50';

export default function AccessLogs() {
  const { role } = useAuth();
  const allowed = ['SYSADMIN', 'ADMIN'].includes(role);
  const [form, setForm] = useState(() => ({ user: '', event_type: '', date_from: localDate(), date_to: localDate() }));
  const [query, setQuery] = useState(() => ({ ...form, page: 1, page_size: 50 }));
  const [data, setData] = useState({ items: [], total: 0 });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const change = key => e => setForm(previous => ({ ...previous, [key]: e.target.value }));

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    setLoading(true);
    setError('');
    const params = Object.fromEntries(Object.entries(query).filter(([, value]) => value !== ''));
    getAccessLogs(params)
      .then(response => { if (active) setData(response.data); })
      .catch(e => { if (active) setError(extractError(e, 'Kayıtlar alınamadı.')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [allowed, query]);

  if (!allowed) return <p>Erişim yalnız sistem yöneticilerine açıktır.</p>;
  return <div className="space-y-4">
    <h2 className="text-xl font-semibold">Giriş / Çıkış Kayıtları</h2>
    <p className="text-sm text-slate-600">
      Saatler ve tarih filtreleri: Europe/Istanbul. Çıkış kaydı kullanıcının Çıkış Yap eylemidir;
      tarayıcı kapanışını veya token iptalini göstermez.
    </p>
    <form className="flex flex-wrap items-center gap-3" onSubmit={e => {
      e.preventDefault();
      setQuery({ ...form, page: 1, page_size: 50 });
    }}>
      <input className={inputClass} aria-label="Kullanıcı" placeholder="Kullanıcı / ad / e-posta"
        value={form.user} onChange={change('user')} />
      <select className={inputClass} aria-label="Olay türü" value={form.event_type} onChange={change('event_type')}>
        <option value="">Tüm olaylar</option>
        {['LOGIN', 'LOGIN_FAILED', 'LOGOUT'].map(value => <option key={value} value={value}>{value}</option>)}
      </select>
      <label>Başlangıç <input className={inputClass} aria-label="Başlangıç tarihi" type="date"
        value={form.date_from} onChange={change('date_from')} /></label>
      <label>Bitiş <input className={inputClass} aria-label="Bitiş tarihi" type="date"
        value={form.date_to} onChange={change('date_to')} /></label>
      <button className={buttonClass} type="submit" disabled={loading}>Filtrele</button>
    </form>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    <div className="overflow-x-auto rounded border bg-white">
      <table className="w-full text-sm">
        <thead><tr>
          {['Tarih / saat', 'Olay', 'Kullanıcı', 'Denenen kimlik', 'E-posta', 'Ad Soyad', 'Rol', 'IP', 'Tarayıcı']
            .map(heading => <th key={heading} className="text-left p-2">{heading}</th>)}
        </tr></thead>
        <tbody>{data.items.map(row => <tr key={row.id}>
          {[formatAccessTime(row.created_at), row.event_type, row.username, row.attempted_identifier,
            row.email, row.full_name, row.role, row.ip_address, row.user_agent]
            .map((value, index) => <td key={index} className="p-2 border-t break-all">{value || '—'}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
    {loading && <p>Yükleniyor…</p>}
    {!loading && !data.items.length && <p>Kayıt bulunmuyor.</p>}
    <div className="flex gap-4 items-center">
      <button className={buttonClass} disabled={loading || query.page === 1}
        onClick={() => setQuery(previous => ({ ...previous, page: previous.page - 1 }))}>Önceki</button>
      <span>{query.page}. sayfa · {data.total} kayıt</span>
      <button className={buttonClass} disabled={loading || query.page * query.page_size >= data.total}
        onClick={() => setQuery(previous => ({ ...previous, page: previous.page + 1 }))}>Sonraki</button>
    </div>
  </div>;
}
