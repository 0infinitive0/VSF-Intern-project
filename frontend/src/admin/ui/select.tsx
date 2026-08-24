import type { ReactNode, SelectHTMLAttributes } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode
}

export function Select({ label, className, id, children, ...rest }: SelectProps) {
  const select = (
    <select id={id} className={['select', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </select>
  )
  if (!label) return select
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {select}
    </div>
  )
}
