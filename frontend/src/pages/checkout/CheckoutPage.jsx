import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { checkoutApi } from '../../api/checkout';
import { errorMessage } from '../../api/client';
import Spinner from '../../components/Spinner';
import { mmss, returnLink, secondsLeft } from '../../utils/checkout';
import { formatMoney } from '../../utils/format';
import QrCode from './QrCode';

const POLL_MS = 3000;
const AWAITING = ['INITIATED', 'PENDING', 'PROCESSING'];
const COMPLETED = ['SUCCESS', 'REFUND_PENDING', 'PARTIALLY_REFUNDED', 'REFUNDED'];

const FINAL_COPY = {
  SUCCESS: ['Payment received', 'The payment provider has confirmed your payment.'],
  FAILED: ['Payment failed', 'The payment did not go through. If money left your account, your bank will reverse it.'],
  EXPIRED: ['Payment window closed', 'This payment link has expired. Ask the merchant for a new one.'],
  CANCELLED: ['Payment cancelled', 'The merchant cancelled this payment request.'],
};

function useCountdown(expiresAt, offsetMs) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return expiresAt ? secondsLeft(expiresAt, now, offsetMs) : null;
}

export default function CheckoutPage() {
  const { token } = useParams();
  const [view, setView] = useState(null);
  const [offsetMs, setOffsetMs] = useState(0); // server clock minus browser clock
  const [error, setError] = useState('');
  const [fatal, setFatal] = useState('');
  const [starting, setStarting] = useState(false);
  const timer = useRef(null);

  const apply = useCallback((v) => {
    setView(v);
    setOffsetMs(new Date(v.server_time).getTime() - Date.now());
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await checkoutApi.get(token));
      setError('');
    } catch (err) {
      if (err.response?.status === 404) setFatal('This payment link is not valid.');
      else setError(errorMessage(err, 'Could not reach the payment server. Retrying…'));
    }
  }, [token, apply]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while the customer may be paying. The page only ever shows the status the server returns.
  useEffect(() => {
    clearInterval(timer.current);
    if (view && AWAITING.includes(view.status)) timer.current = setInterval(load, POLL_MS);
    return () => clearInterval(timer.current);
  }, [view?.status, load]); // eslint-disable-line react-hooks/exhaustive-deps

  async function pay() {
    setStarting(true);
    setError('');
    try {
      apply(await checkoutApi.initiate(token));
    } catch (err) {
      setError(errorMessage(err, 'Could not start the payment. Please try again.'));
      load();
    } finally {
      setStarting(false);
    }
  }

  const deadline = view?.session?.expires_at || view?.expires_at;
  const remaining = useCountdown(view && (AWAITING.includes(view.status) || view.status === 'CREATED') ? deadline : null, offsetMs);

  if (fatal) {
    return (
      <CheckoutShell>
        <div className="checkout__final">
          <h1>Link not valid</h1>
          <p className="muted">{fatal}</p>
        </div>
      </CheckoutShell>
    );
  }
  if (!view) {
    return (
      <CheckoutShell>
        {error ? <p className="alert alert--error">{error}</p> : <Spinner label="Loading payment" />}
      </CheckoutShell>
    );
  }

  const isTest = view.environment === 'TEST';
  const finalKey = COMPLETED.includes(view.status) ? 'SUCCESS' : view.status;
  const final = FINAL_COPY[finalKey];
  const back = view.return_url && returnLink(view.return_url, view.payment_id);

  return (
    <CheckoutShell test={isTest}>
      <div className="checkout__merchant">{view.merchant_name}</div>
      <div className="checkout__amount">{formatMoney(view.amount)}</div>
      <div className="muted small">Ref. <span className="mono">{view.reference}</span></div>

      {error && <p className="alert alert--error">{error}</p>}

      {view.status === 'CREATED' && (
        <div className="checkout__step">
          <button type="button" className="btn btn--primary btn--block checkout__pay" onClick={pay} disabled={starting || remaining === 0}>
            {starting ? 'Starting…' : `Pay ${formatMoney(view.amount)} with UPI`}
          </button>
          {remaining !== null && (
            <p className="muted small center">{remaining > 0 ? `Link valid for ${mmss(remaining)}` : 'Checking link status…'}</p>
          )}
        </div>
      )}

      {AWAITING.includes(view.status) && view.session && (
        <div className="checkout__step">
          <div className={`checkout__qr${isTest ? ' checkout__qr--test' : ''}`}>
            {view.session.qr_payload && <QrCode value={view.session.qr_payload} label="UPI payment QR code" />}
          </div>
          {isTest ? (
            <p className="small center checkout__test-note">
              Sandbox QR — it uses a test-only format that no UPI app can pay. No real money can move.
            </p>
          ) : (
            <>
              <p className="small center">Scan with any UPI app, then approve the payment in the app.</p>
              {view.session.intent_uri && (
                <a className="btn btn--secondary btn--block checkout__intent" href={view.session.intent_uri}>
                  Open UPI app on this phone
                </a>
              )}
            </>
          )}
          <div className="checkout__status" aria-live="polite">
            <span className="spinner spinner--inline" aria-hidden="true" />
            {remaining > 0 ? (
              <span>
                Waiting for confirmation from the payment provider · <strong>{mmss(remaining)}</strong> left
              </span>
            ) : (
              <span>Time is up. Confirming the final status with the payment provider…</span>
            )}
          </div>
          <p className="muted small center">Keep this page open. Don't pay twice.</p>
        </div>
      )}

      {final && (
        <div className={`checkout__final checkout__final--${finalKey.toLowerCase()}`} role="status">
          <h1>{final[0]}</h1>
          <p className="muted">{final[1]}</p>
          {back && (
            <a className="btn btn--primary btn--block" href={back}>
              Return to {view.merchant_name}
            </a>
          )}
        </div>
      )}
    </CheckoutShell>
  );
}

function CheckoutShell({ test, children }) {
  return (
    <div className="checkout-page">
      {test && <div className="checkout__test-banner">TEST MODE — NO REAL MONEY</div>}
      <main className={`checkout${test ? ' checkout--test' : ''}`}>{children}</main>
      <p className="muted small center checkout__footer">
        Secured by TechMasters Payment Gateway · TechMasters Innovations Private Limited
      </p>
    </div>
  );
}
