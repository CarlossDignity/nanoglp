import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { translateText, formatStatusBadge, setActiveLang } from '../i18n/translations';

const THEME_STORAGE_KEY = 'nanolab_theme';
const LANG_STORAGE_KEY = 'nanolab_lang';
const LANG_MANUAL_KEY = 'nanolab_lang_manual';
const USER_STORAGE_KEY = 'nanolab_glp_user';

const PreferencesContext = createContext(null);

function applyHtmlTheme(theme) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const isDark = theme === 'dark';
  if (isDark) {
    root.classList.add('dark');
    root.setAttribute('data-theme', 'dark');
    root.style.colorScheme = 'dark';
    root.style.backgroundColor = '#090d16';
    root.style.color = '#f8fafc';
    if (document.body) {
      document.body.classList.add('dark');
      document.body.style.colorScheme = 'dark';
      document.body.style.backgroundColor = '#090d16';
      document.body.style.color = '#f8fafc';
    }
  } else {
    root.classList.remove('dark');
    root.setAttribute('data-theme', 'light');
    root.style.colorScheme = 'light';
    root.style.backgroundColor = '#f8fafc';
    root.style.color = '#0f172a';
    if (document.body) {
      document.body.classList.remove('dark');
      document.body.style.colorScheme = 'light';
      document.body.style.backgroundColor = '#f8fafc';
      document.body.style.color = '#0f172a';
    }
  }
}

function applyHtmlLang(lang) {
  const normalized = lang === 'en' ? 'en' : 'tr';
  setActiveLang(normalized);
  if (typeof document === 'undefined') return;
  document.documentElement.lang = normalized;
  document.documentElement.setAttribute('lang', normalized);
}

function detectInitialTheme() {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === 'dark' || saved === 'light') {
      applyHtmlTheme(saved);
      return saved;
    }
  } catch {
    /* ignore */
  }
  applyHtmlTheme('light');
  return 'light';
}

function detectInitialLang() {
  try {
    const manual = localStorage.getItem(LANG_MANUAL_KEY);
    const saved = localStorage.getItem(LANG_STORAGE_KEY);
    const rawUser = localStorage.getItem(USER_STORAGE_KEY);
    if (rawUser && !manual) {
      const parsed = JSON.parse(rawUser);
      if (parsed?.username && String(parsed.username).toLowerCase().includes('anoop')) {
        applyHtmlLang('en');
        return 'en';
      }
    }
    if (saved === 'en' || saved === 'tr') {
      applyHtmlLang(saved);
      return saved;
    }
  } catch {
    /* ignore */
  }
  applyHtmlLang('tr');
  return 'tr';
}

