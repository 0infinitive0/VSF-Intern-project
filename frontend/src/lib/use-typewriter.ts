import { useEffect, useRef, useState } from 'react'

/** Characters revealed per tick. A tick is one animation frame (~16ms). */
const CHARS_PER_TICK = 2

/**
 * Reveals `text` progressively, for replies that arrive complete.
 *
 * Most turns do stream: `qa_node` and `intake_qa` write prose and their tokens
 * reach the client as `delta` frames. The rest do not, and cannot — a hotel
 * search answers from a template (`"Mình tìm được {count} khách sạn phù hợp."`),
 * so there is no model producing tokens to forward. Those replies used to snap
 * into place while a streamed one typed itself out, which read as two different
 * assistants.
 *
 * This is presentation only. The text is complete and unmodified before the
 * first character shows; nothing here invents, reorders, or withholds content —
 * it just paces the reveal so every reply behaves the same way.
 *
 * Disabled outright under `prefers-reduced-motion`: someone who asked for less
 * motion is asking for the text, not the performance.
 */
export function useTypewriter(text: string, enabled: boolean): string {
  const [revealed, setRevealed] = useState(() => (enabled ? '' : text))
  // Guards against replaying when React re-renders or remounts with the same
  // content — the animation belongs to the message's arrival, not to a render.
  const playedFor = useRef<string | null>(null)

  useEffect(() => {
    if (!enabled) {
      setRevealed(text)
      return
    }
    if (playedFor.current === text) return

    const reduced =
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      playedFor.current = text
      setRevealed(text)
      return
    }

    playedFor.current = text
    let cursor = 0
    let frame = 0
    setRevealed('')

    const step = () => {
      cursor = Math.min(cursor + CHARS_PER_TICK, text.length)
      setRevealed(text.slice(0, cursor))
      if (cursor < text.length) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)

    // Unmounting mid-reveal must not leave a frame running against a dead
    // component, and must not strand the reader on half a sentence if the
    // component comes back.
    return () => {
      cancelAnimationFrame(frame)
      setRevealed(text)
    }
  }, [text, enabled])

  return revealed
}
