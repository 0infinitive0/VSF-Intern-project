import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { consumeOAuthRedirectError, isIdentityAlreadyLinkedError } from './oauth-redirect-error'

// This project's test suite runs in vitest's plain Node environment (no
// jsdom — see hooks/use-chat-session.test.ts's note), so there is no real
// `window`. oauth-redirect-error.ts only touches window.location/
// window.history, so a minimal fake page URL (backed by Node's built-in
// URL, which already implements the parsing/mutation this needs) stands in
// for a real DOM.
let pageUrl: URL

function setUrl(pathAndQueryAndHash: string) {
  pageUrl = new URL(pathAndQueryAndHash, 'http://localhost/')
}

beforeEach(() => {
  setUrl('/')
  vi.stubGlobal('window', {
    get location() {
      return { search: pageUrl.search, hash: pageUrl.hash, pathname: pageUrl.pathname }
    },
    history: {
      replaceState: (_state: unknown, _title: string, newPath: string) => {
        pageUrl = new URL(newPath, pageUrl)
      },
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('consumeOAuthRedirectError', () => {
  it('returns null and leaves the URL untouched when there is no error', () => {
    setUrl('/?foo=bar')

    expect(consumeOAuthRedirectError()).toBeNull()
    expect(window.location.search).toBe('?foo=bar')
  })

  it('reads error_description from the query string', () => {
    setUrl(
      '/?error=invalid_request&error_code=email_exists&error_description=A+user+with+this+email+address+has+already+been+registered',
    )

    const result = consumeOAuthRedirectError()

    expect(result?.message).toBe('A user with this email address has already been registered')
  })

  it('reads error_description from the hash when the query string has none', () => {
    setUrl(
      '/#error=invalid_request&error_code=email_exists&error_description=A+user+with+this+email+address+has+already+been+registered&sb=',
    )

    const result = consumeOAuthRedirectError()

    expect(result?.message).toBe('A user with this email address has already been registered')
  })

  it('falls back to error_code when no description is present', () => {
    setUrl('/?error=access_denied&error_code=access_denied')

    const result = consumeOAuthRedirectError()

    expect(result?.message).toBe('access_denied')
  })

  it('strips the error params from the URL after consuming them, once', () => {
    setUrl('/?error=invalid_request&error_code=email_exists&error_description=oops#error=invalid_request&sb=')

    consumeOAuthRedirectError()

    expect(window.location.search).toBe('')
    expect(window.location.hash).toBe('')
    expect(consumeOAuthRedirectError()).toBeNull()
  })
})

describe('isIdentityAlreadyLinkedError', () => {
  it('matches the identity_already_exists redirect error', () => {
    setUrl(
      '/?error=invalid_request&error_code=identity_already_exists&error_description=Identity+is+already+linked+to+another+user',
    )

    const result = consumeOAuthRedirectError()

    expect(result).not.toBeNull()
    expect(isIdentityAlreadyLinkedError(result!)).toBe(true)
  })

  it('is false for an unrelated auth error', () => {
    setUrl(
      '/?error=invalid_request&error_code=email_exists&error_description=A+user+with+this+email+address+has+already+been+registered',
    )

    const result = consumeOAuthRedirectError()

    expect(result).not.toBeNull()
    expect(isIdentityAlreadyLinkedError(result!)).toBe(false)
  })
})
