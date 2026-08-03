import { useEffect, useRef, useState } from 'react'
import { DayPicker } from '@daypicker/react'
import { format, isValid, parse } from 'date-fns'
import '@daypicker/react/style.css'

const ISO_FORMAT = 'yyyy-MM-dd'
const DISPLAY_FORMAT = 'dd/MM/yyyy'

function toISODate(date: Date): string {
  return format(date, ISO_FORMAT)
}

function fromISODate(value: string): Date | undefined {
  if (!value) return undefined
  const parsed = parse(value, ISO_FORMAT, new Date())
  return isValid(parsed) ? parsed : undefined
}

/**
 * DateField — a button that opens a DayPicker calendar anchored directly
 * beneath it (relative/absolute positioning, not a browser-centered
 * `<dialog>` — that always renders mid-viewport, disconnected from the
 * trigger). Closes on outside click or Escape. Talks to the caller in the
 * same YYYY-MM-DD string format `<input type="date">` used — callers don't
 * need to know it's backed by `Date` objects internally.
 */
export default function DateField({
  value,
  onChange,
  disabled,
  placeholder,
  minDate,
}: {
  value: string // YYYY-MM-DD, '' = unset
  onChange: (value: string) => void
  disabled: boolean
  placeholder: string
  minDate?: string // YYYY-MM-DD — dates before this (and before today) are disabled
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    const handlePointerDown = (e: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const selected = fromISODate(value)
  const earliestAllowed = fromISODate(minDate ?? '') ?? new Date()

  const handleSelect = (date: Date | undefined) => {
    onChange(date ? toISODate(date) : '')
    setIsOpen(false)
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen((open) => !open)}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        className="w-full bg-surface-muted p-2 rounded-lg text-sm text-on-surface text-left focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
      >
        {selected ? format(selected, DISPLAY_FORMAT) : placeholder}
      </button>
      {isOpen && (
        <div
          role="dialog"
          className="absolute z-20 mt-1 rounded-xl border border-outline-variant bg-surface-background p-3 text-on-surface shadow-lg"
        >
          <DayPicker
            mode="single"
            autoFocus
            selected={selected}
            onSelect={handleSelect}
            disabled={{ before: earliestAllowed }}
          />
        </div>
      )}
    </div>
  )
}
