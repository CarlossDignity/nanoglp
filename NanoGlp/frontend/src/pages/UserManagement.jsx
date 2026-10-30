import React, { useCallback, useEffect, useState } from 'react';
import {
  UserCog,
  UserPlus,
  Pencil,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Shield,
  X,
} from 'lucide-react';
import { getUsers, createUser, updateUser, deleteUser, extractError } from '../services/api';
import { useAuth } from '../state/AuthContext';
import { ROLE_LABEL, ROLE_SHORT } from '../utils/format';

const SELECTABLE_ROLES = [
  'SYSADMIN',
  'TFM',
  'STUDY_DIRECTOR',
  'PLANNING_COORDINATOR',
  'QA',
  'TECHNICIAN',
  'ANALYST',
];

const ROLE_BADGE = {
  SYSADMIN: 'bg-purple-50 text-purple-800 border-purple-200',
  TFM: 'bg-blue-50 text-blue-800 border-blue-200',
  STUDY_DIRECTOR: 'bg-indigo-50 text-indigo-800 border-indigo-200',
  PLANNING_COORDINATOR: 'bg-sky-50 text-sky-800 border-sky-200',
  QA: 'bg-amber-50 text-amber-800 border-amber-200',
  TECHNICIAN: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  ANALYST: 'bg-slate-100 text-slate-700 border-slate-200',
};

const EMPTY_FORM = {
  username: '',
  full_name: '',
  email: '',
  role: 'TECHNICIAN',
  password: '',
  max_daily_hours: 9,
  is_active: true,
};

const USERNAME_REGEX = /^[a-zA-Z0-9_.-]+$/;

