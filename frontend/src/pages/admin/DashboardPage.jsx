import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../api/endpoints';
import { errorMessage } from '../../api/client';
import Alert from '../../components/Alert';
import BarChart from '../../components/BarChart';
import EmptyState from '../../components/EmptyState';
import Spinner from '../../components/Spinner';
import StatCard from '../../components/StatCard';
import StatusBadge from '../../components/StatusBadge';
import { formatDateTime, formatMoney, formatMoneyCompact, formatNumber, formatShortDate, humanize } from '../../utils/format';

const RANGES = [7, 30, 90];

export default function DashboardPage() {
  const [env, setEnv] = useState('LIVE');
  const [days, setDays] = useState(30);
  const [metric, setMetric] = useState('collected_amount');
  const [state, setState] = useState({ loading: true, error: '', summary: null, series: null, activity: null });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: '' }));
    try {
      const [summary, series, activity] = await Promise.all([
        adminApi.summary(env),
        adminApi.timeseries(env, days),
        adminApi.activity(env),
      ]);
      setState({ loading: false, error: '', summary, series, activity });
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: errorMessage(err) }));
    }
  }, [env, days]);

  useEffect(() => {
    load();
  }, [load]);

  const { summary: s, series, activity, loading, error } = state;
  const isMoney = metric === 'collected_amount';

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Platform overview</h1>
          <p className="muted">
            {s ? `Updated ${formatDateTime(s.generated_at)}` : 'Loading figures'} · Collections are provider-verified payments, not
            bank-credited funds.
          </p>
        </div>
        <div className="page__actions">
          <div className="segmented" role="group" aria-label="Environment">
            {['LIVE', 'TEST'].map((e) => (
              <button key={e} type="button" className={env === e ? 'is-active' : ''} onClick={() => setEnv(e)}>
                {e === 'LIVE' ? 'Live' : 'Sandbox'}
              </button>
            ))}
          </div>
          <button type="button" className="btn btn--secondary btn--sm" onClick={load} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {env === 'TEST' && <div className="test-banner">Sandbox data — simulated payments, no real money moved.</div>}
      <Alert onRetry={load}>{error}</Alert>
      {loading && !s && <Spinner label="Loading dashboard" />}

      {s && (
        <>
          <section className="grid grid--stats" aria-label="Collections">
            <StatCard label="Total collection" value={formatMoney(s.collection.total_amount)} hint={`Net of refunds ${formatMoney(s.collection.net_amount)}`} tone="primary" />
            <StatCard label="Today's collection" value={formatMoney(s.collection.today_amount)} hint="Since 00:00 IST" />
            <StatCard label="This month" value={formatMoney(s.collection.month_amount)} hint="Since the 1st, IST" />
            <StatCard label="Refunds" value={formatNumber(s.refunds.total)} hint={`${formatMoney(s.refunds.succeeded_amount)} refunded · ${s.refunds.in_progress} in progress`} />
          </section>

          <section className="grid grid--stats" aria-label="Payments">
            <StatCard label="Payment requests" value={formatNumber(s.payments.total)} />
            <StatCard label="Successful" value={formatNumber(s.payments.successful)} tone="success" />
            <StatCard label="Failed" value={formatNumber(s.payments.failed)} tone="danger" />
            <StatCard label="Pending" value={formatNumber(s.payments.pending)} tone="warning" hint={`${s.payments.expired} expired · ${s.payments.cancelled} cancelled`} />
          </section>

          <section className="grid grid--stats" aria-label="Platform">
            <StatCard label="Registered merchants" value={formatNumber(s.merchants.total)} />
            <StatCard label="Active merchants" value={formatNumber(s.merchants.active)} hint={`${s.merchants.live_enabled} live-enabled`} />
            <StatCard label="UPI transactions" value={formatNumber(s.upi_transactions)} hint="Provider-verified ledger entries" />
            <StatCard
              label="Live / Sandbox payments"
              value={`${formatNumber(s.environment_counts.LIVE)} / ${formatNumber(s.environment_counts.TEST)}`}
            />
          </section>

          <div className="grid grid--2-1">
            <section className="card">
              <div className="card__header">
                <h2>Trend</h2>
                <div className="card__tools">
                  <select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
                    <option value="collected_amount">Collected amount</option>
                    <option value="created">Payment requests</option>
                    <option value="successful">Successful payments</option>
                    <option value="failed">Failed payments</option>
                  </select>
                  <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Range">
                    {RANGES.map((r) => (
                      <option key={r} value={r}>
                        Last {r} days
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {series && (
                <BarChart
                  ariaLabel={`${humanize(metric)} per day`}
                  data={series.points.map((p) => ({ key: p.date, label: formatShortDate(p.date), value: p[metric] }))}
                  formatValue={isMoney ? formatMoneyCompact : formatNumber}
                />
              )}
            </section>

            <section className="card">
              <div className="card__header">
                <h2>Status summary</h2>
              </div>
              <ul className="status-list">
                {Object.entries(s.payments.by_status).map(([status, count]) => (
                  <li key={status}>
                    <StatusBadge status={status} />
                    <span className="status-list__bar" style={{ '--pct': `${s.payments.total ? (count / s.payments.total) * 100 : 0}%` }} />
                    <span className="status-list__count">{formatNumber(count)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <div className="grid grid--2">
            <section className="card">
              <div className="card__header">
                <h2>Recent payments</h2>
              </div>
              {activity?.recent_payments.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Merchant</th>
                        <th>Reference</th>
                        <th className="num">Amount</th>
                        <th>Status</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activity.recent_payments.map((p) => (
                        <tr key={p.id}>
                          <td>{p.merchant_name}</td>
                          <td className="mono">{p.merchant_reference}</td>
                          <td className="num">{formatMoney(p.amount)}</td>
                          <td>
                            <StatusBadge status={p.status} />
                          </td>
                          <td className="nowrap">{formatDateTime(p.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="No payments yet" message={`No ${env === 'LIVE' ? 'live' : 'sandbox'} payment requests have been created.`} />
              )}
            </section>

            <section className="card">
              <div className="card__header">
                <h2>Recent activity</h2>
              </div>
              {activity?.recent_audit.length ? (
                <ul className="activity">
                  {activity.recent_audit.map((a) => (
                    <li key={a.id}>
                      <span className="activity__action mono">{a.action}</span>
                      <span className="activity__meta">
                        {a.actor_label || 'system'} · {formatDateTime(a.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No activity yet" />
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
