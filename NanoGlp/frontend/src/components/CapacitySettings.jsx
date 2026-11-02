import React, { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import {
  getRoomCapacities,
  updateRoomCapacity,
  getLongEquipment,
  updateLongEquipment,
  extractError,
} from '../services/api';

const LEVEL = {
  OK: { label: 'Fiziksel kapasite içinde', dot: 'bg-emerald-500' },
  FLEX: { label: 'Esneklik payı kullanılıyor', dot: 'bg-amber-400' },
  EXCEEDED: { label: 'Planlama kapasitesi aşıldı', dot: 'bg-red-500' },
};

const planningOf = (physical, pct) => Math.round(Number(physical || 0) * (1 + Number(pct || 0) / 100));

/**
 * FAZ 8.1 — Hayvan Odaları Kafes Kapasite Tablosu (Dr. Anoop esneklik yüzdesi) ve 24-72+ saatlik darboğaz cihazlar.
 * Sistem Planlama Kapasitesi = Fiziksel Kafes Sayısı × (1 + Esneklik Yüzdesi / 100)
 */
export default function CapacitySettings({ canEdit = false }) {
  const [rooms, setRooms] = useState([]);
  const [availableAnimals, setAvailableAnimals] = useState({ 'Guinea pig': 152, Rabbit: 98, Mouse: 20, Rat: 19 });
  const [drafts, setDrafts] = useState({});
  const [devices, setDevices] = useState([]);
  const [devDrafts, setDevDrafts] = useState({});
  const [savingKey, setSavingKey] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    try {
      const [r, d] = await Promise.all([getRoomCapacities(), getLongEquipment()]);
      const list = r.data?.rooms || [];
      setRooms(list);
      if (r.data?.available_animals) {
        setAvailableAnimals(r.data.available_animals);
      }
      setDrafts(Object.fromEntries(list.map((x) => [x.room_code, { physical_cages: x.physical_cages, flexibility_pct: x.flexibility_pct }])));
      setDevices(d.data || []);
      setDevDrafts(Object.fromEntries((d.data || []).map((x) => [x.code, x.max_concurrent_studies])));
      setError(null);
    } catch (err) {
      setError(extractError(err, 'Kapasite verileri alınamadı.'));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const saveRoom = async (room) => {
    const d = drafts[room.room_code];
    setSavingKey(room.room_code);
    setError(null);
    setNotice(null);
    try {
      await updateRoomCapacity(room.room_code, {
        physical_cages: Number(d.physical_cages),
        flexibility_pct: Number(d.flexibility_pct),
      });
      setNotice(`${room.room_label}: Planlama kapasitesi ${planningOf(d.physical_cages, d.flexibility_pct)} kafes olarak kaydedildi.`);
      await load();
    } catch (err) {
      setError(extractError(err, 'Oda kapasitesi kaydedilemedi.'));
    } finally {
      setSavingKey(null);
    }
  };

  const saveDevice = async (dev) => {
    setSavingKey(dev.code);
    setError(null);
    setNotice(null);
    try {
      await updateLongEquipment(dev.code, { max_concurrent_studies: Number(devDrafts[dev.code]) });
      setNotice(`${dev.name}: eşzamanlı çalışma kapasitesi ${devDrafts[dev.code]} olarak kaydedildi.`);
      await load();
    } catch (err) {
      setError(extractError(err, 'Cihaz kapasitesi kaydedilemedi.'));
    } finally {
      setSavingKey(null);
    }
  };

  const numInput =
    'w-20 border border-slate-300 rounded px-2 py-1 text-xs font-mono tabular-nums text-right focus:outline-none focus:ring-1 focus:ring-blue-600 disabled:bg-slate-50 disabled:text-slate-500';

  return (
    <div className="space-y-6">
      {error && <div className="border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800 rounded">{error}</div>}
      {notice && <div className="border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700 rounded">{notice}</div>}

      <section className="bg-white border border-slate-200 rounded-lg">
        <div className="px-5 py-3 border-b border-slate-200 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Hayvan Odaları Kafes Kapasitesi</h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Kapasite hayvan sayısı üzerinden değil <strong>kafes sayısı</strong> üzerinden hesaplanır:{' '}
              <span className="font-mono">Planlama Kapasitesi = Fiziksel Kafes × (1 + Dr. Anoop Esneklik % / 100)</span>. Doluluk
              fiziksel kafes ile planlama kapasitesi arasındaysa çalışma engellenmez, yalnızca bilgi etiketi gösterilir.
            </p>
          </div>
          <div className="border border-slate-200 bg-slate-50/70 rounded px-3 py-1.5 text-xs">
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500 block">
              Tesiste Mevcut Hayvan Stok Bilgisi
            </span>
            <span className="font-mono text-slate-800">
              {Object.entries(availableAnimals)
                .map(([sp, n]) => `${sp}: ${n}`)
                .join(' · ')}
            </span>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
              <tr>
                <th className="text-left px-5 py-2 font-medium">Oda</th>
                <th className="text-right px-3 py-2 font-medium">Tesiste mevcut hayvan</th>
                <th className="text-right px-3 py-2 font-medium">Fiziksel kafes</th>
                <th className="text-right px-3 py-2 font-medium">Dr. Anoop esneklik oranı (%)</th>
                <th className="text-right px-3 py-2 font-medium">Sistem planlama kapasitesi</th>
                <th className="text-left px-3 py-2 font-medium">Doluluk (−30 / +120 gün)</th>
                {canEdit && <th className="px-5 py-2" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rooms.map((r) => {
                const d = drafts[r.room_code] || {};
                const dirty = Number(d.physical_cages) !== r.physical_cages || Number(d.flexibility_pct) !== r.flexibility_pct;
                const lv = LEVEL[r.level] || LEVEL.OK;
                return (
                  <tr key={r.room_code}>
                    <td className="px-5 py-2">
                      <span className="font-medium text-slate-800">{r.room_label}</span>
                      <span className="ml-2 font-mono text-[10px] text-slate-400">{r.room_code}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-700">
                      {r.available_animals ?? '—'} hayvan
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        min={1}
                        disabled={!canEdit}
                        value={d.physical_cages ?? ''}
                        onChange={(e) => setDrafts({ ...drafts, [r.room_code]: { ...d, physical_cages: e.target.value } })}
                        className={numInput}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number"
                        min={0}
                        step="1"
                        disabled={!canEdit}
                        value={d.flexibility_pct ?? ''}
                        onChange={(e) => setDrafts({ ...drafts, [r.room_code]: { ...d, flexibility_pct: e.target.value } })}
                        className={numInput}
                      />
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums font-semibold text-slate-900">
                      {planningOf(d.physical_cages, d.flexibility_pct)} Kafes
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5">
                        <span className={`w-1.5 h-1.5 rounded-full ${lv.dot}`} />
                        <span className="font-mono tabular-nums">
                          {r.current_used} bugün · {r.peak_used} tepe
                        </span>
                        <span className="text-slate-400">— {lv.label}</span>
                      </span>
                    </td>
                    {canEdit && (
                      <td className="px-5 py-2 text-right">
                        <button
                          type="button"
                          disabled={!dirty || savingKey === r.room_code}
                          onClick={() => saveRoom(r)}
                          className="inline-flex items-center gap-1.5 border border-slate-300 hover:bg-slate-50 disabled:opacity-40 rounded px-2.5 py-1 text-xs font-medium text-slate-700"
                        >
                          {savingKey === r.room_code && <Loader2 className="w-3 h-3 animate-spin" />}
                          Kaydet
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="bg-white border border-slate-200 rounded-lg">
        <div className="px-5 py-3 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900">24–72+ Saatlik Darboğaz Cihazlar</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Yalnızca uzun süreli cihazlar kapasite denetimine alınır (15 dakikalık kısa cihazlar dahil değildir). Çalkalamalı Su
            Banyosu Polar/Apolar kapasitesi yukarıdaki “Sistem Kalibrasyonu” bölümünde yönetilir.
          </p>
        </div>
        <table className="w-full text-xs">
          <thead className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <tr>
              <th className="text-left px-5 py-2 font-medium">Cihaz</th>
              <th className="text-left px-3 py-2 font-medium">Süre</th>
              <th className="text-right px-3 py-2 font-medium">Eşzamanlı çalışma kapasitesi</th>
              {canEdit && <th className="px-5 py-2" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {devices.map((dev) => {
              const isWb = dev.code === 'EQ-WB-001';
              const dirty = Number(devDrafts[dev.code]) !== dev.max_concurrent_studies;
              return (
                <tr key={dev.code}>
                  <td className="px-5 py-2">
                    <span className="font-medium text-slate-800">{dev.name}</span>
                    <span className="ml-2 font-mono text-[10px] text-slate-400">{dev.code}</span>
                    {dev.note && <p className="text-[11px] text-slate-400 mt-0.5">{dev.note}</p>}
                  </td>
                  <td className="px-3 py-2 text-slate-600">{isWb ? '72 saat (Polar / Apolar)' : '24–72 saat'}</td>
                  <td className="px-3 py-2 text-right">
                    {isWb ? (
                      <span className="font-mono tabular-nums text-slate-500">Kalibrasyon bölümünden</span>
                    ) : (
                      <input
                        type="number"
                        min={1}
                        disabled={!canEdit}
                        value={devDrafts[dev.code] ?? ''}
                        onChange={(e) => setDevDrafts({ ...devDrafts, [dev.code]: e.target.value })}
                        className={numInput}
                      />
                    )}
                  </td>
                  {canEdit && (
                    <td className="px-5 py-2 text-right">
                      {!isWb && (
                        <button
                          type="button"
                          disabled={!dirty || savingKey === dev.code}
                          onClick={() => saveDevice(dev)}
                          className="inline-flex items-center gap-1.5 border border-slate-300 hover:bg-slate-50 disabled:opacity-40 rounded px-2.5 py-1 text-xs font-medium text-slate-700"
                        >
                          {savingKey === dev.code && <Loader2 className="w-3 h-3 animate-spin" />}
                          Kaydet
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
