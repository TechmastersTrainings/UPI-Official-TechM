import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { merchantApi } from '../../api/endpoints';
import Alert from '../../components/Alert';
import EmptyState from '../../components/EmptyState';
import Modal from '../../components/Modal';
import Pagination from '../../components/Pagination';
import { Field } from '../../components/forms';
import SecretOnce from '../../components/SecretOnce';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import useAction from '../../hooks/useAction';
import useLoad from '../../hooks/useLoad';
import { WEBHOOK_EVENTS } from '../../utils/constants';
import { formatDateTime } from '../../utils/format';

function WebhookCard({ env, config, onSaved }) {
  const action = useAction();
  const [form, setForm] = useState({ url: '', events: [...WEBHOOK_EVENTS], is_active: true });
  const [secret, setSecret] = useState(null);

  useEffect(() => {
    if (config) setForm({ url: config.url, events: config.events, is_active: config.is_active });
  }, [config]);

  const toggle = (ev) =>
    setForm((f) => ({ ...f, events: f.events.includes(ev) ? f.events.filter((x) => x !== ev) : [...f.events, ev] }));

  async function save(e) {
    e.preventDefault();
    const res = await action.run('save', () => merchantApi.saveWebhook(env, form), 'Webhook saved');
    if (res) {
      if (res.signing_secret) setSecret(res.signing_secret);
      onSaved();
    }
  }

  async function sendTest() {
    const res = await action.run('test', () => merchantApi.sendTestWebhook(env));
    if (!res) return;
    if (res.status === 'DELIVERED') action.setNotice(`Test event delivered (HTTP ${res.last_response_code}). Endpoint validated.`);
    else action.setError(`Test event not acknowledged: ${res.last_error || 'no 2xx response'}`);
    onSaved();
  }

  async function rotate() {
    const res = await action.run('rotate', () => merchantApi.rotateWebhookSecret(env), 'Signing secret rotated');
    if (res) {
      setSecret(res.signing_secret);
      onSaved();
    }
  }

  return (
    <section className="card">
      <div className="card__header">
        <h2>
          {env === 'LIVE' ? 'Live webhook' : 'Sandbox webhook'} <StatusBadge status={env} />
        </h2>
        {config && (
          <span>
            {config.validated_at ? (
              <StatusBadge status="VERIFIED" label={`Validated ${formatDateTime(config.validated_at)}`} />
            ) : (
              <StatusBadge status="PENDING" label="Not yet validated" />
            )}
          </span>
        )}
      </div>
      <Alert>{action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>
      {secret && <SecretOnce title="Webhook signing secret" items={[['Signing secret', secret]]} onDone={() => setSecret(null)} />}
      <form className="form" onSubmit={save}>
        <Field
          label="Endpoint URL"
          type="url"
          required
          value={form.url}
          onChange={(v) => setForm({ ...form, url: v })}
          placeholder="https://your-server.example.com/payments/webhook"
          hint={env === 'LIVE' ? 'Must be a public HTTPS endpoint.' : 'HTTPS required; http://localhost is allowed only on development servers.'}
        />
        <div className="field">
          <span>Events</span>
          <div className="checkbox-grid">
            {WEBHOOK_EVENTS.map((ev) => (
              <label className="checkbox" key={ev}>
                <input type="checkbox" checked={form.events.includes(ev)} onChange={() => toggle(ev)} />
                <span className="mono">{ev}</span>
              </label>
            ))}
          </div>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Deliver events to this endpoint
        </label>
        {config && (
          <p className="muted small">
            Signing secret: <span className="mono">{config.secret_prefix}…</span>. Each delivery carries an{' '}
            <span className="mono">X-TM-Signature</span> header (HMAC-SHA256 of <span className="mono">timestamp.body</span>).
          </p>
        )}
        <div className="row-actions">
          <button type="submit" className="btn btn--primary" disabled={action.busy === 'save' || form.events.length === 0}>
            {config ? 'Save changes' : 'Create webhook'}
          </button>
          {config && (
            <>
              <button type="button" className="btn btn--secondary" disabled={!!action.busy} onClick={sendTest}>
                {action.busy === 'test' ? 'Sending…' : 'Send test event'}
              </button>
              <button type="button" className="btn btn--secondary" disabled={action.busy === 'rotate'} onClick={rotate}>
                Rotate signing secret
              </button>
            </>
          )}
        </div>
      </form>
    </section>
  );
}

export default function WebhooksPage() {
  const { data, error, loading, reload } = useLoad(() => merchantApi.webhooks());
  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;
  const byEnv = Object.fromEntries(data.map((w) => [w.environment, w]));

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Webhooks</h1>
          <p className="muted">
            We POST signed payment events to your server. A live endpoint must be validated with a signed test event before
            live mode can be enabled.
          </p>
        </div>
      </div>
      <WebhookCard env="TEST" config={byEnv.TEST} onSaved={reload} />
      <WebhookCard env="LIVE" config={byEnv.LIVE} onSaved={reload} />
      <DeliveryLog />
    </div>
  );
}

