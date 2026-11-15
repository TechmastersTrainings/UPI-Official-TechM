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

const BLANK = { environment: 'LIVE', account_holder_name: '', bank_name: '', account_number: '', ifsc: '', upi_vpa: '', make_default: false };

export default function BankAccountsPage() {
  const { can } = useAuth();
  const canManage = can('merchant:bank_manage');
  const canReveal = can('merchant:bank_reveal');
  const { data: accounts, setData, error, loading, reload } = useLoad(() => merchantApi.bankAccounts());
  const action = useAction();
  const [editing, setEditing] = useState(null); // null | 'new' | account
  const [form, setForm] = useState(BLANK);
  const [revealed, setRevealed] = useState({});

  const replace = (acct) => setData((list) => list.map((a) => (a.id === acct.id ? acct : a)));

  function openNew() {
    setForm(BLANK);
    setEditing('new');
  }

  function openEdit(a) {
    setForm({ ...a, account_number: '', upi_vpa: a.upi_vpa || '' });
    setEditing(a);
  }

  async function save(e) {
    e.preventDefault();
    if (editing === 'new') {
      const created = await action.run('save', () =>
        merchantApi.createBankAccount({ ...form, upi_vpa: form.upi_vpa || null }), 'Bank account added and sent for verification');
      if (created) {
        setEditing(null);
        reload();
      }
    } else {
      const body = { account_holder_name: form.account_holder_name, bank_name: form.bank_name, ifsc: form.ifsc };
      if (form.account_number) body.account_number = form.account_number;
      if (form.upi_vpa) body.upi_vpa = form.upi_vpa;
      else if (editing.upi_vpa) body.clear_upi_vpa = true;
      const updated = await action.run('save', () => merchantApi.updateBankAccount(editing.id, body), 'Bank account updated');
      if (updated) {
        replace(updated);
        setEditing(null);
      }
    }
  }

  async function act(a, kind, message) {
    const updated = await action.run(a.id + kind, () => merchantApi.bankAccountAction(a.id, kind), message);
    if (updated) (kind === 'default' ? reload() : replace(updated));
  }

  async function reveal(a) {
    if (revealed[a.id]) {
      setRevealed(({ [a.id]: _, ...rest }) => rest);
      return;
    }
    const res = await action.run(a.id + 'reveal', () => merchantApi.bankAccountAction(a.id, 'reveal'));
    if (res) setRevealed((r) => ({ ...r, [a.id]: res.account_number }));
  }

  const groups = ['LIVE', 'TEST'].map((env) => [env, (accounts || []).filter((a) => a.environment === env)]);

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Bank accounts</h1>
          <p className="muted">Settlement accounts. Account numbers are encrypted and shown masked. Changes to account details require re-verification.</p>
        </div>
        {canManage && (
          <div className="page__actions">
            <button type="button" className="btn btn--primary btn--sm" onClick={openNew}>
              Add bank account
            </button>
          </div>
        )}
      </div>
      <Alert onRetry={accounts ? undefined : reload}>{error || action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>

      {loading && !accounts ? (
        <Spinner />
      ) : (
        groups.map(([env, list]) => (
          <section className="card" key={env}>
            <div className="card__header">
              <h2>
                {env === 'LIVE' ? 'Live' : 'Sandbox'} accounts <StatusBadge status={env} />
              </h2>
            </div>
            {list.length === 0 ? (
              <EmptyState title="No accounts" message={env === 'LIVE' ? 'A verified default live account is required to go live.' : 'Optional: used for sandbox settlement simulation.'} />
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Holder / bank</th>
                      <th>Account</th>
                      <th>IFSC</th>
                      <th>UPI ID</th>
                      <th>Verification</th>
                      <th>Status</th>
                      {canManage && <th className="num">Actions</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <div>{a.account_holder_name}</div>
                          <div className="muted small">{a.bank_name}</div>
                        </td>
                        <td className="mono nowrap">
                          {revealed[a.id] || a.account_number_masked}
                          {canReveal && (
                            <button type="button" className="link-btn" onClick={() => reveal(a)} disabled={action.busy === a.id + 'reveal'}>
                              {revealed[a.id] ? 'Hide' : 'Reveal'}
                            </button>
                          )}
                        </td>
                        <td className="mono">{a.ifsc}</td>
                        <td>{a.upi_vpa || '—'}</td>
                        <td>
                          <StatusBadge status={a.verification_status} />
                          {a.verification_note && <div className="muted small">{a.verification_note}</div>}
                        </td>
                        <td>
                          {a.is_default && <StatusBadge status="ACTIVE" label="Default" />}
                          {!a.is_active && <StatusBadge status="INACTIVE" />}
                        </td>
                        {canManage && (
                          <td className="num nowrap">
                            {!a.is_default && a.is_active && (
                              <button type="button" className="btn btn--ghost btn--sm" onClick={() => act(a, 'default', 'Default account updated')}>
                                Make default
                              </button>
                            )}
                            <button type="button" className="btn btn--ghost btn--sm" onClick={() => openEdit(a)}>
                              Edit
                            </button>
                            <button
                              type="button"
                              className={`btn btn--sm ${a.is_active ? 'btn--danger-ghost' : 'btn--ghost'}`}
                              onClick={() => act(a, a.is_active ? 'deactivate' : 'activate', a.is_active ? 'Account deactivated' : 'Account activated')}
                            >
                              {a.is_active ? 'Deactivate' : 'Activate'}
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))
      )}

      <Modal
        open={editing !== null}
        title={editing === 'new' ? 'Add bank account' : 'Edit bank account'}
        onClose={() => setEditing(null)}
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button type="submit" form="bank-form" className="btn btn--primary" disabled={action.busy === 'save'}>
              {action.busy === 'save' ? 'Saving…' : 'Save'}
            </button>
          </>
        }
      >
        <Alert>{action.error}</Alert>
        <form id="bank-form" className="form" onSubmit={save}>
          {editing === 'new' && (
            <label className="field">
              <span>Environment</span>
              <select value={form.environment} onChange={(e) => setForm({ ...form, environment: e.target.value })}>
                <option value="LIVE">Live</option>
                <option value="TEST">Sandbox</option>
              </select>
            </label>
          )}
          <Field label="Account holder name" required value={form.account_holder_name} onChange={(v) => setForm({ ...form, account_holder_name: v })} />
          <Field label="Bank name" required value={form.bank_name} onChange={(v) => setForm({ ...form, bank_name: v })} />
          <Field
            label="Account number"
            required={editing === 'new'}
            inputMode="numeric"
            autoComplete="off"
            value={form.account_number}
            onChange={(v) => setForm({ ...form, account_number: v.replace(/\D/g, '') })}
            hint={editing !== 'new' ? `Currently ${editing?.account_number_masked}. Leave blank to keep.` : '9–18 digits'}
          />
          <Field label="IFSC" required value={form.ifsc} maxLength={11} onChange={(v) => setForm({ ...form, ifsc: v.toUpperCase() })} />
          <Field label="UPI ID (VPA)" value={form.upi_vpa} onChange={(v) => setForm({ ...form, upi_vpa: v })} placeholder="business@bank" />
          {editing === 'new' && (
            <label className="checkbox">
              <input type="checkbox" checked={form.make_default} onChange={(e) => setForm({ ...form, make_default: e.target.checked })} />
              Make this the default account
            </label>
          )}
        </form>
      </Modal>
    </div>
  );
}
