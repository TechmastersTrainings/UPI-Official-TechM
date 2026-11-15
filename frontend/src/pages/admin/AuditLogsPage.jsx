import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../api/endpoints';
import { errorMessage } from '../../api/client';
import Alert from '../../components/Alert';
import EmptyState from '../../components/EmptyState';
import Modal from '../../components/Modal';
import Pagination from '../../components/Pagination';
import Spinner from '../../components/Spinner';
import { formatDateTime } from '../../utils/format';

const EMPTY_FILTERS = { action: '', actor: '', entity_type: '', entity_id: '', date_from: '', date_to: '' };
const PAGE_SIZE = 25;

export default function AuditLogsPage() {
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v));
      setData(await adminApi.auditLogs({ ...params, page, page_size: PAGE_SIZE }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => {
    load();
  }, [load]);

  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const apply = (e) => {
    e.preventDefault();
    setPage(1);
    setFilters(draft);
  };
  const reset = () => {
    setDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setPage(1);
  };

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Audit logs</h1>
          <p className="muted">Every security-relevant and state-changing action, with actor, IP and request ID.</p>
        </div>
      </div>

      <form className="card filters" onSubmit={apply}>
        <label className="field">
          <span>Action starts with</span>
          <input value={draft.action} onChange={set('action')} placeholder="auth." />
        </label>
        <label className="field">
          <span>Actor email</span>
          <input value={draft.actor} onChange={set('actor')} />
        </label>
        <label className="field">
          <span>Entity type</span>
          <input value={draft.entity_type} onChange={set('entity_type')} placeholder="user" />
        </label>
        <label className="field">
          <span>Entity ID</span>
          <input value={draft.entity_id} onChange={set('entity_id')} />
        </label>
        <label className="field">
          <span>From (UTC)</span>
          <input type="date" value={draft.date_from} onChange={set('date_from')} />
        </label>
        <label className="field">
          <span>To (UTC)</span>
          <input type="date" value={draft.date_to} onChange={set('date_to')} />
        </label>
        <div className="filters__actions">
          <button type="submit" className="btn btn--primary btn--sm">
            Apply
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
            Reset
          </button>
        </div>
      </form>

      <Alert onRetry={load}>{error}</Alert>

      <section className="card">
        {loading && !data ? (
          <Spinner />
        ) : data?.items.length ? (
          <>
            <div className="table-wrap">
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th>Actor</th>
                    <th>Entity</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} onClick={() => setSelected(a)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setSelected(a)}>
                      <td className="nowrap">{formatDateTime(a.created_at)}</td>
                      <td className="mono">{a.action}</td>
                      <td>{a.actor_label || a.actor_type}</td>
                      <td className="mono">{a.entity_type ? `${a.entity_type}:${a.entity_id ?? ''}` : '—'}</td>
                      <td className="mono">{a.ip_address || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </>
        ) : (
          <EmptyState title="No matching entries" message="Adjust the filters and try again." />
        )}
      </section>

      <Modal open={!!selected} title="Audit entry" onClose={() => setSelected(null)}>
        {selected && (
          <dl className="details">
            {[
              ['ID', selected.id],
              ['Time', formatDateTime(selected.created_at)],
              ['Action', selected.action],
              ['Actor', `${selected.actor_label || '—'} (${selected.actor_type})`],
              ['Actor user ID', selected.actor_user_id || '—'],
              ['Entity', selected.entity_type ? `${selected.entity_type}:${selected.entity_id}` : '—'],
              ['Merchant', selected.merchant_id || '—'],
              ['IP address', selected.ip_address || '—'],
              ['User agent', selected.user_agent || '—'],
              ['Request ID', selected.request_id || '—'],
            ].map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd className="mono">{v}</dd>
              </div>
            ))}
            <div>
              <dt>Details</dt>
              <dd>
                <pre className="code">{selected.details ? JSON.stringify(selected.details, null, 2) : '—'}</pre>
              </dd>
            </div>
          </dl>
        )}
      </Modal>
    </div>
  );
}
