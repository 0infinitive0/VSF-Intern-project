import { useState, type CSSProperties } from 'react'
import type { User } from '@supabase/supabase-js'
import { getAvatarUrl, getInitial } from './profile-display'

/**
 * UserAvatar — the account circle used in both UserMenu's toggle button and
 * ProfilePasswordModal's header. Shows the real photo for a Google-linked
 * account (getAvatarUrl), falling back to the existing gradient +
 * initial-letter circle for password accounts (no photo at all) and for a
 * photo URL that fails to load (`onError`, e.g. a revoked/expired Google
 * image link) — same shape as RemoteImage's load/error handling elsewhere
 * in this app, simplified since there's no separate loading state worth
 * showing for a small avatar (the fallback circle underneath already reads
 * fine as the "not loaded yet" state too).
 *
 * `className` carries shape/size/font-size only (e.g. "w-6 h-6 shrink-0
 * rounded-full text-[11px]") — this component supplies the fallback
 * circle's own flex/weight/color, and `object-cover` for the img.
 * `fallbackStyle` optionally overrides the fallback circle's gradient/shadow
 * (each call site's own accent — e.g. ProfilePasswordModal's bigger header
 * avatar uses a lighter gradient + drop shadow than UserMenu's toggle
 * button); defaults to the gradient used everywhere else in the app.
 */
const DEFAULT_FALLBACK_STYLE: CSSProperties = { background: 'linear-gradient(145deg,#5C93EE,#2C5FC9)' }

export default function UserAvatar({
  user,
  displayName,
  className,
  fallbackStyle = DEFAULT_FALLBACK_STYLE,
}: {
  user: User
  displayName: string
  className: string
  fallbackStyle?: CSSProperties
}) {
  const avatarUrl = getAvatarUrl(user)
  const [imgFailed, setImgFailed] = useState(false)

  if (avatarUrl && !imgFailed) {
    return (
      <img
        src={avatarUrl}
        alt=""
        aria-hidden="true"
        className={`${className} object-cover`}
        referrerPolicy="no-referrer"
        onError={() => setImgFailed(true)}
      />
    )
  }

  return (
    <span
      className={`${className} flex items-center justify-center font-semibold text-on-primary`}
      style={fallbackStyle}
      aria-hidden="true"
    >
      {getInitial(displayName)}
    </span>
  )
}
