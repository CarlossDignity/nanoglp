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
  Plus,
  Save,
  Eye,
  KeyRound,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import {
  getUsers,
  createUser,
  updateUser,
  deleteUser,
  getRoles,
  createRole,
  updateRole,
  deleteRole,
  extractError,
} from '../services/api';
import { useAuth } from '../state/AuthContext';
import { usePreferences } from '../state/PreferencesContext';
import { ROLE_LABEL, ROLE_SHORT } from '../utils/format';

export const MENU_DEFINITIONS = [
  { key: 'dashboard', label: 'Yönetici Paneli' },
  { key: 'samples', label: 'Numune & Çalışma Takip' },
  { key: 'upload', label: 'Belge Yükleme' },
  { key: 'planning', label: 'Çoklu Çalışma Planlama' },
  { key: 'personnel', label: 'Personel İş Yükü' },
  { key: 'studies', label: 'GLP Çalışmaları' },
  { key: 'conflicts', label: 'Açık Çakışmalar' },
  { key: 'my_tasks', label: 'Bugünkü Görevlerim' },
  { key: 'users', label: 'Kullanıcı Yönetimi' },
  { key: 'settings', label: 'Sistem Ayarları' },
];

const DEFAULT_ROLE_OPTIONS = [
  { role_code: 'EXECUTIVE', role_label: 'Üst Yönetim (GM / GMY)' },
  { role_code: 'SYSADMIN', role_label: 'Sistem Yöneticisi (SYSADMIN)' },
  { role_code: 'TFM', role_label: 'Test Tesisi Yöneticisi (TFM)' },
  { role_code: 'STUDY_DIRECTOR', role_label: 'Çalışma Yöneticisi (SD)' },
  { role_code: 'PLANNING_COORDINATOR', role_label: 'Planlama Koordinatörü (PK)' },
  { role_code: 'QA', role_label: 'Kalite Güvence (QA)' },
  { role_code: 'TECHNICIAN', role_label: 'Teknisyen' },
  { role_code: 'ANALYST', role_label: 'Analist' },
  { role_code: 'SALES', role_label: 'Satış' },
  { role_code: 'TRM_KABUL', role_label: 'TRM Kabul (Test ve Referans Madde Kabul)' },
];

