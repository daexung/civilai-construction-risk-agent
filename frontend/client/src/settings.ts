export type DetailLevel = '간략' | '기본' | '상세';
export type CurrencyUnit = '원' | '천원' | '만원';
export type Theme = '라이트' | '다크';

export interface Settings {
  detail: DetailLevel;
  unit: CurrencyUnit;
  theme: Theme;
}

const DEFAULTS: Settings = { detail: '기본', unit: '원', theme: '라이트' };
const KEY = 'app_settings';

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {}
  return { ...DEFAULTS };
}

export function saveSettings(s: Settings): void {
  localStorage.setItem(KEY, JSON.stringify(s));
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme === '다크' ? 'dark' : 'light');
}
