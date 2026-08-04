/**
 * i18n/index.ts — react-i18next bootstrap.
 *
 * Resources load synchronously from local JSON imports (no HTTP backend — the
 * whole catalog is small). The selected language is persisted to localStorage
 * under "vota-language" and defaults to Vietnamese ("vi") for a first-time
 * visitor. Manual toggle only — no auto-detection, per scope.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import vi from './locales/vi.json'

export const STORAGE_KEY = 'vota-language'

const stored = localStorage.getItem(STORAGE_KEY)
const initialLanguage = stored === 'en' || stored === 'vi' ? stored : 'vi'

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, vi: { translation: vi } },
  lng: initialLanguage,
  fallbackLng: 'vi',
  interpolation: { escapeValue: false }, // React already escapes
})

i18n.on('languageChanged', (lng) => localStorage.setItem(STORAGE_KEY, lng))

export default i18n