const ROLE_BADGE = {
  EXECUTIVE: 'bg-slate-50 text-slate-700 border-slate-200',
  SALES: 'bg-slate-50 text-slate-700 border-slate-200',
  TRM_KABUL: 'bg-slate-50 text-slate-700 border-slate-200',
  SYSADMIN: 'bg-slate-50 text-slate-700 border-slate-200',
  TFM: 'bg-slate-50 text-slate-700 border-slate-200',
  STUDY_DIRECTOR: 'bg-slate-50 text-slate-700 border-slate-200',
  PLANNING_COORDINATOR: 'bg-slate-50 text-slate-700 border-slate-200',
  QA: 'bg-slate-50 text-slate-700 border-slate-200',
  TECHNICIAN: 'bg-slate-50 text-slate-700 border-slate-200',
  ANALYST: 'bg-slate-50 text-slate-700 border-slate-200',
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

const EMPTY_ROLE_FORM = {
  role_code: '',
  role_label: '',
  allowed_menus: ['dashboard', 'planning', 'personnel', 'studies', 'conflicts'],
  is_read_only: true,
};

const USERNAME_REGEX = /^[a-zA-Z0-9_.-]+$/;
const ROLE_CODE_REGEX = /^[A-Z0-9_]{2,40}$/;

export default function UserManagement({ onChanged }) {
  const { user: currentUser, isSysAdmin, refreshUser } = useAuth();
  const { t, tr, lang } = usePreferences();
  const [activeTab, setActiveTab] = useState('users'); // 'users' | 'roles'
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [roleDrafts, setRoleDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  // Kullanıcı modalı state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);

  // Yeni Rol modalı state (SYSADMIN)
  const [roleModalOpen, setRoleModalOpen] = useState(false);
  const [newRoleForm, setNewRoleForm] = useState(EMPTY_ROLE_FORM);
  const [roleFormError, setRoleFormError] = useState(null);
  const [savingRoleCode, setSavingRoleCode] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [usersRes, rolesRes] = await Promise.all([
        getUsers(),
        getRoles().catch(() => ({ data: [] })),
      ]);
      setUsers(usersRes.data || []);
      const roleList = rolesRes.data?.length ? rolesRes.data : DEFAULT_ROLE_OPTIONS;
      setRoles(roleList);
      const drafts = {};
      roleList.forEach((r) => {
        drafts[r.role_code] = {
          role_label: r.role_label,
          allowed_menus: Array.isArray(r.allowed_menus) ? [...r.allowed_menus] : ['dashboard'],
          is_read_only: Boolean(r.is_read_only),
        };
      });
      setRoleDrafts(drafts);
    } catch (err) {
      setError(extractError(err, 'Kullanıcı ve rol listesi alınamadı.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreateModal = (preset = null) => {
    setEditingUser(null);
    setForm(preset ? { ...EMPTY_FORM, ...preset } : EMPTY_FORM);
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
    setNotice(null);
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
        setNotice(`'${cleanUsername}' kullanıcısı güncellendi.`);
      } else {
        await createUser(payload);
        setNotice(`'${cleanUsername}' (${cleanFullName}) kullanıcısı oluşturuldu.`);
      }

      setModalOpen(false);
      await load();
      await refreshUser?.();
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
    setNotice(null);
    try {
      await deleteUser(u.id);
      setNotice(`'${u.username}' kullanıcısı silindi.`);
      await load();
      onChanged?.();
    } catch (err) {
      setError(extractError(err, 'Kullanıcı silinemedi.'));
    }
  };

  // --- ROL VE EKRAN YETKİ MATRİSİ İŞLEMLERİ (SYSADMIN) ---
  const toggleRoleMenu = (roleCode, menuKey) => {
    setRoleDrafts((prev) => {
      const curr = prev[roleCode] || { allowed_menus: [], is_read_only: false, role_label: roleCode };
      const exists = curr.allowed_menus.includes(menuKey);
      const nextMenus = exists
        ? curr.allowed_menus.filter((m) => m !== menuKey)
        : [...curr.allowed_menus, menuKey];
      return {
        ...prev,
        [roleCode]: {
          ...curr,
          allowed_menus: nextMenus,
        },
      };
    });
  };

  const toggleRoleReadOnly = (roleCode) => {
    if (roleCode === 'SYSADMIN') return;
    setRoleDrafts((prev) => {
      const curr = prev[roleCode] || { allowed_menus: [], is_read_only: false, role_label: roleCode };
      return {
        ...prev,
        [roleCode]: {
          ...curr,
          is_read_only: !curr.is_read_only,
        },
      };
    });
  };

  const handleSaveRolePermission = async (roleCode) => {
    const draft = roleDrafts[roleCode];
    if (!draft) return;
    setSavingRoleCode(roleCode);
    setError(null);
    setNotice(null);
    try {
      await updateRole(roleCode, {
        role_label: draft.role_label,
        allowed_menus: draft.allowed_menus,
        is_read_only: draft.is_read_only,
      });
      await load();
      await refreshUser?.();
      setNotice(`'${draft.role_label}' (${roleCode}) rolünün ekran yetkileri ve izleme modu güncellendi.`);
    } catch (err) {
      setError(extractError(err, 'Rol yetkileri güncellenemedi.'));
    } finally {
      setSavingRoleCode(null);
    }
  };

  const handleCreateNewRole = async (e) => {
    e.preventDefault();
    const code = newRoleForm.role_code.trim().toUpperCase().replace(/\s+/g, '_');
    const label = newRoleForm.role_label.trim();
    if (!ROLE_CODE_REGEX.test(code)) {
      setRoleFormError("Rol kodu yalnızca büyük İngilizce harf, rakam ve '_' içerebilir (Örn: GMY_OPERASYON).");
      return;
    }
    if (!label) {
      setRoleFormError('Rolün Türkçe görünen adı zorunludur.');
      return;
    }
    if (!newRoleForm.allowed_menus.length) {
      setRoleFormError('En az 1 ekran yetkisi seçmelisiniz.');
      return;
    }

    setSavingRoleCode('NEW');
    setRoleFormError(null);
    setNotice(null);
    try {
      await createRole({
        role_code: code,
        role_label: label,
        allowed_menus: newRoleForm.allowed_menus,
        is_read_only: Boolean(newRoleForm.is_read_only),
      });
      setRoleModalOpen(false);
      setNewRoleForm(EMPTY_ROLE_FORM);
      await load();
      setNotice(`Yeni '${label}' (${code}) rolü oluşturuldu.`);
    } catch (err) {
      setRoleFormError(extractError(err, 'Yeni rol oluşturulamadı.'));
    } finally {
      setSavingRoleCode(null);
    }
  };

  const handleDeleteCustomRole = async (r) => {
    if (r.is_system) return;
    if (!window.confirm(`"${r.role_label}" (${r.role_code}) rolünü silmek istiyor musunuz?`)) return;
    setError(null);
    setNotice(null);
    try {
      await deleteRole(r.role_code);
      await load();
      setNotice(`'${r.role_code}' rolü silindi.`);
    } catch (err) {
      setError(extractError(err, 'Rol silinemedi.'));
    }
  };

  const roleOptions = roles.length ? roles : DEFAULT_ROLE_OPTIONS;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Kullanıcı ve Rol Yetkileri Yönetimi</h2>
          <p className="text-sm text-slate-500">
            Kurumsal kullanıcı hesapları, Üst Yönetim (GM / GMY) izleme profilleri ve dinamik sol menü ekran yetki matrisi.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {isSysAdmin && (
            <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-xs">
              <button
                type="button"
                onClick={() => setActiveTab('users')}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                  activeTab === 'users'
                    ? 'bg-slate-900 text-white shadow-xs'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <UserCog className="w-3.5 h-3.5" />
                <span>Kullanıcı Hesapları ({users.length})</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('roles')}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition ${
                  activeTab === 'roles'
                    ? 'bg-slate-900 text-white shadow-xs'
                    : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                <span>Rol Yönetimi ve Ekran Yetki Matrisi ({roleOptions.length})</span>
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={load}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-600 border border-slate-300 bg-white rounded-md px-3 py-2 hover:bg-slate-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Yenile
          </button>

          {activeTab === 'users' ? (
            <>
              <button
                type="button"
                onClick={() =>
                  openCreateModal({
                    username: 'ozkan.bey',
                    full_name: 'Özkan Bey (Üst Yönetim — GM / GMY)',
                    role: 'EXECUTIVE',
                    password: 'NanoLab2026!',
                  })
                }
                className="flex items-center gap-1.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-800 border border-indigo-200 text-xs font-semibold rounded-md px-3 py-2 transition"
                title="Sadece 5 takip ekranını gören Salt Okunur Üst Yönetim (GM / GMY) hesabını hazır şablonla oluştur"
              >
                <Sparkles className="w-3.5 h-3.5 text-indigo-700" />
                <span>Hazır Üst Yönetim (GM/GMY) Ekle</span>
              </button>
              <button
                type="button"
                onClick={() => openCreateModal()}
                className="flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-md px-4 py-2 shadow-xs"
              >
                <UserPlus className="w-4 h-4" /> Yeni Kullanıcı Ekle
              </button>
            </>
          ) : (
            isSysAdmin && (
              <button
                type="button"
                onClick={() => {
                  setRoleFormError(null);
                  setNewRoleForm(EMPTY_ROLE_FORM);
                  setRoleModalOpen(true);
                }}
                className="flex items-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-md px-4 py-2 shadow-xs"
              >
                <Plus className="w-4 h-4" />
                <span>Yeni Rol Oluştur</span>
              </button>
            )
          )}
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-md bg-red-50 border border-red-200 text-sm text-red-700">{error}</div>
      )}
      {notice && (
        <div className="p-3 rounded-md bg-emerald-50 border border-emerald-200 text-xs font-semibold text-emerald-900">
          {notice}
        </div>
      )}

      {/* ===================================================================== */}
      {/* BÖLÜM A: KULLANICI HESAPLARI                                          */}
      {/* ===================================================================== */}
      {activeTab === 'users' && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <UserCog className="w-4 h-4 text-slate-500" />
              <h3 className="text-sm font-semibold text-slate-800">Kayıtlı Kullanıcılar</h3>
            </div>
            <span className="text-xs text-slate-500">{users.length} hesap</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left px-5 py-3 font-semibold">Kullanıcı Adı</th>
                  <th className="text-left px-5 py-3 font-semibold">Ad Soyad (Görünen İsim)</th>
                  <th className="text-left px-5 py-3 font-semibold">Rol & Yetki Modu</th>
                  <th className="text-left px-5 py-3 font-semibold">Açık Menü Sayısı</th>
                  <th className="text-left px-5 py-3 font-semibold">Durum</th>
                  <th className="text-right px-5 py-3 font-semibold">İşlemler</th>
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
                    const rInfo = roleOptions.find((r) => r.role_code === u.role);
                    const displayLabel = u.role_label || rInfo?.role_label || ROLE_LABEL[u.role] || u.role;
                    const readOnlyFlag = u.is_read_only ?? rInfo?.is_read_only ?? (u.role === 'QA' || u.role === 'EXECUTIVE');
                    const menuCount = u.allowed_menus?.length ?? rInfo?.allowed_menus?.length ?? '—';

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
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span
                              className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded border ${
                                ROLE_BADGE[u.role] || 'bg-slate-100 text-slate-700 border-slate-200'
                              }`}
                            >
                              <Shield className="w-3 h-3" />
                              {ROLE_SHORT[u.role] || u.role} · {displayLabel}
                            </span>
                            {readOnlyFlag && (
                              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                                <Eye className="w-3 h-3" /> Salt Okunur
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-5 py-3 text-xs text-slate-600">{menuCount} ekran</td>
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
      )}

      {/* ===================================================================== */}
      {/* BÖLÜM B: ROL YÖNETİMİ VE EKRAN YETKİ MATRİSİ (SADECE SYSADMIN)         */}
      {/* ===================================================================== */}
      {isSysAdmin && activeTab === 'roles' && (
        <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-slate-500" />
                <h3 className="text-sm font-semibold text-slate-800">
                  Rol Yönetimi ve Sol Menü Ekran Yetki Matrisi (SYSADMIN)
                </h3>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Her rolün sol menüde görebileceği ekranları ve <strong>Salt Okunur (İzleme Modu)</strong> durumunu işaretleyip{' '}
                <strong>Kaydet</strong> butonuna basın.
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-600 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-3 font-semibold min-w-[210px]">Rol Kodu & Görünen Ad</th>
                  <th className="text-center px-2.5 py-3 font-semibold bg-amber-50/60 text-amber-900">
                    Salt Okunur
                    <span className="block text-[9px] font-normal text-amber-700">(İzleme Modu)</span>
                  </th>
                  {MENU_DEFINITIONS.map((m) => (
                    <th key={m.key} className="text-center px-2 py-3 font-semibold min-w-[78px]">
                      {m.label}
                    </th>
                  ))}
                  <th className="text-right px-4 py-3 font-semibold">İşlem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {roleOptions.map((r) => {
                  const draft = roleDrafts[r.role_code] || {
                    role_label: r.role_label,
                    allowed_menus: r.allowed_menus || [],
                    is_read_only: Boolean(r.is_read_only),
                  };
                  const isSavingThis = savingRoleCode === r.role_code;

                  return (
                    <tr key={r.role_code} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3">
                        <div className="font-mono font-bold text-slate-900">{r.role_code}</div>
                        <input
                          type="text"
                          value={draft.role_label}
                          onChange={(e) =>
                            setRoleDrafts((prev) => ({
                              ...prev,
                              [r.role_code]: { ...draft, role_label: e.target.value },
                            }))
                          }
                          className="mt-1 w-full border border-slate-200 rounded px-2 py-1 text-xs text-slate-700 focus:outline-none focus:ring-1 focus:ring-blue-600"
                        />
                      </td>

                      <td className="px-2.5 py-3 text-center bg-amber-50/30">
                        <input
                          type="checkbox"
                          aria-label={`${r.role_code} Salt Okunur`}
                          disabled={r.role_code === 'SYSADMIN'}
                          checked={Boolean(draft.is_read_only)}
                          onChange={() => toggleRoleReadOnly(r.role_code)}
                          className="w-4 h-4 accent-amber-600 rounded cursor-pointer disabled:opacity-40"
                        />
                      </td>

                      {MENU_DEFINITIONS.map((m) => {
                        const checked = draft.allowed_menus.includes(m.key);
                        const lockedSysAdminUsers = r.role_code === 'SYSADMIN' && m.key === 'users';
                        return (
                          <td key={m.key} className="px-2 py-3 text-center">
                            <input
                              type="checkbox"
                              aria-label={`${r.role_code} - ${m.label}`}
                              disabled={lockedSysAdminUsers}
                              checked={checked}
                              onChange={() => toggleRoleMenu(r.role_code, m.key)}
                              className="w-4 h-4 accent-blue-700 rounded cursor-pointer disabled:opacity-40"
                            />
                          </td>
                        );
                      })}

                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={isSavingThis}
                            onClick={() => handleSaveRolePermission(r.role_code)}
                            className="inline-flex items-center gap-1 bg-slate-900 hover:bg-slate-800 text-white font-semibold px-3 py-1.5 rounded-md shadow-xs disabled:opacity-50 transition"
                          >
                            <Save className="w-3.5 h-3.5" />
                            <span>{isSavingThis ? 'Kaydediliyor…' : 'Kaydet'}</span>
                          </button>
                          {!r.is_system && (
                            <button
                              type="button"
                              onClick={() => handleDeleteCustomRole(r)}
                              title="Özel rolü sil"
                              className="p-1.5 text-slate-400 hover:text-red-700 hover:bg-red-50 rounded transition"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Yeni Kullanıcı / Düzenleme Modalı */}
      {modalOpen && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleSave}
            className="bg-white rounded-lg shadow-xl max-w-md w-full p-6 space-y-4 text-sm border border-slate-200"
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
                placeholder="Örn: ozkan.bey, anoop, invivo_3"
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
                placeholder="Örn: Özkan Bey (Genel Müdür)"
                className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Sistem Rolü *</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-600"
                >
                  {roleOptions.map((r) => (
                    <option key={r.role_code} value={r.role_code}>
                      {r.role_label} ({r.role_code})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Günlük Maks. Saat
                </label>
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
                E-posta (Opsiyonel)
              </label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="Boş bırakılabilir"
                className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                {editingUser ? 'Yeni Şifre (Değiştirmek istemiyorsanız boş bırakın)' : 'Şifre *'}
              </label>
              <input
                type="password"
                required={!editingUser}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder={editingUser ? '•••••••• (Değişmeyecek)' : 'Örn: NanoLab2026!'}
                className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              />
            </div>

            <label className="flex items-center gap-2 text-xs text-slate-700 pt-1">
              <input
                type="checkbox"
                checked={form.is_active}
                disabled={editingUser?.id === currentUser?.id}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                className="rounded border-slate-300 text-blue-700 focus:ring-blue-600"
              />
              <span>Hesap Aktif (Sisteme giriş yapabilir ve görev atanabilir)</span>
            </label>

            <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-md"
              >
                İptal
              </button>
              <button
                type="submit"
                disabled={saving}
                className="px-4 py-2 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white rounded-md disabled:opacity-50"
              >
                {saving ? 'Kaydediliyor…' : editingUser ? 'Değişiklikleri Kaydet' : 'Kullanıcı Oluştur'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* + Yeni Rol Oluştur Modalı (Sadece SYSADMIN) */}
      {roleModalOpen && isSysAdmin && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateNewRole}
            className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6 space-y-4 text-sm border border-slate-200"
          >
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900">+ Yeni Rol ve Ekran Yetkisi Oluştur</h3>
              <button
                type="button"
                onClick={() => setRoleModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
                aria-label="Kapat"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {roleFormError && (
              <div className="p-2.5 bg-red-50 border border-red-200 text-red-700 rounded-md text-xs font-medium">
                {roleFormError}
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Rol Kodu (Büyük Harf) *
                </label>
                <input
                  type="text"
                  required
                  value={newRoleForm.role_code}
                  onChange={(e) =>
                    setNewRoleForm({ ...newRoleForm, role_code: e.target.value.toUpperCase() })
                  }
                  placeholder="Örn: GMY_OPERASYON"
                  className="w-full border border-slate-300 rounded-md px-3 py-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Rol Görünen Adı (Türkçe) *
                </label>
                <input
                  type="text"
                  required
                  value={newRoleForm.role_label}
                  onChange={(e) => setNewRoleForm({ ...newRoleForm, role_label: e.target.value })}
                  placeholder="Örn: Genel Müdür Yardımcısı"
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-blue-600"
                />
              </div>
            </div>

            <label className="flex items-center gap-2.5 p-3 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-900 cursor-pointer">
              <input
                type="checkbox"
                checked={newRoleForm.is_read_only}
                onChange={(e) => setNewRoleForm({ ...newRoleForm, is_read_only: e.target.checked })}
                className="w-4 h-4 accent-amber-600 rounded"
              />
              <span>
                <strong>Salt Okunur (İzleme Modu):</strong> Aktif edilirse bu rol sadece izleme ve Study Plan (.docx)
                raporu indirme yapabilir; planlama, onaylama veya veri silme yapamaz.
              </span>
            </label>

            <div>
              <p className="text-xs font-semibold text-slate-700 mb-2">
                Sol Menüde Görebileceği Ekranlar:
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {MENU_DEFINITIONS.map((m) => {
                  const checked = newRoleForm.allowed_menus.includes(m.key);
                  return (
                    <label
                      key={m.key}
                      className={`flex items-center gap-2 px-3 py-2 rounded-md border text-xs cursor-pointer transition ${
                        checked
                          ? 'bg-blue-50 border-blue-300 text-blue-900 font-semibold'
                          : 'bg-white border-slate-200 text-slate-600'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          const next = checked
                            ? newRoleForm.allowed_menus.filter((k) => k !== m.key)
                            : [...newRoleForm.allowed_menus, m.key];
                          setNewRoleForm({ ...newRoleForm, allowed_menus: next });
                        }}
                        className="accent-blue-700 rounded"
                      />
                      <span>{m.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setRoleModalOpen(false)}
                className="px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-md"
              >
                İptal
              </button>
              <button
                type="submit"
                disabled={savingRoleCode === 'NEW'}
                className="px-4 py-2 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white rounded-md disabled:opacity-50"
              >
                {savingRoleCode === 'NEW' ? 'Oluşturuluyor…' : 'Rolü Oluştur'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
