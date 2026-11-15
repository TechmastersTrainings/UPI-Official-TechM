import { useState } from 'react';
import { Link } from 'react-router-dom';
import { adminMerchantApi } from '../../api/endpoints';
import Alert from '../../components/Alert';
import EmptyState from '../../components/EmptyState';
import Pagination from '../../components/Pagination';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import useLoad from '../../hooks/useLoad';
import { formatDateTime, humanize } from '../../utils/format';

const PAGE_SIZE = 25;
const STATUSES = ['', 'PENDING_REVIEW', 'ACTIVE', 'SUSPENDED', 'REJECTED'];

export default function MerchantsPage() {
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useLoad(
    () => adminMerchantApi.list({ q: query || undefined, status: status || undefined, page, page_size: PAGE_SIZE }),
    [query, status, page],
  );

  function search(e) {
    e.preventDefault();
    setPage(1);
    setQuery(q.trim());
  }

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Merchants</h1>
          <p className="muted">Review registrations, manage status and control live access.</p>
        </div>
      </div>

      <form className="card toolbar" onSubmit={search}>
        <input type="search" placeholder="Search name, email or merchant ID" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search merchants" />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s ? humanize(s) : 'All statuses'}
            </option>
          ))}
        </select>
        <button type="submit" className="btn btn--primary btn--sm">
          Search
        </button>
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
                    <th>Business</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Live</th>
                    <th>API</th>
                    <th>Registered</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <Link to={`/admin/merchants/${m.id}`}>{m.business_name}</Link>
                        <div className="muted small">{m.business_email}</div>
                      </td>
                      <td>{humanize(m.business_type)}</td>
                      <td>
                        <StatusBadge status={m.status} />
                      </td>
                      <td>{m.live_enabled ? <StatusBadge status="LIVE" label="Enabled" /> : <span className="muted">Off</span>}</td>
                      <td>{m.api_access_enabled ? 'On' : <StatusBadge status="INACTIVE" label="Off" />}</td>
                      <td className="nowrap">{formatDateTime(m.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </>
        ) : (
          <EmptyState title="No merchants found" message={query || status ? 'Try different filters.' : 'Merchants appear here after they register.'} />
        )}
      </section>
    </div>
  );
}
