import { describe, expect, it } from 'vitest';
import { formatMoney, formatShortDate, humanize, parseRupees } from './format';

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

describe('parseRupees', () => {
  it('converts rupees to integer paise without float error', () => {
    expect(parseRupees('1299.50')).toBe(129950);
    expect(parseRupees('1,299.5')).toBe(129950);
    expect(parseRupees('₹ 0.29')).toBe(29);
    expect(parseRupees('100')).toBe(10000);
  });
  it('rejects invalid amounts', () => {
    for (const bad of ['', '0', '1.234', '-5', 'abc', '1e3']) expect(parseRupees(bad)).toBeNull();
  });
});
