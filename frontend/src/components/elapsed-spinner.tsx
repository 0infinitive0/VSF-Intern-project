/**
 * ElapsedSpinner — in-flow thinking indicator (design dc.html:189-198).
 * Three animated dots, plus a status caption that escalates once the wait
 * has stretched past a few seconds — no elapsed-seconds count shown.
 */
export default function ElapsedSpinner() {
  return (
    <div className="flex gap-2.5 items-end" aria-live="polite" aria-busy="true">
      <div className="w-6 h-6 flex-none rounded-[9px] bg-[linear-gradient(145deg,#5C93EE,#2C5FC9)] flex items-center justify-center">
        <span className="text-on-primary text-[11px] font-[590]">V</span>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex gap-1 px-[15px] py-[13px] rounded-[18px] bg-glass-3 border border-line">
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface animate-[vDot_1.1s_infinite]" aria-hidden="true" />
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface animate-[vDot_1.1s_0.16s_infinite]" aria-hidden="true" />
          <span className="w-1.5 h-1.5 rounded-full bg-on-surface animate-[vDot_1.1s_0.32s_infinite]" aria-hidden="true" />
        </div>
      </div>
    </div>
  )
}
