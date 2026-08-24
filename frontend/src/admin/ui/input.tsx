import type { InputHTMLAttributes, ReactNode } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode
}

export function Input({ label, className, id, ...rest }: InputProps) {
  const input = <input id={id} className={['input', className].filter(Boolean).join(' ')} {...rest} />
  if (!label) return input
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {input}
    </div>
  )
}
