/**
 * phone-pattern.ts — Vietnamese mobile number format check, same role as
 * email-pattern.ts's EMAIL_RE but exported as a function rather than a bare
 * regex: phone numbers need whitespace/punctuation stripped before matching
 * (the field's own placeholder, "0905 000 000", is grouped with spaces —
 * rejecting that on format alone would be wrong).
 *
 * Matches the post-2018 11→10-digit renumbering carrier prefixes (Viettel,
 * Mobifone, Vinaphone, Vietnamobile, Gmobile, Itelecom), either with the
 * domestic `0` prefix or the `+84` country code.
 */
const VN_PHONE_RE = /^(?:\+84|0)(3[2-9]|5[25689]|7[06-9]|8[1-9]|9[0-9])\d{7}$/

export function isValidPhone(phone: string): boolean {
  return VN_PHONE_RE.test(phone.replace(/[\s.-]/g, ''))
}
