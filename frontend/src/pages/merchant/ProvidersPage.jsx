import { useState } from 'react';
import { merchantApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import Alert from '../../components/Alert';
import EmptyState from '../../components/EmptyState';
import { Field } from '../../components/forms';
import Modal from '../../components/Modal';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import useAction from '../../hooks/useAction';
import useLoad from '../../hooks/useLoad';
import { formatDateTime } from '../../utils/format';

const emptyCred = () => [{ key: '', value: '' }];

export default function ProvidersPage() {
  const { can } = useAuth();
  const canManage = can('merchant:providers_manage');
  const { data, error, loading, reload } = useLoad(async () => {
    const [providers, configs] = await Promise.all([merchantApi.providers(), merchantApi.providerConfigs()]);
    return { providers, configs };
  });
  const action = useAction();
  const [editing, setEditing] = useState(null); // null | 'new' | config
  const [form, setForm] = useState({ provider_code: '', provider_merchant_id: '', creds: emptyCred() });

  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;
  const liveProviders = data.providers.filter((p) => p.is_live_capable);

  function openNew() {
    setForm({ provider_code: liveProviders[0]?.code || '', provider_merchant_id: '', creds: emptyCred() });
    setEditing('new');
  }

  function openEdit(c) {
    setForm({ provider_code: c.provider.code, provider_merchant_id: c.provider_merchant_id || '',
      creds: c.credential_fields.map((k) => ({ key: k, value: '' })) });
    setEditing(c);
  }

  async function save(e) {
    e.preventDefault();
    const credentials = Object.fromEntries(form.creds.filter((c) => c.key.trim() && c.value).map((c) => [c.key.trim(), c.value]));
    const ok = editing === 'new'
      ? await action.run('save', () => merchantApi.createProviderConfig({
          provider_code: form.provider_code, environment: 'LIVE', provider_merchant_id: form.provider_merchant_id, credentials,
        }), 'Provider configuration saved as draft')
      : await action.run('save', () => merchantApi.updateProviderConfig(editing.id, {
          provider_merchant_id: form.provider_merchant_id,
          ...(Object.keys(credentials).length ? { credentials } : {}),
        }), 'Provider configuration updated');
    if (ok) {
      setEditing(null);
      reload();
    }
  }

  async function submit(c) {
    if (await action.run(c.id, () => merchantApi.submitProviderConfig(c.id), 'Submitted to TechMasters for approval')) reload();
  }

  const setCred = (i, k, v) => setForm((f) => ({ ...f, creds: f.creds.map((c, j) => (j === i ? { ...c, [k]: v } : c)) }));

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Payment providers</h1>
          <p className="muted">
            Live UPI collection runs through an authorised payment provider that has onboarded your business. Credentials are
            encrypted and never displayed again.
          </p>
        </div>
        {canManage && liveProviders.length > 0 && (
          <div className="page__actions">
            <button type="button" className="btn btn--primary btn--sm" onClick={openNew}>
              Add live provider
            </button>
          </div>
        )}
      </div>
      <Alert>{error || action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>
      {liveProviders.length === 0 && (
        <Alert kind="info">
          No live payment provider is integrated on the platform yet. The sandbox is available for testing; live provider
          onboarding opens once TechMasters completes a provider integration.
        </Alert>
      )}

      <section className="card">
        {data.configs.length === 0 ? (
          <EmptyState title="No provider configurations" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Environment</th>
                  <th>Provider merchant ID</th>
                  <th>Credentials</th>
                  <th>Status</th>
                  <th>Updated</th>
                  {canManage && <th className="num">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {data.configs.map((c) => {
                  const managed = c.provider.code === 'sandbox';
                  return (
                    <tr key={c.id}>
                      <td>{c.provider.name}</td>
                      <td>
                        <StatusBadge status={c.environment} />
                      </td>
                      <td className="mono">{c.provider_merchant_id || '—'}</td>
                      <td className="small">{managed ? 'Not required' : c.credential_fields.length ? c.credential_fields.join(', ') : 'Not set'}</td>
                      <td>
                        <StatusBadge status={c.status === 'DRAFT' ? 'CREATED' : c.status === 'SUBMITTED' ? 'PENDING' : c.status} label={c.status} />
                        {c.status_reason && <div className="muted small">{c.status_reason}</div>}
                      </td>
                      <td className="nowrap">{formatDateTime(c.updated_at)}</td>
                      {canManage && (
                        <td className="num nowrap">
                          {!managed && ['DRAFT', 'DISABLED'].includes(c.status) && (
                            <button type="button" className="btn btn--ghost btn--sm" onClick={() => openEdit(c)}>
                              Edit
                            </button>
                          )}
                          {!managed && c.status === 'DRAFT' && (
                            <button type="button" className="btn btn--secondary btn--sm" disabled={action.busy === c.id} onClick={() => submit(c)}>
                              Submit for approval
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Modal
        open={editing !== null}
        title={editing === 'new' ? 'Add live provider' : 'Edit provider configuration'}
        onClose={() => setEditing(null)}
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button type="submit" form="provider-form" className="btn btn--primary" disabled={action.busy === 'save'}>
              Save draft
            </button>
          </>
        }
      >
        <Alert>{action.error}</Alert>
        <form id="provider-form" className="form" onSubmit={save}>
          {editing === 'new' && (
            <label className="field">
              <span>Provider</span>
              <select value={form.provider_code} onChange={(e) => setForm({ ...form, provider_code: e.target.value })}>
                {liveProviders.map((p) => (
                  <option key={p.code} value={p.code}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Field label="Provider merchant ID" required value={form.provider_merchant_id} onChange={(v) => setForm({ ...form, provider_merchant_id: v })} />
          <div className="field">
            <span>API credentials issued by the provider</span>
            {editing !== 'new' && <small className="muted">Leave values blank to keep the stored credentials.</small>}
            {form.creds.map((c, i) => (
              <div className="kv-row" key={i}>
                <input aria-label="Field name" placeholder="field (e.g. key_secret)" value={c.key} onChange={(e) => setCred(i, 'key', e.target.value)} />
                <input aria-label="Value" type="password" autoComplete="off" placeholder="value" value={c.value} onChange={(e) => setCred(i, 'value', e.target.value)} />
              </div>
            ))}
            <button type="button" className="link-btn" onClick={() => setForm((f) => ({ ...f, creds: [...f.creds, { key: '', value: '' }] }))}>
              + Add field
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
