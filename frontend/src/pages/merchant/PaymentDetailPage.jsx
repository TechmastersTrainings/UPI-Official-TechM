import { useState } from 'react';
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

  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;

  async function cancel(reason) {
    setConfirming(false);
    const res = await action.run('cancel', () => merchantApi.cancelPayment(id, reason), 'Payment cancelled');
    if (res) setData(res);
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
