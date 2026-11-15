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
            <Row label="Checkout link">
              <a href={p.checkout_url} target="_blank" rel="noreferrer">Open checkout</a>
            </Row>
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

      {p.attempts?.length > 0 && (
        <section className="card">
          <div className="card__header"><h2>Provider sessions</h2></div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Opened</th>
                  <th>Expires</th>
                </tr>
              </thead>
              <tbody>
                {p.attempts.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <span className="mono small">{a.provider_session_ref || a.id}</span>
                      {a.error_message && <div className="muted small">{a.error_message}</div>}
                    </td>
                    <td>{a.provider_code}</td>
                    <td><StatusBadge status={a.status} /></td>
                    <td className="nowrap">{formatDateTime(a.created_at)}</td>
                    <td className="nowrap">{formatDateTime(a.expires_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {p.transactions?.length > 0 && (
        <section className="card">
          <div className="card__header"><h2>Verified transactions</h2></div>
          <p className="muted small">
            Confirmed by the payment provider. Bank credit to the settlement account is confirmed separately during reconciliation.
          </p>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Provider transaction</th>
                  <th className="num">Amount</th>
                  <th>Bank ref. (RRN)</th>
                  <th>Payer</th>
                  <th>Verified via</th>
                  <th>Verified</th>
                </tr>
              </thead>
              <tbody>
                {p.transactions.map((t) => (
                  <tr key={t.id}>
                    <td className="mono small">{t.provider_transaction_id}</td>
                    <td className="num">{formatMoney(t.amount)}</td>
                    <td className="mono small">{t.bank_reference || '—'}</td>
                    <td className="mono small">{t.payer_vpa_masked || '—'}</td>
                    <td>
                      {t.type === 'REFUND' && <StatusBadge status="REFUNDED" label="Refund" />}{' '}
                      {t.verification_method === 'PROVIDER_WEBHOOK' ? 'Signed callback' : 'Status API'}
                    </td>
                    <td className="nowrap">{formatDateTime(t.verified_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {p.refunds?.length > 0 && (
        <section className="card">
          <div className="card__header"><h2>Refunds</h2></div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Refund</th>
                  <th className="num">Amount</th>
                  <th>Status</th>
                  <th>Reason</th>
                  <th>Created</th>
                  <th>Completed</th>
                </tr>
              </thead>
              <tbody>
                {p.refunds.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span className="mono small">{r.id}</span>
                      {r.provider_refund_ref && <div className="muted small mono">{r.provider_refund_ref}</div>}
                    </td>
                    <td className="num">{formatMoney(r.amount)}</td>
                    <td>
                      <StatusBadge status={r.status} />
                      {r.failure_reason && <div className="muted small">{r.failure_reason}</div>}
                    </td>
                    <td>{r.reason || '—'}</td>
                    <td className="nowrap">{formatDateTime(r.created_at)}</td>
                    <td className="nowrap">{formatDateTime(r.processed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {p.webhook_deliveries?.length > 0 && (
        <section className="card">
          <div className="card__header"><h2>Webhook deliveries</h2></div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Last response</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {p.webhook_deliveries.map((d) => (
                  <tr key={d.id}>
                    <td className="mono small">{d.event_type}</td>
                    <td><StatusBadge status={d.status} /></td>
                    <td className="num">{d.attempt_count}</td>
                    <td className="small">{d.last_response_code ? `HTTP ${d.last_response_code}` : d.last_error || '—'}</td>
                    <td className="nowrap">{formatDateTime(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

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
