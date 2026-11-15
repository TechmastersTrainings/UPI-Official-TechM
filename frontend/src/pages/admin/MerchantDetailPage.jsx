import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { adminMerchantApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import Alert from '../../components/Alert';
import EmptyState from '../../components/EmptyState';
import ReadinessList from '../../components/ReadinessList';
import ReasonDialog from '../../components/ReasonDialog';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import useAction from '../../hooks/useAction';
import useLoad from '../../hooks/useLoad';
import { formatDateTime, humanize } from '../../utils/format';

const STATUS_ACTIONS = {
  PENDING_REVIEW: [
    { action: 'approve', label: 'Approve' },
    { action: 'reject', label: 'Reject', reason: true, danger: true },
  ],
  ACTIVE: [{ action: 'suspend', label: 'Suspend', reason: true, danger: true }],
  SUSPENDED: [{ action: 'reactivate', label: 'Reactivate' }],
  REJECTED: [{ action: 'reopen', label: 'Reopen review' }],
};

export default function MerchantDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const canManage = can('merchants:manage');
  const canLive = can('merchants:live');
  const canReveal = can('sensitive:reveal');
  const { data, error, loading, reload } = useLoad(() => adminMerchantApi.detail(id), [id]);
  const action = useAction();
  const [dialog, setDialog] = useState(null); // { title, message, reasonRequired, reasonOptional, danger, confirmLabel, run }
  const [revealed, setRevealed] = useState({});

  if (loading && !data) return <Spinner />;
  if (!data) return <Alert onRetry={reload}>{error}</Alert>;
  const { merchant: m, live_readiness: readiness } = data;
  const p = m.profile || {};

  async function exec(key, fn, message) {
    if (await action.run(key, fn, message)) reload();
  }

  function ask(opts) {
    setDialog(opts);
  }

  async function reveal(acct) {
    const res = await action.run('reveal' + acct.id, () => adminMerchantApi.revealBank(acct.id));
    if (res) setRevealed((r) => ({ ...r, [acct.id]: res.account_number }));
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <p className="muted small">
            <Link to="/admin/merchants">Merchants</Link> /
          </p>
          <h1>{m.business_name}</h1>
          <p className="muted">
            {m.legal_business_name} · <span className="mono">{m.id}</span>
          </p>
        </div>
        <div className="page__actions">
          <StatusBadge status={m.status} />
          {canManage &&
            (STATUS_ACTIONS[m.status] || []).map((a) => (
              <button
                key={a.action}
                type="button"
                className={`btn btn--sm ${a.danger ? 'btn--danger-ghost' : 'btn--primary'}`}
                disabled={!!action.busy}
                onClick={() =>
                  ask({
                    title: `${a.label} ${m.business_name}?`,
                    reasonRequired: a.reason,
                    reasonOptional: !a.reason,
                    danger: a.danger,
                    confirmLabel: a.label,
                    run: (reason) => exec(a.action, () => adminMerchantApi.statusAction(m.id, a.action, reason), `Merchant ${a.action} done`),
                  })
                }
              >
                {a.label}
              </button>
            ))}
        </div>
      </div>
      <Alert>{action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>
      {m.status_reason && <Alert kind="info">Status reason: {m.status_reason}</Alert>}

      <div className="grid grid--2">
        <section className="card">
          <div className="card__header">
            <h2>Business</h2>
          </div>
          <dl className="details">
            {[
              ['Business email', m.business_email],
              ['Mobile', m.mobile],
              ['Type', humanize(m.business_type)],
              ['Website', m.website_url || '—'],
              ['Address', [p.address_line1, p.address_line2, p.city, p.state, p.postal_code].filter(Boolean).join(', ')],
              ['Contact', [p.contact_person_name, p.contact_person_email, p.contact_person_mobile].filter(Boolean).join(' · ')],
              ['PAN', p.pan || '—'],
              ['GSTIN', p.gstin || '—'],
              ['Registered', formatDateTime(m.created_at)],
              ['Approved', formatDateTime(m.approved_at)],
            ].map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="card">
          <div className="card__header">
            <h2>Live mode</h2>
            {m.live_enabled ? <StatusBadge status="LIVE" label="Enabled" /> : <StatusBadge status="CREATED" label="Off" />}
          </div>
          <ReadinessList readiness={readiness} />
          <div className="row-actions">
            {canLive &&
              (m.live_enabled ? (
                <button type="button" className="btn btn--danger-ghost btn--sm"
                  onClick={() => ask({ title: 'Disable live payments?', danger: true, confirmLabel: 'Disable live',
                    message: 'Live API keys will stop working immediately.',
                    run: () => exec('live', () => adminMerchantApi.setLive(m.id, false), 'Live mode disabled') })}>
                  Disable live
                </button>
              ) : (
                <button type="button" className="btn btn--primary btn--sm" disabled={!readiness.ready || !!action.busy}
                  title={readiness.ready ? '' : 'All checklist items must be complete'}
                  onClick={() => ask({ title: 'Enable live payments?', confirmLabel: 'Enable live',
                    message: 'The merchant will be able to collect real money through their live provider.',
                    run: () => exec('live', () => adminMerchantApi.setLive(m.id, true), 'Live mode enabled') })}>
                  Enable live
                </button>
              ))}
            {canManage && (
              <button type="button" className="btn btn--secondary btn--sm" disabled={!!action.busy}
                onClick={() => exec('api', () => adminMerchantApi.setApiAccess(m.id, !m.api_access_enabled),
                  m.api_access_enabled ? 'API access disabled' : 'API access enabled')}>
                {m.api_access_enabled ? 'Disable API access' : 'Enable API access'}
              </button>
            )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card__header">
          <h2>Bank accounts</h2>
        </div>
        {data.bank_accounts.length === 0 ? (
          <EmptyState title="No bank accounts" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Env</th>
                  <th>Holder / bank</th>
                  <th>Account</th>
                  <th>IFSC</th>
                  <th>UPI ID</th>
                  <th>Verification</th>
                  <th className="num">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.bank_accounts.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <StatusBadge status={a.environment} />
                    </td>
                    <td>
                      {a.account_holder_name}
                      <div className="muted small">
                        {a.bank_name}
                        {a.is_default && ' · default'}
                        {!a.is_active && ' · inactive'}
                      </div>
                    </td>
                    <td className="mono nowrap">
                      {revealed[a.id] || a.account_number_masked}
                      {canReveal && !revealed[a.id] && (
                        <button type="button" className="link-btn" onClick={() => reveal(a)}>
                          Reveal
                        </button>
                      )}
                    </td>
                    <td className="mono">{a.ifsc}</td>
                    <td>{a.upi_vpa || '—'}</td>
                    <td>
                      <StatusBadge status={a.verification_status} />
                      {a.verification_note && <div className="muted small">{a.verification_note}</div>}
                    </td>
                    <td className="num nowrap">
                      {canManage && a.verification_status === 'PENDING' && (
                        <>
                          <button type="button" className="btn btn--ghost btn--sm"
                            onClick={() => ask({ title: 'Mark account verified?', reasonOptional: true, confirmLabel: 'Verify',
                              message: 'Confirm you have checked supporting documents (e.g. cancelled cheque or bank letter) for this account holder.',
                              run: (note) => exec('v' + a.id, () => adminMerchantApi.verifyBank(a.id, 'VERIFIED', note), 'Bank account verified') })}>
                            Verify
                          </button>
                          <button type="button" className="btn btn--danger-ghost btn--sm"
                            onClick={() => ask({ title: 'Reject bank account?', reasonRequired: true, danger: true, confirmLabel: 'Reject',
                              run: (note) => exec('v' + a.id, () => adminMerchantApi.verifyBank(a.id, 'REJECTED', note), 'Bank account rejected') })}>
                            Reject
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

      <section className="card">
        <div className="card__header">
          <h2>Provider onboarding</h2>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Env</th>
                <th>Provider merchant ID</th>
                <th>Status</th>
                <th>Submitted</th>
                <th className="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.provider_configs.map((c) => {
                const managed = c.provider.code === 'sandbox';
                return (
                  <tr key={c.id}>
                    <td>{c.provider.name}</td>
                    <td>
                      <StatusBadge status={c.environment} />
                    </td>
                    <td className="mono">{c.provider_merchant_id || '—'}</td>
                    <td>
                      {c.status}
                      {c.status_reason && <div className="muted small">{c.status_reason}</div>}
                    </td>
                    <td className="nowrap">{formatDateTime(c.submitted_at)}</td>
                    <td className="num nowrap">
                      {!managed && canManage && c.status === 'SUBMITTED' && (
                        <button type="button" className="btn btn--ghost btn--sm"
                          onClick={() => ask({ title: 'Approve provider onboarding?', confirmLabel: 'Approve',
                            message: `Confirm ${c.provider.name} has completed onboarding/KYC for this merchant under ID ${c.provider_merchant_id}.`,
                            run: () => exec('p' + c.id, () => adminMerchantApi.providerAction(c.id, 'approve'), 'Provider configuration approved') })}>
                          Approve
                        </button>
                      )}
                      {!managed && canManage && ['SUBMITTED', 'APPROVED'].includes(c.status) && (
                        <button type="button" className="btn btn--danger-ghost btn--sm"
                          onClick={() => ask({ title: 'Return to merchant?', reasonRequired: true, danger: true, confirmLabel: 'Reject',
                            run: (r) => exec('p' + c.id, () => adminMerchantApi.providerAction(c.id, 'reject', r), 'Returned to merchant') })}>
                          Reject
                        </button>
                      )}
                      {!managed && canLive && c.status === 'TESTED' && (
                        <button type="button" className="btn btn--primary btn--sm"
                          onClick={() => exec('p' + c.id, () => adminMerchantApi.providerAction(c.id, 'activate'), 'Provider configuration activated')}>
                          Activate
                        </button>
                      )}
                      {!managed && canManage && c.status !== 'DISABLED' && (
                        <button type="button" className="btn btn--danger-ghost btn--sm"
                          onClick={() => ask({ title: 'Disable provider configuration?', reasonRequired: true, danger: true, confirmLabel: 'Disable',
                            run: (r) => exec('p' + c.id, () => adminMerchantApi.providerAction(c.id, 'disable', r), 'Provider configuration disabled') })}>
                          Disable
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid grid--2">
        <section className="card">
          <div className="card__header">
            <h2>API keys</h2>
          </div>
          {data.api_credentials.length === 0 ? (
            <EmptyState title="No keys generated" />
          ) : (
            <ul className="activity">
              {data.api_credentials.map((c) => (
                <li key={c.id}>
                  <span className="mono">
                    {c.key_id} <StatusBadge status={c.status === 'ACTIVE' ? 'ACTIVE' : 'INACTIVE'} label={c.status} />
                  </span>
                  <span className="activity__meta">
                    Created {formatDateTime(c.created_at)} · last used {formatDateTime(c.last_used_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          <div className="card__header">
            <h2>Webhooks &amp; users</h2>
          </div>
          <ul className="activity">
            {data.webhooks.map((w) => (
              <li key={w.id}>
                <span>
                  <StatusBadge status={w.environment} /> <span className="mono">{w.url}</span>
                </span>
                <span className="activity__meta">
                  {w.is_active ? 'Active' : 'Inactive'} · {w.validated_at ? `validated ${formatDateTime(w.validated_at)}` : 'not validated'}
                </span>
              </li>
            ))}
            {data.users.map((u) => (
              <li key={u.id}>
                <span>
                  {u.full_name} · {u.email}
                </span>
                <span className="activity__meta">
                  {humanize(u.role)} · {u.is_active ? 'active' : 'inactive'} · last sign-in {formatDateTime(u.last_login_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <ReasonDialog
        open={!!dialog}
        {...(dialog || {})}
        onConfirm={(reason) => {
          const run = dialog.run;
          setDialog(null);
          run(reason);
        }}
        onClose={() => setDialog(null)}
      />
    </div>
  );
}
