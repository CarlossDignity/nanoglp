import axios from 'axios';

export const TOKEN_STORAGE_KEY = 'nanolab_glp_jwt';
export const USER_STORAGE_KEY = 'nanolab_glp_user';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1', // dev: Vite proxy → 127.0.0.1:8000
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error?.config?.url || '';
    if (error?.response?.status === 401 && !url.includes('/auth/login')) {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(USER_STORAGE_KEY);
      window.dispatchEvent(new Event('nanolab:unauthorized'));
    }
    return Promise.reject(error);
  }
);

// Kimlik Doğrulama (FAZ 5, 5.1 & FAZ 10 Auth & RBAC)
export const loginApi = (username, password) =>
  api.post('/auth/login', { username, password });
export const getMe = () => api.get('/auth/me');
export const changePasswordApi = (currentPassword, newPassword) =>
  api.post('/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  });

// Kullanıcı ve Rol Yönetimi (SYSADMIN ve TFM)
export const getUsers = () => api.get('/users');
export const createUser = (data) => api.post('/users', data);
export const updateUser = (id, data) => api.put(`/users/${id}`, data);
export const deleteUser = (id) => api.delete(`/users/${id}`);
export const getRoles = () => api.get('/users/roles');
export const createRole = (data) => api.post('/users/roles', data);
export const updateRole = (roleCode, data) => api.put(`/users/roles/${roleCode}`, data);
export const deleteRole = (roleCode) => api.delete(`/users/roles/${roleCode}`);

// Temel Servisler
export const getHealth = () => api.get('/health');
export const getStudies = () => api.get('/studies/');
export const createStudy = (data) => api.post('/studies/', data);
export const updatePersonnelContact = (id, data) => api.patch(`/personnel/${id}/contact`, data);
export const getPersonnel = () => api.get('/personnel/');
export const createPersonnel = (data) => api.post('/personnel/', data);
export const getEquipment = () => api.get('/equipment');
export const getRooms = () => api.get('/rooms');

// Operasyonel Planlama & Çakışma Yönetimi Servisleri
export const getSummary = () => api.get('/planning/summary');
export const getTemplates = () => api.get('/planning/templates');
export const getCalibration = () => api.get('/planning/calibration');
export const updateCalibration = (data) => api.put('/planning/calibration', data);
export const getSteps = (params) => api.get('/planning/steps', { params });
export const getCalendar = () => api.get('/planning/calendar');

export const downloadOperationPlanExcel = async (params) => {
  const res = await api.get('/planning/export-excel', { params, responseType: 'blob' });
  const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = res.headers?.['content-disposition']?.match(/filename="([^"]+)"/)?.[1]
    || `operasyon-plani-${params.view}-${params.target_date}.xlsx`;
  try {
    document.body.appendChild(a);
    a.click();
  } finally {
    a.remove();
    window.URL.revokeObjectURL(url);
  }
};
export const getStudySchedule = (studyId) => api.get(`/planning/studies/${studyId}/schedule`);
export const approveStudyPlan = (studyId) => api.post(`/planning/studies/${studyId}/approve`);
export const getBiologicalRevisionPreview = (studyId) =>
  api.get(`/planning/studies/${studyId}/revision-preview`);
export const approveBiologicalRevision = (studyId, data) =>
  api.post(`/planning/studies/${studyId}/approve-revision`, data);
export const getMyTasks = (targetDate) =>
  api.get('/planning/my-tasks', { params: targetDate ? { target_date: targetDate } : {} });
export const updateStepStatus = (stepId, data) =>
  api.patch(`/planning/steps/${stepId}/status`, data);
export const getDailyWorkload = (targetDate) =>
  api.get('/planning/workload', { params: { target_date: targetDate } });
export const getWeeklyWorkload = (targetDate) =>
  api.get('/planning/workload-weekly', { params: { target_date: targetDate } });
export const scheduleStudy = (data) => api.post('/planning/schedule-study', data);
export const checkPersonnelWorkload = (data) => api.post('/planning/check-workload', data);
export const getConflicts = (params) => api.get('/planning/conflicts', { params });
export const recomputeConflicts = () => api.post('/planning/recompute-conflicts');
export const resolveConflict = (id, data) => api.post(`/planning/conflicts/${id}/resolve`, data);
export const applyConflictResolution = (conflictId, data) =>
  api.post(`/planning/conflicts/${conflictId}/apply-resolution`, data);

// FAZ 6.2: Otomatik Study Plan (.docx) Word Belgesi İndirme
export const exportStudyPlanDocx = (studyId) =>
  api.get(`/studies/${studyId}/export-study-plan`, { responseType: 'blob' });

