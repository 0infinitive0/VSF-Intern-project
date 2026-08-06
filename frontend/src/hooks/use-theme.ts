/**
 * use-theme.ts — light/dark toggle. Mirrors i18n/index.ts's storage-key
 * convention ("vota-language" -> "vota-theme"). Writes `data-theme` onto
 * <body>; styles.css keys its dark-mode overrides off
 * `body[data-theme="dark"]`.
 */
import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'vota-theme'

function readInitialTheme(): Theme {
  return localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readInitialTheme)

  useEffect(() => {
    document.body.dataset.theme = theme
    localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggleTheme }
}
