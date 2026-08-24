import type { ReactNode, TextareaHTMLAttributes } from 'react'

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode
}

export function Textarea({ label, className, id, ...rest }: TextareaProps) {
  const textarea = <textarea id={id} className={['textarea', className].filter(Boolean).join(' ')} {...rest} />
  if (!label) return textarea
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {textarea}
    </div>
  )
}
