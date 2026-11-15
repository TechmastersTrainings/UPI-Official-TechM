import { Link } from 'react-router-dom';
import { merchantApi } from '../../api/endpoints';
import Alert from '../../components/Alert';
import ReadinessList from '../../components/ReadinessList';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import useLoad from '../../hooks/useLoad';
import { formatDateTime } from '../../utils/format';

const STATUS_TEXT = {
  PENDING_REVIEW: 'TechMasters is reviewing your business. You can configure your account and use the sandbox meanwhile.',
  ACTIVE: 'Your merchant account is approved.',
  SUSPENDED: 'Your account is suspended. Configuration changes are disabled; contact TechMasters support.',
  REJECTED: 'Your application was not approved. Contact TechMasters support for details.',
};

export default function OverviewPage() {
  const { data, error, loading, reload } = useLoad(async () => {
    const [profile, readiness] = await Promise.all([merchantApi.profile(), merchantApi.readiness()]);
    return { profile, readiness };
  });

  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;
  const { profile: m, readiness } = data;

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>{m.business_name}</h1>
          <p className="muted mono">{m.id}</p>
        </div>
      </div>
      <Alert onRetry={reload}>{error}</Alert>

      <div className="grid grid--2">
        <section className="card">
          <div className="card__header">
            <h2>Account status</h2>
            <StatusBadge status={m.status} />
          </div>
          <p>{STATUS_TEXT[m.status]}</p>
          {m.status_reason && <p className="muted">Reason: {m.status_reason}</p>}
          <dl className="details details--spaced">
            <div>
              <dt>Live payments</dt>
              <dd>{m.live_enabled ? `Enabled ${formatDateTime(m.live_enabled_at)}` : 'Not enabled'}</dd>
            </div>
            <div>
              <dt>Gateway API access</dt>
              <dd>{m.api_access_enabled ? 'Enabled' : 'Disabled'}</dd>
            </div>
            <div>
              <dt>Registered</dt>
              <dd>{formatDateTime(m.created_at)}</dd>
            </div>
          </dl>
        </section>

        <section className="card">
          <div className="card__header">
            <h2>Go-live checklist</h2>
            <StatusBadge status={readiness.ready ? 'SUCCESS' : 'PENDING'} label={readiness.ready ? 'Ready' : 'In progress'} />
          </div>
          <ReadinessList readiness={readiness} />
          <p className="muted small">
            TechMasters switches on live mode once every item is complete. Entering bank details or a UPI ID alone does not
            authorise live collection.
          </p>
        </section>
      </div>

      <section className="card">
        <div className="card__header">
          <h2>Start testing</h2>
        </div>
        <ol className="steps">
          <li>
            <Link to="/merchant/api-keys">Generate sandbox API keys</Link> (prefix <code>tm_test_</code>).
          </li>
          <li>
            <Link to="/merchant/webhooks">Configure a sandbox webhook URL</Link> and store the signing secret.
          </li>
          <li>Create test payments with the gateway API (available in the next release).</li>
        </ol>
      </section>
    </div>
  );
}
