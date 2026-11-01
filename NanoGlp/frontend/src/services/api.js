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

// Kimlik Doğrulama (FAZ 5 & 5.1 Auth & RBAC)
export const loginApi = (username, password) =>
  api.post('/auth/login', { username, password });
export const getMe = () => api.get('/auth/me');

// Kullanıcı Yönetimi (Sadece SYSADMIN ve TFM)
export const getUsers = () => api.get('/users');
export const createUser = (data) => api.post('/users', data);
export const updateUser = (id, data) => api.put(`/users/${id}`, data);
export const deleteUser = (id) => api.delete(`/users/${id}`);

// Temel Servisler
export const getHealth = () => api.get('/health');
export const getStudies = () => api.get('/studies/');
export const createStudy = (data) => api.post('/studies/', data);
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
export const getStudySchedule = (studyId) => api.get(`/planning/studies/${studyId}/schedule`);
export const approveStudyPlan = (studyId) => api.post(`/planning/studies/${studyId}/approve`);
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
