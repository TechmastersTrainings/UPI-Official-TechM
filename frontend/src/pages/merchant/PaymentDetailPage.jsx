import { useState } from 'react';
import Modal from '../../components/Modal';
import { formatMoney, parseRupees } from '../../utils/format';
import { Link, useParams } from 'react-router-dom';
import { merchantApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import Alert from '../../components/Alert';
import ReasonDialog from '../../components/ReasonDialog';
import Spinner from '../../components/Spinner';
import PaymentDetail from '../../components/payments/PaymentDetail';
import useAction from '../../hooks/useAction';
import useLoad from '../../hooks/useLoad';

export default function PaymentDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data, setData, error, loading, reload } = useLoad(() => merchantApi.payment(id), [id]);
  const action = useAction();
  const [confirming, setConfirming] = useState(false);
  const [refunding, setRefunding] = useState(null); // { amount, reason, key }

  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;

  async function cancel(reason) {
    setConfirming(false);
    const res = await action.run('cancel', () => merchantApi.cancelPayment(id, reason), 'Payment cancelled');
    if (res) setData(res);
  }

  const refundable = data.amount - data.amount_refunded;
  const canRefund = can('merchant:payments_manage') && ['SUCCESS', 'PARTIALLY_REFUNDED'].includes(data.status);

  function openRefund() {
    // One idempotency key per dialog: a double click or network retry can't refund twice.
    setRefunding({ amount: (refundable / 100).toFixed(2), reason: '', key: crypto.randomUUID() });
  }

  async function submitRefund(e) {
    e.preventDefault();
    const paise = parseRupees(refunding.amount);
    if (!paise || paise > refundable) {
      action.setError(`Enter an amount up to ${formatMoney(refundable)}`);
      return;
    }
    const body = { amount: paise === refundable ? null : paise, reason: refunding.reason.trim() || null };
    const res = await action.run('refund', () => merchantApi.refundPayment(id, body, refunding.key), 'Refund submitted to the provider');
    if (res) {
      setData(res);
      setRefunding(null);
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <p className="muted small"><Link to="/merchant/payments">Payments</Link> /</p>
          <h1>{data.merchant_reference}</h1>
          <p className="muted mono">{data.id}</p>
        </div>
        <div className="page__actions">
          <button type="button" className="btn btn--secondary btn--sm" onClick={reload} disabled={loading}>Refresh</button>
          {canRefund && (
            <button type="button" className="btn btn--secondary btn--sm" disabled={!!action.busy} onClick={openRefund}>
              Refund
            </button>
          )}
          {can('merchant:payments_manage') && data.status === 'CREATED' && (
            <button type="button" className="btn btn--danger-ghost btn--sm" disabled={!!action.busy} onClick={() => setConfirming(true)}>
              Cancel payment
            </button>
          )}
        </div>
      </div>
      <Alert>{action.error}</Alert>
      {action.notice && <div className="alert alert--success">{action.notice}</div>}
      <PaymentDetail payment={data} />
      <Modal
        open={!!refunding}
        title="Refund payment"
        onClose={() => setRefunding(null)}
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setRefunding(null)}>Cancel</button>
            <button type="submit" form="refund-form" className="btn btn--primary" disabled={action.busy === 'refund'}>
              {action.busy === 'refund' ? 'Submitting…' : 'Refund'}
            </button>
          </>
        }
      >
        {refunding && (
          <form id="refund-form" className="form" onSubmit={submitRefund}>
            {data.environment === 'TEST' && <div className="test-banner">Sandbox refund — simulated, no real money moves.</div>}
            <label className="field">
              <span>Amount (₹) — refundable {formatMoney(refundable)}</span>
              <input inputMode="decimal" required value={refunding.amount}
                onChange={(e) => setRefunding({ ...refunding, amount: e.target.value })} />
            </label>
            <label className="field">
              <span>Reason (optional)</span>
              <input maxLength={500} value={refunding.reason} onChange={(e) => setRefunding({ ...refunding, reason: e.target.value })} />
            </label>
            <p className="muted small">The provider confirms the refund; its status updates here and via webhooks.</p>
          </form>
        )}
      </Modal>
      <ReasonDialog
        open={confirming}
        title="Cancel this payment?"
        message="The customer will no longer be able to pay it. This cannot be undone."
        confirmLabel="Cancel payment"
        reasonOptional
        danger
        onConfirm={cancel}
        onClose={() => setConfirming(false)}
      />
    </div>
  );
}
