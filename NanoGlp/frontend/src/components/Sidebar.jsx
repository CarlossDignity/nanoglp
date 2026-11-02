import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  CalendarClock,
  Users,
  FlaskConical,
  ShieldAlert,
  FileUp,
  Settings as SettingsIcon,
  ClipboardCheck,
  UserCog,
  Eye,
  TestTubes as FlaskRound,
} from 'lucide-react';
import { useAuth } from '../state/AuthContext';

export const ALL_NAV_SECTIONS = [
  {
    title: 'Operasyon & Takip',
    items: [
      { to: '/', menuKey: 'dashboard', label: 'Yönetici Paneli', icon: LayoutDashboard, end: true },
      { to: '/samples', menuKey: 'samples', label: 'Numune & Çalışma Takip', icon: FlaskRound },
      { to: '/upload', menuKey: 'upload', label: 'Belge Yükleme', icon: FileUp },
      { to: '/planning', menuKey: 'planning', label: 'Çoklu Çalışma Planlama', icon: CalendarClock },
      { to: '/personnel', menuKey: 'personnel', label: 'Personel İş Yükü', icon: Users },
      { to: '/studies', menuKey: 'studies', label: 'GLP Çalışmaları', icon: FlaskConical },
      { to: '/conflicts', menuKey: 'conflicts', label: 'Açık Çakışmalar', icon: ShieldAlert, badgeKey: 'conflicts' },
      { to: '/my-tasks', menuKey: 'my_tasks', label: 'Bugünkü Görevlerim', icon: ClipboardCheck },
    ],
  },
  {
    title: 'Yönetim',
    items: [
      { to: '/users', menuKey: 'users', label: 'Kullanıcı Yönetimi', icon: UserCog },
      { to: '/settings', menuKey: 'settings', label: 'Sistem Ayarları', icon: SettingsIcon },
    ],
  },
];

export default function Sidebar({ badges = {} }) {
  const { allowedMenus, isReadOnly, isExecutive, role } = useAuth();

  const sections = ALL_NAV_SECTIONS.map((sec) => ({
    ...sec,
    items: sec.items.filter((item) => allowedMenus.includes(item.menuKey)),
  })).filter((sec) => sec.items.length > 0);

  return (
    <aside className="w-60 shrink-0 bg-white border-r border-slate-200 min-h-[calc(100vh-64px)] flex flex-col justify-between">
      <nav className="p-3 space-y-4">
        {isReadOnly && (
          <div
            className={`px-3 py-2 rounded-md border text-[11px] flex items-center gap-2 font-semibold ${
              isExecutive
                ? 'bg-indigo-50 border-indigo-200 text-indigo-900'
                : 'bg-amber-50 border-amber-200 text-amber-900'
            }`}
          >
            <Eye className={`w-3.5 h-3.5 shrink-0 ${isExecutive ? 'text-indigo-700' : 'text-amber-700'}`} />
            <span>
              {isExecutive
                ? 'Üst Yönetim (GM/GMY): İzleme Modu'
                : role === 'QA'
                ? 'QA Modu: Salt Okunur'
                : 'İzleme Modu (Salt Okunur)'}
            </span>
          </div>
        )}

        {sections.map((section) => (
          <div key={section.title}>
            <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              {section.title}
            </p>
            <div className="space-y-0.5">
              {section.items.map(({ to, label, icon: Icon, end, badgeKey }) => {
                const badge = badgeKey ? badges[badgeKey] : 0;
                return (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    className={({ isActive }) =>
                      `group w-full flex items-center justify-between px-3 py-2 rounded-md text-sm transition ${
                        isActive
                          ? 'bg-slate-100 text-slate-900 font-medium'
                          : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <span className="flex items-center gap-2.5">
                          <Icon className={`w-4 h-4 ${isActive ? 'text-slate-700' : 'text-slate-400'}`} />
                          {label}
                        </span>
                        {badge > 0 && (
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-600 text-white">
                            {badge}
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="m-3 p-3 rounded-md bg-slate-50 border border-slate-200 text-[11px] text-slate-600 leading-relaxed">
        <p className="font-semibold text-slate-800 mb-1">GLP Kural Motoru</p>
        Biyolojik saatler kilitlidir. Sistem takvimi otomatik kaydırmaz; tüm kararlar SD onayına tabidir.
      </div>
    </aside>
  );
}
