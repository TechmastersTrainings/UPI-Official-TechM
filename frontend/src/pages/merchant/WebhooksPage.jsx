import { useEffect, useState } from 'react';
import { merchantApi } from '../../api/endpoints';
import Alert from '../../components/Alert';
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
            <button type="button" className="btn btn--secondary" disabled={action.busy === 'rotate'} onClick={rotate}>
              Rotate signing secret
            </button>
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
    </div>
  );
}
