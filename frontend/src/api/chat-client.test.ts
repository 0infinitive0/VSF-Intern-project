import { afterEach, describe, expect, it, vi } from 'vitest'
import { pingSession } from './chat-client'
import { onSessionExpired } from '../auth/session-expired-bus'

// The real authHeaders() reads Supabase's cached session; under vitest there
// is none, so it would warn on every call and send no token — stubbing it is
// what lets these tests assert the header actually reaches fetch.
vi.mock('./auth-headers', () => ({
  authHeaders: async () => ({ Authorization: 'Bearer test-token' }),
}))

/** pingSession never reads the body — status alone decides the outcome. */
function statusResponse(status: number): Response {
  return { ok: status >= 200 && status < 300, status } as unknown as Response
}

describe('pingSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the bearer token and hits the /api/v1 base path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(statusResponse(200))
    vi.stubGlobal('fetch', fetchMock)

    await pingSession('sid 1')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/chat/sid%201/plan')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer test-token')
  })

  it('reports alive on 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(statusResponse(200)))
    await expect(pingSession('sid')).resolves.toBe('alive')
  })

  it('reports gone on 404 — the server no longer knows this session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(statusResponse(404)))
    await expect(pingSession('sid')).resolves.toBe('gone')
  })

  it('reports unauthorized on 401 and notifies the session-expired bus', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(statusResponse(401)))
    let notified = false
    const unsubscribe = onSessionExpired(() => {
      notified = true
    })

    await expect(pingSession('sid')).resolves.toBe('unauthorized')
    unsubscribe()
    expect(notified).toBe(true)
  })

  it('reports unknown on a network failure rather than throwing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    await expect(pingSession('sid')).resolves.toBe('unknown')
  })

  // A 500 says the server is unwell, not that the session is gone. Treating it
  // as `gone` would throw away a live conversation over a transient blip.
  it('reports unknown on a server error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(statusResponse(500)))
    await expect(pingSession('sid')).resolves.toBe('unknown')
  })
})
