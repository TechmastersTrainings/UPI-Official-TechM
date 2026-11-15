import { describe, expect, it } from 'vitest';
import { formatMoney, formatShortDate, humanize } from './format';

describe('format', () => {
  it('formats paise as INR', () => {
    expect(formatMoney(123456)).toBe('₹1,234.56');
    expect(formatMoney(0)).toBe('₹0.00');
    expect(formatMoney(1000000000)).toBe('₹1,00,00,000.00');
  });

  it('humanizes enum values', () => {
    expect(humanize('PARTIALLY_REFUNDED')).toBe('Partially refunded');
  });

  it('formats ISO dates without timezone drift', () => {
    expect(formatShortDate('2026-11-05')).toMatch(/05 Nov/);
  });
});
