import { useState } from 'react';
import { merchantApi } from '../../api/endpoints';
import Alert from '../../components/Alert';
import EmptyState from '../../components/EmptyState';
import Pagination from '../../components/Pagination';
import ReasonDialog from '../../components/ReasonDialog';
import SecretOnce from '../../components/SecretOnce';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import useAction from '../../hooks/useAction';
import useLoad from '../../hooks/useLoad';
import { formatDateTime } from '../../utils/format';

const LOG_PAGE = 20;

export default function ApiKeysPage() {
  const { data, setData, error, loading, reload } = useLoad(async () => {
    const [profile, creds] = await Promise.all([merchantApi.profile(), merchantApi.credentials()]);
    return { profile, creds };
  });
  const [logPage, setLogPage] = useState(1);
  const logs = useLoad(() => merchantApi.requestLogs({ page: logPage, page_size: LOG_PAGE }), [logPage]);
  const action = useAction();
  const [secret, setSecret] = useState(null);
  const [confirm, setConfirm] = useState(null); // { kind, cred }

  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;
  const { profile, creds } = data;

  async function generate(environment) {
    const c = await action.run('gen' + environment, () => merchantApi.generateCredential({ environment }));
    if (c) {
      setSecret(c);
      reload();
    }
  }

  async function doConfirm() {
    const { kind, cred } = confirm;
    setConfirm(null);
    if (kind === 'revoke') {
      if (await action.run(cred.id, () => merchantApi.revokeCredential(cred.id), `Revoked ${cred.key_id}`)) reload();
    } else {
      const c = await action.run(cred.id, () => merchantApi.regenerateCredential(cred.id));
      if (c) {
        setSecret(c);
        reload();
      }
    }
  }

  async function toggleAccess() {
    const m = await action.run('access', () => merchantApi.setApiAccess(!profile.api_access_enabled),
      profile.api_access_enabled ? 'API access disabled' : 'API access enabled');
    if (m) setData((d) => ({ ...d, profile: m }));
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>API keys</h1>
          <p className="muted">Authenticate server-to-server calls with HTTP Basic auth: key ID as username, secret as password. Never embed secrets in apps or web pages.</p>
        </div>
      </div>
      <Alert>{action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>
      {secret && (
        <SecretOnce
          title={`New ${secret.environment === 'LIVE' ? 'live' : 'sandbox'} key created`}
          items={[['Key ID', secret.key_id], ['Key secret', secret.key_secret]]}
          onDone={() => setSecret(null)}
        />
      )}

      <section className="card">
        <div className="card__header">
          <h2>Gateway API access</h2>
          <button type="button" className={`btn btn--sm ${profile.api_access_enabled ? 'btn--danger-ghost' : 'btn--primary'}`}
            disabled={action.busy === 'access'} onClick={toggleAccess}>
            {profile.api_access_enabled ? 'Disable API access' : 'Enable API access'}
          </button>
        </div>
        <p>
          API access is <strong>{profile.api_access_enabled ? 'enabled' : 'disabled'}</strong>. Disabling rejects every request
          made with any of your keys until re-enabled.
        </p>
      </section>

      {['TEST', 'LIVE'].map((env) => {
        const list = creds.filter((c) => c.environment === env);
        const liveBlocked = env === 'LIVE' && !profile.live_enabled;
        return (
          <section className="card" key={env}>
            <div className="card__header">
              <h2>
                {env === 'LIVE' ? 'Live keys' : 'Sandbox keys'} <StatusBadge status={env} />
              </h2>
              <button type="button" className="btn btn--secondary btn--sm" disabled={liveBlocked || action.busy === 'gen' + env}
                onClick={() => generate(env)}>
                Generate key
              </button>
            </div>
            {liveBlocked && <p className="muted">Live keys become available after TechMasters enables live mode for your account.</p>}
            {list.length === 0 ? (
              !liveBlocked && <EmptyState title="No keys yet" />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Key ID</th>
                      <th>Secret</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Last used</th>
                      <th className="num">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((c) => (
                      <tr key={c.id}>
                        <td className="mono">{c.key_id}</td>
                        <td className="mono">{c.secret_prefix}…</td>
                        <td>
                          <StatusBadge status={c.status === 'ACTIVE' ? 'ACTIVE' : 'INACTIVE'} label={c.status} />
                        </td>
                        <td className="nowrap">{formatDateTime(c.created_at)}</td>
                        <td className="nowrap">{formatDateTime(c.last_used_at)}</td>
                        <td className="num nowrap">
                          {c.status === 'ACTIVE' && (
                            <>
                              <button type="button" className="btn btn--ghost btn--sm" disabled={action.busy === c.id || liveBlocked}
                                onClick={() => setConfirm({ kind: 'regenerate', cred: c })}>
                                Regenerate
                              </button>
                              <button type="button" className="btn btn--danger-ghost btn--sm" disabled={action.busy === c.id}
                                onClick={() => setConfirm({ kind: 'revoke', cred: c })}>
                                Revoke
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        );
      })}

      <section className="card">
        <div className="card__header">
          <h2>API request log</h2>
          <button type="button" className="btn btn--ghost btn--sm" onClick={logs.reload}>
            Refresh
          </button>
        </div>
        <Alert onRetry={logs.reload}>{logs.error}</Alert>
        {logs.data?.items.length ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Env</th>
                    <th>Request</th>
                    <th>Status</th>
                    <th className="num">Latency</th>
                    <th>Request ID</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.data.items.map((l) => (
                    <tr key={l.id}>
                      <td className="nowrap">{formatDateTime(l.created_at)}</td>
                      <td>{l.environment && <StatusBadge status={l.environment} />}</td>
                      <td className="mono">
                        {l.method} {l.path}
                      </td>
                      <td>
                        <StatusBadge status={l.status_code < 400 ? 'SUCCESS' : 'FAILED'} label={String(l.status_code)} />
                      </td>
                      <td className="num">{l.latency_ms} ms</td>
                      <td className="mono small">{l.request_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={logPage} pageSize={LOG_PAGE} total={logs.data.total} onChange={setLogPage} />
          </>
        ) : (
          !logs.loading && <EmptyState title="No API requests yet" message="Requests made with your keys will appear here." />
        )}
      </section>

      <ReasonDialog
        open={!!confirm}
        title={confirm?.kind === 'revoke' ? 'Revoke key?' : 'Regenerate key?'}
        message={
          confirm?.kind === 'revoke'
            ? `${confirm?.cred.key_id} will stop working immediately.`
            : `${confirm?.cred.key_id} will stop working immediately and a new key will be issued. Update your servers right away.`
        }
        confirmLabel={confirm?.kind === 'revoke' ? 'Revoke' : 'Regenerate'}
        danger
        onConfirm={doConfirm}
        onClose={() => setConfirm(null)}
      />
    </div>
  );
}
