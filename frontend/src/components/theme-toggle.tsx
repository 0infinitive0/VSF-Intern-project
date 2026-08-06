import { useTranslation } from 'react-i18next'
import type { Theme } from '../hooks/use-theme'

/**
 * ThemeToggle — sidebar control. Label shows the mode you'll switch TO
 * (matches the reference design: current dark shows "Light mode").
 */
export default function ThemeToggle({
  theme,
  onToggle,
  collapsed,
}: {
  theme: Theme
  onToggle: () => void
  collapsed: boolean
}) {
  const { t } = useTranslation()
  const label = t(theme === 'dark' ? 'themeToggleSwitchToLight' : 'themeToggleSwitchToDark')

  return (
    <button
      type="button"
      onClick={onToggle}
      title={label}
      aria-label={label}
      className="shrink-0 h-9 rounded-xl border border-outline-variant bg-glass-1 flex items-center justify-center gap-2 text-[11.5px] font-medium text-on-surface-variant hover:text-on-surface transition-colors"
    >
      <span className="material-symbols-outlined text-[16px]" aria-hidden="true">
        {theme === 'dark' ? 'light_mode' : 'dark_mode'}
      </span>
      {!collapsed && label}
    </button>
  )
}