const PAGE_SIZE = 20;

function DeliveryLog() {
  const [env, setEnv] = useState('TEST');
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const action = useAction();
  const { data, error, loading, reload } = useLoad(
    () => merchantApi.webhookDeliveries({ environment: env, page, page_size: PAGE_SIZE }),
    [env, page],
  );

  async function redeliver(d) {
    const res = await action.run(d.id, () => merchantApi.redeliverWebhook(d.id));
    if (res) {
      if (res.status === 'DELIVERED') action.setNotice(`Event ${res.event_id} delivered.`);
      else action.setError(`Redelivery failed: ${res.last_error || 'no 2xx response'}`);
      reload();
    }
  }

  async function view(d) {
    const res = await action.run('view', () => merchantApi.webhookDelivery(d.id));
    if (res) setOpen(res);
  }

  return (
    <section className="card">
      <div className="card__header">
        <h2>Delivery log</h2>
        <div className="card__tools">
          <div className="segmented" role="group" aria-label="Environment">
            {['TEST', 'LIVE'].map((e) => (
              <button key={e} type="button" className={env === e ? 'is-active' : ''} onClick={() => { setEnv(e); setPage(1); }}>
                {e === 'LIVE' ? 'Live' : 'Sandbox'}
              </button>
            ))}
          </div>
          <button type="button" className="btn btn--ghost btn--sm" onClick={reload} disabled={loading}>Refresh</button>
        </div>
      </div>
      <Alert onRetry={reload}>{error}</Alert>
      <Alert>{action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>
      {loading && !data ? (
        <Spinner />
      ) : data?.items.length ? (
        <>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Last response</th>
                  <th>Created</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {data.items.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <span className="mono">{d.event_type}</span>
                      <div className="muted small mono">{d.event_id}</div>
                      {d.payment_id && <Link className="small" to={`/merchant/payments/${d.payment_id}`}>{d.payment_id}</Link>}
                    </td>
                    <td>
                      <StatusBadge status={d.status} />
                      {d.status === 'RETRYING' && <div className="muted small">Next {formatDateTime(d.next_attempt_at)}</div>}
                    </td>
                    <td className="num">{d.attempt_count}</td>
                    <td className="small">
                      {d.last_response_code ? `HTTP ${d.last_response_code}` : '—'}
                      {d.last_error && <div className="muted">{d.last_error}</div>}
                    </td>
                    <td className="nowrap">{formatDateTime(d.created_at)}</td>
                    <td className="row-actions">
                      <button type="button" className="btn btn--ghost btn--sm" onClick={() => view(d)}>Payload</button>
                      {d.event_type !== 'webhook.test' && (
                        <button type="button" className="btn btn--secondary btn--sm" disabled={!!action.busy} onClick={() => redeliver(d)}>
                          {action.busy === d.id ? 'Sending…' : 'Redeliver'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
        </>
      ) : (
        <EmptyState title="No deliveries yet" message="Events appear here once payments change status and a webhook is configured." />
      )}
      <Modal open={!!open} title={open ? open.event_type : ''} onClose={() => setOpen(null)}>
        {open && <pre className="code">{JSON.stringify(open.payload, null, 2)}</pre>}
      </Modal>
    </section>
  );
}
