/**
 * auth-context.tsx — the app's one React Context (see module docstring
 * rationale: auth state is needed simultaneously in places that aren't in a
 * single prop chain — SidebarRail's account slot, the boot-gate splash, the
 * session-expired modal, and the plain-module fetch wrappers in
 * api/*-client.ts, which can't receive props at all).
 *
 * Boot sequence: every visitor — logged in or not — gets a real Supabase
 * session before the app renders anything else. If none exists yet,
 * signInAnonymously() mints one silently (plan
 * 260814-supabase-auth-and-per-user-history's answer to "where does a guest's
 * chat history live"). `status` stays 'loading' until that resolves; App.tsx
 * gates mounting AppShell (and therefore use-chat-session.ts's own bootstrap)
 * on `status === 'ready'`, so no request ever goes out with no token.
 *
 * Anonymous -> permanent upgrade: converting the CURRENT anonymous user in
 * place (updateUser / linkIdentity) rather than creating a new one is what
 * makes chat history carry over automatically — see registerWithPassword /
 * signInWithGoogle below. Logging into a different, pre-existing account
 * from an anonymous session is NOT a merge (Supabase's linking API only ever
 * attaches a new identity to the current user, and there is no merge API) —
 * guest chat history under the anonymous session cannot carry over in that
 * case. What this app does instead is not show that as an error: when
 * signInWithGoogle()'s linkIdentity attempt fails specifically because the
 * Google identity already belongs to someone else, App.tsx's redirect-return
 * handler (isIdentityAlreadyLinkedError) calls retryGoogleSignIn() to sign
 * straight into that existing account, the same way any other "Continue with
 * Google" click would — see retryGoogleSignIn below.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import type { AuthError, User } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase-client'
import { onSessionExpired } from './session-expired-bus'

type AuthStatus = 'loading' | 'ready'

export interface AuthResult {
  error: AuthError | null
}

/** Shared by updatePassword and setInitialPassword so ProfilePasswordModal's
 * `hasPassword ? updatePassword(...) : setInitialPassword(...)` ternary
 * collapses to one type — setInitialPassword's result just never sets
 * `wrongCurrent`, which is fine since it's optional. */
export interface PasswordChangeResult {
  error: AuthError | null
  wrongCurrent?: boolean
}

interface AuthContextValue {
  status: AuthStatus
  user: User | null
  isAnonymous: boolean
  /** True once a previously-real (non-anonymous) session unexpectedly died —
   * expired refresh token, revoked elsewhere, clock skew against the backend.
   * An anonymous session dying never sets this (see onAuthStateChange below) —
   * that case just re-signs-in anonymously with no user-visible interruption. */
  sessionExpired: boolean
  signInWithPassword: (email: string, password: string) => Promise<AuthResult>
  registerWithPassword: (name: string, email: string, password: string) => Promise<AuthResult>
  signInWithGoogle: () => Promise<AuthResult>
  /** Plain Google sign-in — never linkIdentity, regardless of whether the
   * current session is anonymous. Exists for App.tsx's redirect-return
   * handler to call when signInWithGoogle()'s linkIdentity attempt failed
   * because the Google identity already belongs to a different, pre-existing
   * user: that's not recoverable as a merge, so the next best thing is
   * signing straight into that existing account instead of showing an error. */
  retryGoogleSignIn: () => Promise<AuthResult>
  sendPasswordReset: (email: string) => Promise<AuthResult>
  /** Updates the profile fields shown in ProfilePasswordModal. `email` is only
   * sent to Supabase when it actually changed (an unchanged email would still
   * trigger a needless reconfirmation flow) — everything else lives in
   * user_metadata, same place `registerWithPassword` already puts full_name. */
  updateProfile: (fields: {
    fullName: string
    email: string
    phone: string
    city: string
    dateOfBirth: string
  }) => Promise<AuthResult>
  /** Rotates the password for the signed-in user. Supabase's updateUser() has
   * no separate "verify this is really your current password" call, so this
   * re-authenticates with `currentPassword` first — that doubles as the
   * check ProfilePasswordModal's design requires before accepting a new one.
   * `wrongCurrent` tells the caller which of the two steps failed, so it can
   * show a message scoped to "current password" rather than the generic
   * sign-in error copy. */
  updatePassword: (currentPassword: string, newPassword: string) => Promise<PasswordChangeResult>
  /** Sets a password for a user who has never had one — a Google-only
   * account (no 'email' entry in user.app_metadata.providers). Unlike
   * updatePassword above, there is nothing to re-authenticate against: the
   * account has no password credential yet for signInWithPassword to check,
   * so this goes straight to updateUser(). ProfilePasswordModal is what
   * decides which of the two to call. */
  setInitialPassword: (newPassword: string) => Promise<PasswordChangeResult>
  signOut: () => Promise<void>
  dismissSessionExpired: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth() must be used inside <AuthProvider>')
  return ctx
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [sessionExpired, setSessionExpired] = useState(false)
  // Set synchronously right before this app's own signOut() calls
  // supabase.auth.signOut(), so the SIGNED_OUT handler below can tell "the
  // user chose this" apart from "the token just died on its own" — both fire
  // the identical Supabase event.
  const signingOutRef = useRef(false)
  // Mirrors `user` but read inside the onAuthStateChange closure below,
  // which captures whatever `user` was at effect-setup time otherwise —
  // needed to know whether the session that JUST ended was anonymous.
  const userRef = useRef<User | null>(null)
  userRef.current = user

