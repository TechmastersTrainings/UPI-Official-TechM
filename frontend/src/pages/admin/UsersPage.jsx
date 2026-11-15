import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../api/endpoints';
import { errorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import Alert from '../../components/Alert';
import Modal from '../../components/Modal';
import Spinner from '../../components/Spinner';
import StatusBadge from '../../components/StatusBadge';
import { formatDateTime, humanize } from '../../utils/format';

const ROLES = ['SUPER_ADMIN', 'PLATFORM_ADMIN', 'PLATFORM_SUPPORT'];
const BLANK = { email: '', full_name: '', password: '', role: 'PLATFORM_SUPPORT' };

export default function UsersPage() {
  const { user: me, can } = useAuth();
  const canManage = can('platform_users:manage');
  const [users, setUsers] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setError('');
    try {
      setUsers(await adminApi.users());
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function update(u, body, message) {
    setBusyId(u.id);
    setError('');
    setNotice('');
    try {
      const updated = await adminApi.updateUser(u.id, body);
      setUsers((list) => list.map((x) => (x.id === u.id ? updated : x)));
      setNotice(message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function create(e) {
    e.preventDefault();
    setSaving(true);
    setFormError('');
    try {
      const created = await adminApi.createUser(form);
      setUsers((list) => [...list, created]);
      setCreateOpen(false);
      setForm(BLANK);
      setNotice(`Created ${created.email}`);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const isLocked = (u) => u.locked_until && new Date(u.locked_until) > new Date();

  return (
    <div className="page">
      <div className="page__header">
        <div>
          <h1>Platform users</h1>
          <p className="muted">TechMasters staff with access to this console. Merchant users are managed per merchant.</p>
        </div>
        {canManage && (
          <div className="page__actions">
            <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreateOpen(true)}>
              Add user
            </button>
          </div>
        )}
      </div>

      <Alert onRetry={users ? undefined : load}>{error}</Alert>
      <Alert kind="success">{notice}</Alert>

      <section className="card">
        {!users ? (
          !error && <Spinner />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last sign-in</th>
                  {canManage && <th className="num">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const self = u.id === me.id;
                  return (
                    <tr key={u.id}>
                      <td>
                        {u.full_name}
                        {self && <span className="muted"> (you)</span>}
                      </td>
                      <td>{u.email}</td>
                      <td>
                        {canManage && !self ? (
                          <select
                            value={u.role}
                            disabled={busyId === u.id}
                            aria-label={`Role for ${u.email}`}
                            onChange={(e) => update(u, { role: e.target.value }, `Role updated for ${u.email}`)}
                          >
                            {ROLES.map((r) => (
                              <option key={r} value={r}>
                                {humanize(r)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          humanize(u.role)
                        )}
                      </td>
                      <td>
                        <StatusBadge status={u.is_active ? 'ACTIVE' : 'INACTIVE'} />
                        {isLocked(u) && <StatusBadge status="LOCKED" />}
                      </td>
                      <td className="nowrap">{formatDateTime(u.last_login_at)}</td>
                      {canManage && (
                        <td className="num nowrap">
                          {isLocked(u) && (
                            <button type="button" className="btn btn--ghost btn--sm" disabled={busyId === u.id}
                              onClick={() => update(u, { unlock: true }, `Unlocked ${u.email}`)}>
                              Unlock
                            </button>
                          )}
                          {!self && (
                            <button
                              type="button"
                              className={`btn btn--sm ${u.is_active ? 'btn--danger-ghost' : 'btn--ghost'}`}
                              disabled={busyId === u.id}
                              onClick={() =>
                                update(u, { is_active: !u.is_active }, `${u.is_active ? 'Deactivated' : 'Activated'} ${u.email}`)
                              }
                            >
                              {u.is_active ? 'Deactivate' : 'Activate'}
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
        open={createOpen}
        title="Add platform user"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn--ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </button>
            <button type="submit" form="create-user" className="btn btn--primary" disabled={saving}>
              {saving ? 'Creating…' : 'Create user'}
            </button>
          </>
        }
      >
        <Alert>{formError}</Alert>
        <form id="create-user" className="form" onSubmit={create}>
          <label className="field">
            <span>Full name</span>
            <input required minLength={2} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </label>
          <label className="field">
            <span>Email</span>
            <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label className="field">
            <span>Initial password</span>
            <input
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            <small className="muted">At least 12 characters with three of: lowercase, uppercase, digit, symbol.</small>
          </label>
          <label className="field">
            <span>Role</span>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {humanize(r)}
                </option>
              ))}
            </select>
          </label>
        </form>
      </Modal>
    </div>
  );
}
