/**
 * GEÇİCİ FRONTEND STORE (MOCK) — YALNIZCA SİSTEM AYARLARI
 *
 * Sistem kalibrasyon değerleri (görev süreleri, oda/cihaz kapasiteleri), backend bağlantısı
 * yapılana kadar burada tutulur.
 * - Sayfalar arasında gezinirken veri korunur; sayfa yenilenince (F5) sıfırlanır.
 * - Hiçbir veri sunucuya gönderilmez; planlama motoru bu değerleri henüz KULLANMAZ.
 *
 * FAZ 6: Belge yükleme simülasyonu kaldırıldı — belgeler artık /api/v1/documents üzerinden
 * gerçekten yüklenip AI ile ayrıştırılıyor.
 */
import React, { createContext, useContext, useMemo, useState } from 'react';

let _seq = 100;
export const uid = () => ++_seq;

// ---------------------------------------------------------------------------
// Sistem kalibrasyonu — başlangıç değerleri yalnızca kullanıcı tarafından verilen örneklerdir.
// ---------------------------------------------------------------------------
export const TASK_CATEGORIES = ['Hazırlık', 'Uygulama', 'Gözlem', 'Ekstraksiyon', 'Terminasyon', 'Diğer'];
export const RESOURCE_TYPES = ['Oda', 'Cihaz'];

const INITIAL_DURATIONS = [
  { id: 1, name: 'Tüy Kesimi', category: 'Hazırlık', minutes: 45 },
  { id: 2, name: 'Gözlem', category: 'Gözlem', minutes: 15 },
];

const INITIAL_RESOURCES = [
  { id: 1, name: 'Su Banyosu (Apolar)', type: 'Cihaz', capacity: 1, unit: 'eşzamanlı kullanım' },
];

const MockStoreContext = createContext(null);

export function MockStoreProvider({ children }) {
  const [durations, setDurations] = useState(INITIAL_DURATIONS);
  const [resources, setResources] = useState(INITIAL_RESOURCES);
  const [settingsLog, setSettingsLog] = useState([]);

  const value = useMemo(
    () => ({
      durations, setDurations,
      resources, setResources,
      settingsLog, setSettingsLog,
    }),
    [durations, resources, settingsLog]
  );

  return <MockStoreContext.Provider value={value}>{children}</MockStoreContext.Provider>;
}

export const useMockStore = () => {
  const ctx = useContext(MockStoreContext);
  if (!ctx) throw new Error('useMockStore, MockStoreProvider içinde kullanılmalıdır.');
  return ctx;
};
