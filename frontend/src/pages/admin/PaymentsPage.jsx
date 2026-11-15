import { adminPaymentApi } from '../../api/endpoints';
import PaymentList from '../../components/payments/PaymentList';

export default function AdminPaymentsPage() {
  return (
    <PaymentList
      title="Payments"
      subtitle="All merchants' payment orders. Successful means provider-confirmed, not yet bank-credited."
      load={adminPaymentApi.list}
      detailPath={(id) => `/admin/payments/${id}`}
      defaultEnv="LIVE"
      showMerchant
      emptyHint={(env) => (env === 'LIVE' ? 'No merchant has live mode enabled yet.' : 'Merchants create sandbox payments with their test API keys.')}
    />
  );
}
