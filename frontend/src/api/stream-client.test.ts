import { afterEach, describe, expect, it, vi } from 'vitest'
import { StreamUnsupported, parseSse, sendMessageStream } from './stream-client'

/** Build a ReadableStream<Uint8Array> that yields the given string chunks in
 * order — simulates network reads that don't align with SSE frame boundaries. */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]))
        i++
      } else {
        controller.close()
      }
    },
  })
}

async function collect(chunks: string[]) {
  const out: { event: string; data: unknown }[] = []
  for await (const frame of parseSse(streamOf(chunks), new AbortController().signal)) {
    out.push(frame)
  }
  return out
}

describe('parseSse', () => {
  it('parses a single complete frame in one chunk', async () => {
    const frames = await collect(['event: phase\ndata: {"key":"received","at":1}\n\n'])
    expect(frames).toEqual([{ event: 'phase', data: { key: 'received', at: 1 } }])
  })

  it('reassembles a frame split across multiple network chunks', async () => {
    const frames = await collect(['event: delta\nda', 'ta: {"text":"xin ', 'chào"}\n\n'])
    expect(frames).toEqual([{ event: 'delta', data: { text: 'xin chào' } }])
  })

  it('skips heartbeat/open comment frames', async () => {
    const frames = await collect([': open\n\n: heartbeat\n\nevent: final\ndata: {"reply":"ok"}\n\n'])
    expect(frames).toEqual([{ event: 'final', data: { reply: 'ok' } }])
  })

  it('parses multiple frames delivered in a single chunk', async () => {
    const frames = await collect([
      'event: phase\ndata: {"key":"received","at":1}\n\nevent: phase\ndata: {"key":"hotel_search","at":2}\n\n',
    ])
    expect(frames.map((f) => f.event)).toEqual(['phase', 'phase'])
    expect(frames[1].data).toEqual({ key: 'hotel_search', at: 2 })
  })

  it('yields the final frame even without a trailing blank-line terminator', async () => {
    const frames = await collect(['event: final\ndata: {"reply":"done"}'])
    expect(frames).toEqual([{ event: 'final', data: { reply: 'done' } }])
  })

  it('drops a malformed frame (invalid JSON) without throwing', async () => {
    const frames = await collect(['event: delta\ndata: not-json\n\nevent: final\ndata: {"reply":"ok"}\n\n'])
    expect(frames).toEqual([{ event: 'final', data: { reply: 'ok' } }])
  })

  it('stops yielding once the signal is aborted', async () => {
    const controller = new AbortController()
    const out: { event: string; data: unknown }[] = []
    controller.abort()
    for await (const frame of parseSse(streamOf(['event: final\ndata: {}\n\n']), controller.signal)) {
      out.push(frame)
    }
    expect(out).toEqual([])
  })
})

// ── sendMessageStream retry-safety boundary ─────────────────────────────────
// Whether it is safe to replay a turn via POST hinges on ONE thing: did the
// server ever return a 200 text/event-stream response? routes.py's
// planner_chat_stream submits the turn to its worker pool BEFORE building
// that response, so once it arrives the turn is running server-side
// regardless of whether any frame was subsequently read.

function mockResponse(streamChunks: string[] | null, init: { status?: number; contentType?: string } = {}) {
  const status = init.status ?? 200
  const contentType = init.contentType ?? 'text/event-stream'
  const body =
    streamChunks === null
      ? null
      : new ReadableStream<Uint8Array>({
          start(controller) {
            const encoder = new TextEncoder()
            for (const chunk of streamChunks) controller.enqueue(encoder.encode(chunk))
            controller.close()
          },
        })
  return {
    ok: status >= 200 && status < 300,
    status,
    body,
    headers: { get: (name: string) => (name.toLowerCase() === 'content-type' ? contentType : null) },
  } as unknown as Response
}

describe('sendMessageStream', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('throws StreamUnsupported when fetch itself rejects (network unreachable)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    await expect(
      sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal),
    ).rejects.toBeInstanceOf(StreamUnsupported)
  })

  it('throws StreamUnsupported on a non-2xx response (e.g. 404 unknown session)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse(null, { status: 404 })))
    await expect(
      sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal),
    ).rejects.toBeInstanceOf(StreamUnsupported)
  })

  it('throws StreamUnsupported when the content-type is not text/event-stream', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockResponse(['event: final\ndata: {}\n\n'], { contentType: 'application/json' })),
    )
    await expect(
      sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal),
    ).rejects.toBeInstanceOf(StreamUnsupported)
  })

  it('resolves with the final payload on a normal stream', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockResponse(['event: final\ndata: {"reply":"hi there"}\n\n'])),
    )
    const data = await sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal)
    expect(data).toEqual({ reply: 'hi there' })
  })

  it('throws a plain Error (NOT StreamUnsupported) when a valid 200 stream closes with zero frames', async () => {
    // The server already accepted and started the turn — this must never be
    // "safe to retry", even though nothing was ever parsed out of the body.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse([])))
    const promise = sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal)
    await expect(promise).rejects.toThrow()
    await expect(promise).rejects.not.toBeInstanceOf(StreamUnsupported)
  })

  it('throws a plain Error (NOT StreamUnsupported) when the stream closes after some frames but no final', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockResponse(['event: phase\ndata: {"key":"received","at":1}\n\n'])),
    )
    const promise = sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal)
    await expect(promise).rejects.toThrow()
    await expect(promise).rejects.not.toBeInstanceOf(StreamUnsupported)
  })

  it('surfaces an `error` frame detail as a plain Error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(mockResponse(['event: error\ndata: {"detail":"Đã xảy ra lỗi máy chủ."}\n\n'])),
    )
    await expect(sendMessageStream('sid', 'hi', 'vi', {}, new AbortController().signal)).rejects.toThrow(
      'Đã xảy ra lỗi máy chủ.',
    )
  })

  it('invokes onPhase/onDelta handlers as frames arrive', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        mockResponse([
          'event: phase\ndata: {"key":"received","at":1}\n\n',
          'event: delta\ndata: {"text":"xin "}\n\n',
          'event: final\ndata: {"reply":"ok"}\n\n',
        ]),
      ),
    )
    const onPhase = vi.fn()
    const onDelta = vi.fn()
    await sendMessageStream('sid', 'hi', 'vi', { onPhase, onDelta }, new AbortController().signal)
    expect(onPhase).toHaveBeenCalledWith('received', 1, { key: 'received', at: 1 })
    expect(onDelta).toHaveBeenCalledWith('xin ')
  })
})