export function PreferencesProvider({ children }) {
  const [theme, setThemeState] = useState(detectInitialTheme);
  const [lang, setLangState] = useState(detectInitialLang);

  useEffect(() => {
    applyHtmlTheme(theme);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    applyHtmlLang(lang);
    try {
      localStorage.setItem(LANG_STORAGE_KEY, lang);
    } catch {
      /* ignore */
    }
  }, [lang]);

  const syncUserLanguagePreference = useCallback((username) => {
    try {
      const manual = localStorage.getItem(LANG_MANUAL_KEY);
      if (!manual && username && String(username).toLowerCase().includes('anoop')) {
        applyHtmlLang('en');
        localStorage.setItem(LANG_STORAGE_KEY, 'en');
        setLangState('en');
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    try {
      const rawUser = localStorage.getItem(USER_STORAGE_KEY);
      if (rawUser) {
        const parsed = JSON.parse(rawUser);
        if (parsed?.username) syncUserLanguagePreference(parsed.username);
      }
    } catch {
      /* ignore */
    }
  }, [syncUserLanguagePreference]);

  const setTheme = useCallback((next) => {
    const normalized = next === 'dark' ? 'dark' : 'light';
    applyHtmlTheme(normalized);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch {
      /* ignore */
    }
    setThemeState(normalized);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark';
      applyHtmlTheme(next);
      try {
        localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const setLang = useCallback((next) => {
    const normalized = next === 'en' ? 'en' : 'tr';
    applyHtmlLang(normalized);
    try {
      localStorage.setItem(LANG_MANUAL_KEY, '1');
      localStorage.setItem(LANG_STORAGE_KEY, normalized);
    } catch {
      /* ignore */
    }
    setLangState(normalized);
  }, []);

  const toggleLang = useCallback(() => {
    setLang(lang === 'tr' ? 'en' : 'tr');
  }, [lang, setLang]);

  const t = useCallback(
    (trText, enFallback) => {
      if (trText === null || trText === undefined) return '';
      if (lang === 'en') {
        if (enFallback !== undefined) return enFallback;
        return translateText(String(trText), 'en');
      }
      return String(trText);
    },
    [lang]
  );

  const tr = t;

  const value = useMemo(
    () => ({
      theme,
      isDark: theme === 'dark',
      setTheme,
      toggleTheme,
      lang,
      isEnglish: lang === 'en',
      setLang,
      toggleLang,
      t,
      tr,
      translateText: (str) => translateText(str, lang),
      formatStatusBadge: (code) => formatStatusBadge(code, lang),
      syncUserLanguagePreference,
    }),
    [theme, setTheme, toggleTheme, lang, setLang, toggleLang, t, tr, syncUserLanguagePreference]
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences() {
  const ctx = useContext(PreferencesContext);
  if (!ctx) {
    return {
      theme: 'light',
      isDark: false,
      setTheme: () => {},
      toggleTheme: () => {},
      lang: 'tr',
      isEnglish: false,
      setLang: () => {},
      toggleLang: () => {},
      t: (s) => s,
      tr: (s) => s,
      translateText: (s) => s,
      formatStatusBadge: (s) => formatStatusBadge(s, 'tr'),
      syncUserLanguagePreference: () => {},
    };
  }
  return ctx;
}

/**
 * Kurumsal TR | EN Dil Değiştirici + İki Parçalı [ ☀️ Açık | 🌙 Koyu ] Tema Anahtarı
 */
export function ThemeLanguageControls({ variant = 'header' }) {
  const { theme, setTheme, lang, setLang } = usePreferences();
  const isLogin = variant === 'login';

  return (
    <div
      data-no-i18n="true"
      className={`inline-flex items-center gap-2 ${isLogin ? 'text-xs' : 'text-xs'}`}
    >
      {/* TR | EN Segmented Toggle */}
      <div
        role="group"
        aria-label="Language switcher"
        className="inline-flex items-center rounded border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-0.5 font-mono text-[11px]"
      >
        <button
          type="button"
          onClick={() => setLang('tr')}
          className={`px-2 py-0.5 rounded-sm font-semibold transition ${
            lang === 'tr'
              ? 'bg-slate-900 text-white dark:bg-blue-600 dark:text-white shadow-xs'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
          }`}
          title="Türkçe"
        >
          TR
        </button>
        <button
          type="button"
          onClick={() => setLang('en')}
          className={`px-2 py-0.5 rounded-sm font-semibold transition ${
            lang === 'en'
              ? 'bg-slate-900 text-white dark:bg-blue-600 dark:text-white shadow-xs'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
          }`}
          title="English"
        >
          EN
        </button>
      </div>

      {/* [ ☀️ Açık | 🌙 Koyu ] Segmented Theme Switch */}
      <div
        role="group"
        aria-label="Theme switcher"
        className="inline-flex items-center rounded border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-0.5 text-[11px]"
      >
        <button
          type="button"
          onClick={() => setTheme('light')}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm font-semibold transition ${
            theme === 'light'
              ? 'bg-slate-900 text-white shadow-xs'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
          }`}
          title={lang === 'en' ? 'Light Mode' : 'Açık Mod'}
        >
          <Sun className={`w-3.5 h-3.5 ${theme === 'light' ? 'text-amber-300' : 'text-amber-400'}`} />
          <span>{lang === 'en' ? 'Light' : 'Açık'}</span>
        </button>
        <button
          type="button"
          onClick={() => setTheme('dark')}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm font-semibold transition ${
            theme === 'dark'
              ? 'bg-blue-600 text-white shadow-xs'
              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
          }`}
          title={lang === 'en' ? 'Dark Mode' : 'Koyu Mod'}
        >
          <Moon className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-white' : 'text-slate-500'}`} />
          <span>{lang === 'en' ? 'Dark' : 'Koyu'}</span>
        </button>
      </div>
    </div>
  );
}
