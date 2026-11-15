import { Link, useParams } from 'react-router-dom';
import { adminPaymentApi } from '../../api/endpoints';
import Alert from '../../components/Alert';
import Spinner from '../../components/Spinner';
import PaymentDetail from '../../components/payments/PaymentDetail';
import useLoad from '../../hooks/useLoad';

export default function AdminPaymentDetailPage() {
  const { id } = useParams();
  const { data, error, loading, reload } = useLoad(() => adminPaymentApi.detail(id), [id]);
  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;
  return (
    <div className="page">
      <div className="page__header">
        <div>
          <p className="muted small"><Link to="/admin/payments">Payments</Link> /</p>
          <h1>{data.merchant_reference}</h1>
          <p className="muted"><Link to={`/admin/merchants/${data.merchant_id}`}>{data.merchant_name}</Link></p>
        </div>
        <div className="page__actions">
          <button type="button" className="btn btn--secondary btn--sm" onClick={reload} disabled={loading}>Refresh</button>
        </div>
      </div>
      <PaymentDetail payment={data} showMerchant />
    </div>
  );
}
