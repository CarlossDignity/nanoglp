export const todayISO = () => {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d - tz).toISOString().slice(0, 10);
};

const isEnLang = () => {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem('nanolab_lang') === 'en';
  } catch {
    return false;
  }
};

export const fmtDateTime = (iso) =>
  new Date(iso).toLocaleString(isEnLang() ? 'en-GB' : 'tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });

export const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString(isEnLang() ? 'en-GB' : 'tr-TR', { day: '2-digit', month: 'short', year: 'numeric' });

export const fmtTime = (iso) =>
  new Date(iso).toLocaleTimeString(isEnLang() ? 'en-GB' : 'tr-TR', { hour: '2-digit', minute: '2-digit' });

const WEEKDAY_ABBR_TR = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
const WEEKDAY_ABBR_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** "08.08.2026 Cmt" biçiminde tarih + kısa gün adı */
export const fmtDateWeekday = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const abbr = isEnLang() ? WEEKDAY_ABBR_EN[d.getDay()] : WEEKDAY_ABBR_TR[d.getDay()];
  return `${dd}.${mm}.${d.getFullYear()} ${abbr}`;
};

export const fmtMinutes = (m) => {
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (isEnLang()) {
    return h ? `${h} hr${r ? ` ${r} min` : ''}` : `${r} min`;
  }
  return h ? `${h} sa${r ? ` ${r} dk` : ''}` : `${r} dk`;
};

/** "3 gün sonra", "Bugün", "2 saat sonra" gibi göreli metin */
export const relativeFromNow = (iso) => {
  const diffMs = new Date(iso) - new Date();
  const hours = Math.round(diffMs / 3600000);
  if (isEnLang()) {
    if (hours < 0) return 'Ongoing';
    if (hours < 24) return `in ${hours} hr`;
    return `in ${Math.round(hours / 24)} days`;
  }
  if (hours < 0) return 'Devam ediyor';
  if (hours < 24) return `${hours} saat sonra`;
  return `${Math.round(hours / 24)} gün sonra`;
};

export const conflictTypeLabel = {
  PERSONNEL_OVERLAP: 'Personel Çakışması / 9 Saat Aşımı',
  BIOLOGICAL_TIME_VIOLATION: 'Biyolojik Zaman Kilidi İhlali',
  EQUIPMENT_OVERLAP: 'Cihaz Rezervasyon Çakışması',
  ROOM_CAPACITY_EXCEEDED: 'Oda Kapasitesi Aşımı',
  CALIBRATION_EXPIRED: 'Kalibrasyon Süresi Dolmuş',
  QUALIFICATION_MISMATCH: 'Atanacak Personel Yok / Yetkinlik',
};

export const ROLE_LABEL = {
  SYSADMIN: 'Sistem Yöneticisi (SYSADMIN)',
  EXECUTIVE: 'Üst Yönetim (GM / GMY)',
  SALES: 'Satış',
  TRM_KABUL: 'TRM Kabul',
  TFM: 'Test Tesisi Yöneticisi',
  STUDY_DIRECTOR: 'Çalışma Yöneticisi',
  PLANNING_COORDINATOR: 'Planlama Koordinatörü',
  QA: 'Kalite Güvence',
  ANALYST: 'Analist',
  TECHNICIAN: 'Teknisyen',
  ADMIN: 'Sistem Yöneticisi',
};

export const ROLE_SHORT = {
  SYSADMIN: 'SYSADMIN',
  EXECUTIVE: 'GM / GMY',
  SALES: 'Satış',
  TRM_KABUL: 'TRM Kabul',
  TFM: 'TFM',
  STUDY_DIRECTOR: 'SD',
  PLANNING_COORDINATOR: 'PK',
  QA: 'QA',
  ANALYST: 'Analist',
  TECHNICIAN: 'Teknisyen',
  ADMIN: 'Admin',
};
