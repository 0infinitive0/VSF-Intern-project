/** Shared email-format check — used by every form that validates an email
 * client-side before calling Supabase (auth-panel.tsx, profile-password-modal.tsx). */
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
