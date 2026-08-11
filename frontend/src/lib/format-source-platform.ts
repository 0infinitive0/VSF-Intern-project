/**
 * format-source-platform.ts — maps a hotel row's source_platform DB value
 * ('agoda' | 'booking', see backend/scripts/database_schema.sql:30) to the
 * OTA's real brand name. Brand names are not translated, so this stays out
 * of the locale JSON like format-stars.ts.
 */
const SOURCE_PLATFORM_LABELS: Record<string, string> = {
  agoda: 'Agoda',
  booking: 'Booking.com',
}

export function formatSourcePlatform(sourcePlatform: string): string {
  return SOURCE_PLATFORM_LABELS[sourcePlatform] ?? sourcePlatform
}
