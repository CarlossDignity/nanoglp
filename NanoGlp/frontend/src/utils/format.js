export const todayISO = () => {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d - tz).toISOString().slice(0, 10);
};

export const fmtDateTime = (iso) =>
  new Date(iso).toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });

export const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' });

export const fmtTime = (iso) =>
  new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });

export const fmtMinutes = (m) => {
  const h = Math.floor(m / 60);
  const r = m % 60;
  return h ? `${h} sa${r ? ` ${r} dk` : ''}` : `${r} dk`;
};

/** "3 gün sonra", "Bugün", "2 saat sonra" gibi göreli metin */
export const relativeFromNow = (iso) => {
  const diffMs = new Date(iso) - new Date();
  const hours = Math.round(diffMs / 3600000);
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
  TFM: 'TFM',
  STUDY_DIRECTOR: 'SD',
  PLANNING_COORDINATOR: 'PK',
  QA: 'QA',
  ANALYST: 'Analist',
  TECHNICIAN: 'Teknisyen',
  ADMIN: 'Admin',
};
