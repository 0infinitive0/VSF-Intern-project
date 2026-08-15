import { useEffect, type RefObject } from 'react'

/**
 * Replays the vFade entrance animation on a DayPicker's month grid whenever
 * `month` changes — without remounting <DayPicker> itself, which would drop
 * keyboard focus mid-navigation (DayPicker owns focus internally). Shared by
 * IntakeDateRange and DateOfBirthField, both of which wrap their calendar in
 * a `.day-calendar`-scoped container and want the same "grid re-fades in
 * when the visible month changes" feel as the design's `calKey`-driven
 * transition.
 */
export function useCalendarGridFadeReplay(containerRef: RefObject<HTMLElement | null>, month: Date) {
  useEffect(() => {
    const grid = containerRef.current?.querySelector<HTMLElement>('.rdp-month_grid')
    if (!grid) return
    const animClass = 'animate-[vFade_0.32s_ease_both]'
    grid.classList.remove(animClass)
    void grid.offsetWidth
    grid.classList.add(animClass)
  }, [containerRef, month])
}
