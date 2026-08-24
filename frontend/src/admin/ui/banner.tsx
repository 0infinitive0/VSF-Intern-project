import type { ReactNode } from 'react'

interface BannerProps {
  tone: 'warn' | 'err' | 'ok'
  children: ReactNode
}

export function Banner({ tone, children }: BannerProps) {
  return <div className={`banner banner--${tone}`}>{children}</div>
}
