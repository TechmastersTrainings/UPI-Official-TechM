/** Seconds as m:ss. */
export function mmss(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Seconds left until `expiresAt`, measured on the server's clock (offsetMs = server − browser). */
export function secondsLeft(expiresAt, nowMs, offsetMs) {
  return Math.max(0, Math.floor((new Date(expiresAt).getTime() - (nowMs + offsetMs)) / 1000));
}

/** The merchant's return URL with payment_id added. Only http(s) URLs are allowed. Carries no status: the
 * merchant must look the payment up server-side, because a redirect is never proof of payment. */
export function returnLink(url, paymentId) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
    u.searchParams.set('payment_id', paymentId);
    return u.toString();
  } catch {
    return null;
  }
}