  useEffect(() => {
    let cancelled = false

    async function boot() {
      const { data } = await supabase.auth.getSession()
      if (cancelled) return
      if (!data.session) {
        const { data: anon, error } = await supabase.auth.signInAnonymously()
        if (error) {
          // eslint-disable-next-line no-console
          console.error('auth-context: anonymous sign-in failed', error)
        }
        if (!cancelled) setUser(anon.user ?? null)
      } else {
        setUser(data.session.user)
      }
      if (!cancelled) setStatus('ready')
    }
    boot()

    const { data: subscription } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        const wasAnonymous = userRef.current?.is_anonymous ?? false
        setUser(null)
        if (signingOutRef.current) {
          // User-initiated — auth-context's own signOut() below already
          // starts a fresh anonymous session; nothing more to do here.
          return
        }
        if (wasAnonymous) {
          // An anonymous session dying is never something the visitor opted
          // into — re-mint one silently, no modal (design brief: "login
          // should not feel like being blocked", which applies doubly to a
          // session the user never knew existed as an account).
          supabase.auth.signInAnonymously().then(({ data, error }) => {
            if (error) {
              // eslint-disable-next-line no-console
              console.error('auth-context: silent anonymous re-sign-in failed', error)
              return
            }
            setUser(data.user ?? null)
          })
        } else {
          setSessionExpired(true)
        }
        return
      }
      setUser(session?.user ?? null)
    })

    return () => {
      cancelled = true
      subscription.subscription.unsubscribe()
    }
  }, [])

  // A 401 an api/*-client.ts fetch wrapper saw mid-session is only visible
  // at the call site, not necessarily through onAuthStateChange (see
  // session-expired-bus.ts's module docstring for why both paths exist).
  useEffect(() => onSessionExpired(() => setSessionExpired(true)), [])

  const signInWithPassword = useCallback(async (email: string, password: string): Promise<AuthResult> => {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    return { error }
  }, [])

  const registerWithPassword = useCallback(
    async (name: string, email: string, password: string): Promise<AuthResult> => {
      if (userRef.current?.is_anonymous) {
        // Converts the SAME user row in place — every session already
        // persisted under this anonymous user_id stays attached to it.
        const { error } = await supabase.auth.updateUser({
          email,
          password,
          data: { full_name: name },
        })
        return { error }
      }
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { full_name: name } },
      })
      return { error }
    },
    [],
  )

  const retryGoogleSignIn = useCallback(async (): Promise<AuthResult> => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    })
    return { error }
  }, [])

  const signInWithGoogle = useCallback(async (): Promise<AuthResult> => {
    if (userRef.current?.is_anonymous) {
      const { error } = await supabase.auth.linkIdentity({
        provider: 'google',
        options: { redirectTo: window.location.origin },
      })
      return { error }
    }
    return retryGoogleSignIn()
  }, [retryGoogleSignIn])

  const sendPasswordReset = useCallback(async (email: string): Promise<AuthResult> => {
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin,
    })
    return { error }
  }, [])

  const updateProfile = useCallback(
    async (fields: {
      fullName: string
      email: string
      phone: string
      city: string
      dateOfBirth: string
    }): Promise<AuthResult> => {
      const payload: Parameters<typeof supabase.auth.updateUser>[0] = {
        data: {
          full_name: fields.fullName,
          phone: fields.phone,
          city: fields.city,
          date_of_birth: fields.dateOfBirth,
        },
      }
      if (fields.email && fields.email !== userRef.current?.email) payload.email = fields.email
      const { error } = await supabase.auth.updateUser(payload)
      return { error }
    },
    [],
  )

  const updatePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const email = userRef.current?.email
    if (email) {
      const { error: reauthError } = await supabase.auth.signInWithPassword({ email, password: currentPassword })
      if (reauthError) return { error: reauthError, wrongCurrent: true }
    }
    const { error } = await supabase.auth.updateUser({ password: newPassword })
    return { error }
  }, [])

  const setInitialPassword = useCallback(async (newPassword: string): Promise<PasswordChangeResult> => {
    const { error } = await supabase.auth.updateUser({ password: newPassword })
    return { error }
  }, [])

  const signOut = useCallback(async () => {
    signingOutRef.current = true
    try {
      await supabase.auth.signOut()
      setUser(null)
      // Guest browsing is always available in this app (plan
      // 260814) — sign-out returns to a fresh anonymous session rather than
      // a dead-end unauthenticated state.
      const { data, error } = await supabase.auth.signInAnonymously()
      if (error) {
        // eslint-disable-next-line no-console
        console.error('auth-context: anonymous re-sign-in after sign-out failed', error)
      } else {
        setUser(data.user ?? null)
      }
    } finally {
      signingOutRef.current = false
    }
  }, [])

  const dismissSessionExpired = useCallback(() => setSessionExpired(false), [])

  const value: AuthContextValue = {
    status,
    user,
    isAnonymous: user?.is_anonymous ?? false,
    sessionExpired,
    signInWithPassword,
    registerWithPassword,
    signInWithGoogle,
    retryGoogleSignIn,
    sendPasswordReset,
    updateProfile,
    updatePassword,
    setInitialPassword,
    signOut,
    dismissSessionExpired,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
