import { merchantApi } from '../../api/endpoints';
import { API_BASE_URL } from '../../api/client';
import PaymentList from '../../components/payments/PaymentList';

function hint(env) {
  if (env === 'LIVE') return 'Live payments appear here once TechMasters has enabled live mode for your account.';
  return (
    <>
      Create one from your server with a sandbox API key:
      <pre className="code">{`curl -u "$TM_KEY_ID:$TM_KEY_SECRET" \\
  -H "Idempotency-Key: order-1001" \\
  -H "Content-Type: application/json" \\
  -d '{"merchant_reference":"ORDER-1001","amount":49900}' \\
  ${API_BASE_URL}/api/v1/payments/create`}</pre>
    </>
  );
}

export default function PaymentsPage() {
  return (
    <PaymentList
      title="Payments"
      subtitle="Payment orders created through the gateway API. Status is set by TechMasters from provider-verified data only."
      load={merchantApi.payments}
      detailPath={(id) => `/merchant/payments/${id}`}
      defaultEnv="TEST"
      emptyHint={hint}
    />
  );
}
