import StatusBadge from '../StatusBadge';
import { formatDateTime, formatMoney, humanize } from '../../utils/format';

const FINAL_NOTE = {
  SUCCESS: 'Confirmed by the payment provider. Settlement to the bank account is tracked separately.',
  FAILED: 'The payment provider reported this payment as failed.',
  EXPIRED: 'The payment window closed before the customer paid.',
  CANCELLED: 'Cancelled before the customer started paying.',
};

function Row({ label, children }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children ?? '—'}</dd>
    </div>
  );
}

/** Read-only payment view with its status timeline. Status shown is exactly what the backend holds. */
export default function PaymentDetail({ payment: p, showMerchant }) {
  return (
    <>
      {p.environment === 'TEST' && <div className="test-banner">Sandbox payment — simulated, no real money moved.</div>}
      {FINAL_NOTE[p.status] && <div className="alert alert--info">{FINAL_NOTE[p.status]}</div>}
      <div className="grid grid--2-1">
        <section className="card">
          <div className="card__header"><h2>Payment</h2></div>
          <dl className="details details--spaced">
            <Row label="Amount"><strong>{formatMoney(p.amount)}</strong> {p.currency}</Row>
            {p.amount_refunded > 0 && <Row label="Refunded">{formatMoney(p.amount_refunded)}</Row>}
            <Row label="Status"><StatusBadge status={p.status} /></Row>
            <Row label="Environment"><StatusBadge status={p.environment} label={p.environment === 'LIVE' ? 'Live' : 'Sandbox'} /></Row>
            {showMerchant && <Row label="Merchant">{p.merchant_name} <span className="muted small mono">{p.merchant_id}</span></Row>}
            <Row label="Payment ID"><span className="mono">{p.id}</span></Row>
            <Row label="Merchant ref."><span className="mono">{p.merchant_reference}</span></Row>
            <Row label="Order ref.">{p.order_reference && <span className="mono">{p.order_reference}</span>}</Row>
            <Row label="Method">{humanize(p.payment_method)}</Row>
            <Row label="Provider">{p.provider_code}</Row>
            {p.failure_reason && <Row label="Failure">{p.failure_reason} {p.failure_code && <span className="muted small">({p.failure_code})</span>}</Row>}
            <Row label="Created">{formatDateTime(p.created_at)}</Row>
            <Row label="Expires">{formatDateTime(p.expires_at)}</Row>
            <Row label="Confirmed">{p.confirmed_at && formatDateTime(p.confirmed_at)}</Row>
          </dl>
        </section>
        <section className="card">
          <div className="card__header"><h2>Customer</h2></div>
          <dl className="details details--spaced">
            <Row label="Name">{p.customer.name}</Row>
            <Row label="Mobile">{p.customer.mobile}</Row>
            <Row label="Email">{p.customer.email}</Row>
            <Row label="Return URL">{p.return_url}</Row>
            <Row label="Webhook URL">{p.webhook_url}</Row>
          </dl>
          {p.notes && Object.keys(p.notes).length > 0 && (
            <>
              <h3 className="small muted">Notes</h3>
              <dl className="details">
                {Object.entries(p.notes).map(([k, v]) => <Row key={k} label={k}>{v}</Row>)}
              </dl>
            </>
          )}
        </section>
      </div>

      <section className="card">
        <div className="card__header"><h2>Timeline</h2></div>
        <ul className="activity">
          {p.events.map((e) => (
            <li key={e.id}>
              <span>
                {e.from_status && e.from_status !== e.to_status ? (
                  <>
                    <StatusBadge status={e.from_status} /> → <StatusBadge status={e.to_status} />
                  </>
                ) : (
                  <strong>{humanize(e.event_type.replace('payment.', ''))}</strong>
                )}
                {e.payload?.reason && <span className="muted"> · {e.payload.reason}</span>}
              </span>
              <span className="activity__meta">
                {formatDateTime(e.created_at)} · {humanize(e.source)}
                {e.payload?.by && ` · ${e.payload.by}`}
                {e.payload?.key_id && ` · ${e.payload.key_id}`}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