export const downloadStudyPlanDocx = async (studyId, studyCode = '') => {
  const res = await exportStudyPlanDocx(studyId);
  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  const safeCode = (studyCode || `Study_${studyId}`).replace(/[^A-Za-z0-9_.-]+/g, '_');
  a.href = url;
  a.download = `GLP_Study_Plan_Draft_${safeCode}.docx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// FAZ 6, 6.1 & 6.2: Belge Yükleme, GPT-4o Vision OCR, Dosya Birleştirme & Çalışma Paketi İzolasyonu
export const uploadDocument = (file, onUploadProgress, dossierKey, dossierLabel) => {
  const form = new FormData();
  form.append('file', file);
  const params = {};
  if (dossierKey) params.dossier_key = dossierKey;
  if (dossierLabel) params.dossier_label = dossierLabel;
  return api.post('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params,
    timeout: 180000,
    onUploadProgress,
  });
};
export const getDocuments = (params) => api.get('/documents', { params });
export const getDossiers = () => api.get('/documents/dossiers');
export const getDossier = (dossierKey) =>
  api.get('/documents/dossier', { params: dossierKey ? { dossier_key: dossierKey } : {} });
export const reparseDocument = (id) =>
  api.post(`/documents/${id}/reparse`, {}, { timeout: 180000 });
export const reparseAllDocuments = (params) =>
  api.post('/documents/reparse-all', {}, { params, timeout: 600000 });
export const deleteDocument = (id) => api.delete(`/documents/${id}`);

// FAZ 8.1: Test Kısıtlama Takvimi, Kafes Kapasitesi, Uzun Süreli Cihazlar
export const getRestrictions = () => api.get('/restrictions');
export const createRestriction = (data) => api.post('/restrictions', data);
export const updateRestriction = (id, data) => api.put(`/restrictions/${id}`, data);
export const deleteRestriction = (id) => api.delete(`/restrictions/${id}`);
export const previewRestrictionShift = (data) => api.post('/restrictions/preview-shift', data);
export const getRoomCapacities = () => api.get('/room-capacities');
export const updateRoomCapacity = (code, data) => api.put(`/room-capacities/${code}`, data);
export const getLongEquipment = () => api.get('/long-equipment');
export const updateLongEquipment = (code, data) => api.put(`/long-equipment/${code}`, data);

// FAZ 8.1: Numune & Çalışma Takip
export const getSamples = () => api.get('/samples');
export const getNextSampleCode = () => api.get('/samples/next-code');
export const getSample = (id) => api.get(`/samples/${id}`);
export const createSample = (data) => api.post('/samples', data);
export const updateSample = (id, data) => api.put(`/samples/${id}`, data);
export const deleteSample = (id) => api.delete(`/samples/${id}`);
export const planSample = (id, data = {}) => api.post(`/samples/${id}/plan`, data, { timeout: 120000 });
export const autoScheduleAllSamples = () => api.post('/samples/auto-schedule-all', {}, { timeout: 300000 });
export const sampleWorkflowAction = (id, step, data) => api.post(`/samples/${id}/workflow/${step}`, data);
export const importSamplesExcel = (file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post('/samples/import-excel', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
};
export const exportSamplesExcel = async () => {
  const res = await api.get('/samples/export-excel', { responseType: 'blob', timeout: 120000 });
  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'NANOLAB_GLP_Calisma_Takip_Listesi.xlsx';
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};
export const downloadSampleStudyPlan = async (sampleId, studyCode = '') => {
  const res = await api.get(`/samples/${sampleId}/study-plan-docx`, { responseType: 'blob', timeout: 180000 });
  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `GLP_Study_Plan_Draft_${(studyCode || `Sample_${sampleId}`).replace(/[^A-Za-z0-9_.-]+/g, '_')}.docx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

export const getSampleDocuments = (id) => api.get(`/samples/${id}/documents`);
export const uploadSampleDocuments = (id, files, overwrite = false) => {
  const form = new FormData();
  Array.from(files).forEach((f) => form.append('files', f));
  return api.post(`/samples/${id}/documents`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params: overwrite ? { overwrite: true } : {},
    timeout: 600000,
  });
};

/** Blob yanıtlı isteklerde FastAPI hata gövdesini (JSON) okunabilir metne çevirir. */
export const extractBlobError = async (err, fallback = 'İşlem başarısız.') => {
  const data = err?.response?.data;
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text());
      if (typeof parsed?.detail === 'string') return parsed.detail;
    } catch {
      /* yut */
    }
  }
  return err?.response?.data?.detail && typeof err.response.data.detail === 'string' ? err.response.data.detail : fallback;
};

/** FastAPI hata gövdesini okunabilir metne çevirir. */
export const extractError = (err, fallback = 'Beklenmeyen bir hata oluştu.') => {
  const detail = err?.response?.data?.detail;
  if (!detail) return err?.message === 'Network Error' ? 'Backend servisine ulaşılamıyor (localhost:8000).' : fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(' • ');
  if (typeof detail === 'object' && detail.message) return detail.message;
  return fallback;
};

export default api;
