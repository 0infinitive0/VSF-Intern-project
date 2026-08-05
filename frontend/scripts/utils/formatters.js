// Number/date/currency formatting — pure functions (no `this`, no DOM).
// Root Logic keeps its existing this.vnd()/this.mny()/etc. methods as
// one-line wrappers around these, passing this.isEn() through, so every
// call site elsewhere in the class is untouched. See README for why this
// is window.VOTA.Utils.* rather than an ES export.
window.VOTA = window.VOTA || {};
window.VOTA.Utils = window.VOTA.Utils || {};

window.VOTA.Utils.formatters = {
  // Whole-number VND amount, e.g. vnd(3000000) -> "3.000.000đ" / "VND 3,000,000"
  vnd(n, isEn) {
    return isEn ? 'VND ' + Math.round(n).toLocaleString('en-US') : Math.round(n).toLocaleString('vi-VN') + 'đ';
  },
  // Amount given in millions of VND, e.g. mny(3.2) -> "3,2 triệu ₫" / "VND 3,200,000"
  mny(mil, isEn) {
    if (isEn) return 'VND ' + Math.round(mil * 1000000).toLocaleString('en-US');
    const s = (Math.round(mil * 10) / 10).toString().replace('.', ',');
    return s + ' triệu ₫';
  },
  // Same, abbreviated form: mnyShort(3.2) -> "3,2tr ₫" / "VND 3,200,000"
  mnyShort(mil, isEn) {
    if (isEn) return 'VND ' + Math.round(mil * 1000000).toLocaleString('en-US');
    return (Math.round(mil * 10) / 10).toString().replace('.', ',') + 'tr ₫';
  },
  // ISO date string -> localized display date.
  fmtDate(d, isEn) {
    if (!d) return '';
    const dt = new Date(d);
    if (isEn) return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    return String(dt.getDate()).padStart(2, '0') + '/' + String(dt.getMonth() + 1).padStart(2, '0') + '/' + dt.getFullYear();
  },
  // "N Days N-1 Nights" for a date range (a, b are ISO date strings).
  fmtNights(a, b, isEn) {
    const n = Math.max(0, Math.round((new Date(b) - new Date(a)) / 86400000));
    return isEn ? (n + 1) + ' Days ' + n + ' Nights' : (n + 1) + ' ngày ' + n + ' đêm';
  },
  // One decimal place, VI uses a comma separator.
  num1(n, isEn) {
    const v = (Math.round(n * 10) / 10).toFixed(1);
    return isEn ? v : v.replace('.', ',');
  },
  // "YYYY-MM-DD" -> "DD/MM/YYYY" (VI) or localized short date (EN).
  dmy(s, isEn) {
    if (!s) return '—';
    const p = s.split('-');
    if (isEn) return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    return p[2] + '/' + p[1] + '/' + p[0];
  },
  // year, 0-based month, day -> "YYYY-MM-DD"
  iso(y, m, d) {
    return y + '-' + String(m + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
  },
  // Inclusive night count between two ISO date strings (0 if either is unset).
  countNights(dStart, dEnd) {
    if (!dStart || !dEnd) return 0;
    return Math.round((new Date(dEnd) - new Date(dStart)) / 86400000) + 1;
  },
};
