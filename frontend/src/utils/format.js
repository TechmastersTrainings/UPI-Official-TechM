const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 });
const inrCompact = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', notation: 'compact', maximumFractionDigits: 1 });
const num = new Intl.NumberFormat('en-IN');

/** Amounts from the API are integers in paise. */
export const formatMoney = (paise) => inr.format((paise || 0) / 100);
export const formatMoneyCompact = (paise) => inrCompact.format((paise || 0) / 100);
export const formatNumber = (n) => num.format(n || 0);

export function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function formatShortDate(isoDate) {
  const [y, m, d] = isoDate.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

export const humanize = (s) => (s || '').toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());

/** "1,299.50" / "1299.5" → 129950 paise; null when not a positive amount with at most 2 decimals. */
export function parseRupees(text) {
  const v = String(text ?? '').replace(/[,\s₹]/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(v)) return null;
  const [r, p = ''] = v.split('.');
  const paise = Number(r) * 100 + Number(p.padEnd(2, '0'));
  return paise > 0 && Number.isSafeInteger(paise) ? paise : null;
}
