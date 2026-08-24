import type { ReactNode } from 'react'

interface BannerProps {
  tone: 'info' | 'warn' | 'err' | 'ok'
  children: ReactNode
}

export function Banner({ tone, children }: BannerProps) {
  return <div className={`banner banner--${tone}`}>{children}</div>
}
