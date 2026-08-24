import type { ReactNode } from 'react'

interface PageHeaderProps {
  breadcrumb: string
  title: string
  action?: ReactNode
}

export function PageHeader({ breadcrumb, title, action }: PageHeaderProps) {
  return (
    <div
      style={{
        height: 66,
        flex: 'none',
        padding: '0 28px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        background: 'var(--g1)',
        backdropFilter: 'blur(18px)',
        borderBottom: '1px solid var(--stroke)',
      }}
    >
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>{breadcrumb}</div>
        <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: '-.01em' }}>{title}</div>
      </div>
      {action && <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{action}</div>}
    </div>
  )
}