export default function UserManagement({ onChanged }) {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getUsers();
      setUsers(res.data || []);
    } catch (err) {
      setError(extractError(err, 'Kullanıcı listesi alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreateModal = () => {
    setEditingUser(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setModalOpen(true);
  };

  const openEditModal = (u) => {
    setEditingUser(u);
    setForm({
      username: u.username,
      full_name: u.full_name,
      email: u.email || '',
      role: u.role,
      password: '',
      max_daily_hours: u.max_daily_hours ?? 9,
      is_active: u.is_active !== false,
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    const cleanUsername = form.username.trim();
    const cleanFullName = form.full_name.trim();

    if (!USERNAME_REGEX.test(cleanUsername)) {
      setFormError("Kullanıcı adı boşluk içeremez; yalnızca harf, rakam ve '_', '-', '.' karakterlerinden oluşabilir.");
      return;
    }
    if (!cleanFullName) {
      setFormError('Ad Soyad (Görünecek İsim) alanı zorunludur.');
      return;
    }
    if (!editingUser && !form.password.trim()) {
      setFormError('Yeni kullanıcı için şifre belirlenmesi zorunludur.');
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        username: cleanUsername.toLowerCase(),
        full_name: cleanFullName,
        email: form.email.trim() || null,
        role: form.role,
        max_daily_hours: Number(form.max_daily_hours) || 9,
        is_active: Boolean(form.is_active),
      };
      if (form.password.trim()) {
        payload.password = form.password.trim();
      }

      if (editingUser) {
        await updateUser(editingUser.id, payload);
      } else {
        await createUser(payload);
      }

      setModalOpen(false);
      await load();
      onChanged?.();
    } catch (err) {
      setFormError(extractError(err, 'Kullanıcı kaydedilemedi.'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (u) => {
    if (u.id === currentUser?.id) return;
    if (!window.confirm(`"${u.username}" (${u.full_name}) kullanıcısını silmek istediğinize emin misiniz?`)) {
      return;
    }
    setError(null);
    try {
      await deleteUser(u.id);
      await load();
      onChanged?.();
    } catch (err) {
      setError(extractError(err, 'Kullanıcı silinemedi.'));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Kullanıcı Yönetimi</h2>
          <p className="text-sm text-slate-500">
            Sistem kullanıcı hesapları, kurumsal kullanıcı adları, GLP rolleri ve şifre yönetimi (SYSADMIN & TFM).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-600 border border-slate-300 bg-white rounded-md px-3 py-2 hover:bg-slate-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Yenile
          </button>
          <button
            type="button"
            onClick={openCreateModal}
            className="flex items-center gap-2 bg-blue-700 hover:bg-blue-800 text-white text-sm font-medium rounded-md px-4 py-2 shadow-sm"
          >
            <UserPlus className="w-4 h-4" /> Yeni Kullanıcı Ekle
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>
      )}

      <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <UserCog className="w-4 h-4 text-blue-700" />
            <h3 className="text-sm font-semibold text-slate-800">Kayıtlı Kullanıcılar</h3>
          </div>
          <span className="text-xs text-slate-500">{users.length} hesap</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="text-left px-5 py-3 font-medium">Kullanıcı Adı</th>
                <th className="text-left px-5 py-3 font-medium">Ad Soyad (Görünen İsim)</th>
                <th className="text-left px-5 py-3 font-medium">Rol</th>
                <th className="text-left px-5 py-3 font-medium">Günlük Sınır</th>
                <th className="text-left px-5 py-3 font-medium">Durum</th>
                <th className="text-right px-5 py-3 font-medium">İşlemler</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && users.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-5 py-8 text-center text-sm text-slate-400">
                    Kullanıcılar yükleniyor…
                  </td>
                </tr>
              ) : (
                users.map((u) => {
                  const isSelf = u.id === currentUser?.id;
                  return (
                    <tr key={u.id} className="hover:bg-slate-50">
                      <td className="px-5 py-3 font-mono text-xs font-semibold text-slate-800">
                        {u.username}
                        {isSelf && (
                          <span className="ml-2 font-sans text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                            Siz
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-slate-900 font-medium">
                        {u.full_name}
                        {u.email && <p className="text-xs text-slate-400 font-normal">{u.email}</p>}
                      </td>
                      <td className="px-5 py-3">
                        <span
                          className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded border ${
                            ROLE_BADGE[u.role] || 'bg-slate-100 text-slate-700 border-slate-200'
                          }`}
                        >
                          <Shield className="w-3 h-3" />
                          {ROLE_SHORT[u.role] || u.role} · {ROLE_LABEL[u.role] || u.role}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-600">{u.max_daily_hours} saat / gün</td>
                      <td className="px-5 py-3">
                        {u.is_active !== false ? (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
                            <CheckCircle2 className="w-3.5 h-3.5" /> Aktif
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
                            <XCircle className="w-3.5 h-3.5" /> Pasif
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-right whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => openEditModal(u)}
                          className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-blue-700 px-2.5 py-1.5 rounded hover:bg-blue-50 transition"
                        >
                          <Pencil className="w-3.5 h-3.5" /> Düzenle
                        </button>
                        <button
                          type="button"
                          disabled={isSelf}
                          onClick={() => handleDelete(u)}
                          title={isSelf ? 'Kendi aktif oturum hesabınızı silemezsiniz' : 'Kullanıcıyı Sil'}
                          className="ml-1 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-red-700 px-2.5 py-1.5 rounded hover:bg-red-50 disabled:opacity-30 disabled:hover:bg-transparent transition"
                        >
                          <Trash2 className="w-3.5 h-3.5" /> Sil
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Yeni Kullanıcı / Düzenleme Modalı */}
      {modalOpen && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleSave}
            className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4 text-sm border border-slate-200"
          >
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">
                {editingUser ? `Kullanıcı Düzenle: ${editingUser.username}` : 'Yeni Kullanıcı Ekle'}
              </h3>
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
                aria-label="Kapat"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {formError && (
              <div className="p-2.5 bg-red-50 border border-red-200 text-red-700 rounded-md text-xs font-medium">
                {formError}
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                Kullanıcı Adı (Username) *
              </label>
              <input
                type="text"
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="Örn: invivo_3, dr_ahmet"
                className="w-full border border-slate-300 rounded-md px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
              <p className="text-[11px] text-slate-400 mt-1">
                Boşluksuz; yalnızca harf, rakam ve <span className="font-mono">_ - .</span> karakterleri.
              </p>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                Ad Soyad (Ekranda Görünecek İsim) *
              </label>
              <input
                type="text"
                required
                value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                placeholder="Örn: In Vivo Teknisyeni 3"
                className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Sistem Rolü *</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                >
                  {SELECTABLE_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r] || r}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Günlük Mesai Sınırı (Saat)</label>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={form.max_daily_hours}
                  onChange={(e) => setForm({ ...form, max_daily_hours: e.target.value })}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                {editingUser ? 'Yeni Şifre (değiştirmeyecekseniz boş bırakın)' : 'Şifre *'}
              </label>
              <input
                type="password"
                required={!editingUser}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={editingUser ? 'Mevcut şifre korunur' : 'En az 6 karakter'}
                className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>

            <div className="flex items-center justify-between pt-1">
              <label className="inline-flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  disabled={editingUser?.id === currentUser?.id}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Hesap Aktif (Sisteme giriş yapabilir)</span>
              </label>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="px-3 py-2 border border-slate-300 rounded-md text-xs font-medium text-slate-600 hover:bg-slate-50"
              >
                İptal
              </button>
              <button
                type="submit"
                disabled={saving}
                className="px-4 py-2 bg-blue-700 hover:bg-blue-800 text-white rounded-md text-xs font-semibold disabled:bg-blue-400"
              >
                {saving ? 'Kaydediliyor…' : editingUser ? 'Güncelle' : 'Kullanıcı Oluştur'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
