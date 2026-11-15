import { describe, expect, it } from 'vitest';
import { mmss, returnLink, secondsLeft } from './checkout';

describe('checkout helpers', () => {
  it('formats countdowns', () => {
    expect(mmss(0)).toBe('0:00');
    expect(mmss(65)).toBe('1:05');
    expect(mmss(-3)).toBe('0:00');
  });

  it('counts down on the server clock', () => {
    const exp = '2026-11-15T10:00:00Z';
    const browserNow = Date.parse('2026-11-15T09:59:00Z');
    expect(secondsLeft(exp, browserNow, 0)).toBe(60);
    expect(secondsLeft(exp, browserNow, 30_000)).toBe(30); // server is 30s ahead
    expect(secondsLeft(exp, browserNow + 120_000, 0)).toBe(0);
  });

  it('adds only the payment id to the return URL', () => {
    expect(returnLink('https://shop.example.com/thanks?o=1', 'pay_1')).toBe('https://shop.example.com/thanks?o=1&payment_id=pay_1');
    expect(returnLink('javascript:alert(1)', 'pay_1')).toBeNull();
    expect(returnLink('not a url', 'pay_1')).toBeNull();
  });
});
