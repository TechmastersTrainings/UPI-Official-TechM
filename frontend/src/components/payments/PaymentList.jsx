import { useState } from 'react';
import { Link } from 'react-router-dom';
import Alert from '../Alert';
import EmptyState from '../EmptyState';
import Pagination from '../Pagination';
import Spinner from '../Spinner';
import StatusBadge from '../StatusBadge';
import useLoad from '../../hooks/useLoad';
import { formatDateTime, formatMoney, humanize } from '../../utils/format';

const PAGE_SIZE = 25;
export const PAYMENT_STATUSES = [
  'CREATED', 'INITIATED', 'PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'EXPIRED', 'CANCELLED',
  'REFUND_PENDING', 'PARTIALLY_REFUNDED', 'REFUNDED',
];

/**
 * Filterable, paginated payment list shared by the merchant and admin consoles.
 * `load(params)` fetches a page; `detailPath(id)` builds the row link.
 */
export default function PaymentList({ title, subtitle, load, detailPath, showMerchant, defaultEnv, emptyHint }) {
  const [env, setEnv] = useState(defaultEnv);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(
    () => load({ environment: env, status: status || undefined, q: query || undefined, page, page_size: PAGE_SIZE }),
    [env, status, query, page],
  );

  function search(e) {
    e.preventDefault();
    setPage(1);
    setQuery(q.trim());
  }

  const filtered = Boolean(status || query);

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>{title}</h1>
          <p className="muted">{subtitle}</p>
        </div>
        <div className="page__actions">
          <div className="segmented" role="group" aria-label="Environment">
            {['LIVE', 'TEST'].map((e) => (
              <button key={e} type="button" className={env === e ? 'is-active' : ''} onClick={() => { setEnv(e); setPage(1); }}>
                {e === 'LIVE' ? 'Live' : 'Sandbox'}
              </button>
            ))}
          </div>
          <button type="button" className="btn btn--secondary btn--sm" onClick={reload} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {env === 'TEST' && <div className="test-banner">Sandbox payments — simulated, no real money moves.</div>}

      <form className="card toolbar" onSubmit={search}>
        <input
          type="search"
          placeholder="Payment ID, merchant reference or order reference"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search payments"
        />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
          <option value="">All statuses</option>
          {PAYMENT_STATUSES.map((s) => (
            <option key={s} value={s}>{humanize(s)}</option>
          ))}
        </select>
        <button type="submit" className="btn btn--primary btn--sm">Search</button>
      </form>

      <Alert onRetry={reload}>{error}</Alert>
      <section className="card">
        {loading && !data ? (
          <Spinner />
        ) : data?.items.length ? (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Payment</th>
                    {showMerchant && <th>Merchant</th>}
                    <th className="num">Amount</th>
                    <th>Status</th>
                    <th>Method</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <Link to={detailPath(p.id)}>{p.merchant_reference}</Link>
                        <div className="muted small mono">{p.id}</div>
                      </td>
                      {showMerchant && <td>{p.merchant_name}</td>}
                      <td className="num nowrap">
                        {formatMoney(p.amount)}
                        {p.amount_refunded > 0 && <div className="muted small">−{formatMoney(p.amount_refunded)} refunded</div>}
                      </td>
                      <td><StatusBadge status={p.status} /></td>
                      <td>{humanize(p.payment_method)}</td>
                      <td className="nowrap">{formatDateTime(p.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </>
        ) : (
          <EmptyState
            title={filtered ? 'No matching payments' : `No ${env === 'LIVE' ? 'live' : 'sandbox'} payments yet`}
            message={filtered ? 'Try different filters.' : emptyHint?.(env)}
          />
        )}
      </section>
    </div>
  );
}
