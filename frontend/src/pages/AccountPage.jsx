import { useState } from 'react';
import { errorMessage, setAccessToken } from '../api/client';
import { authApi } from '../api/endpoints';
import { useAuth } from '../auth/AuthContext';
import Alert from '../components/Alert';
import { formatDateTime, humanize } from '../utils/format';

export default function AccountPage() {
  const { user } = useAuth();
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setNotice('');
    if (form.next !== form.confirm) {
      setError('New passwords do not match');
      return;
    }
    setSaving(true);
    try {
      const data = await authApi.changePassword(form.current, form.next);
      setAccessToken(data.access_token);
      setForm({ current: '', next: '', confirm: '' });
      setNotice('Password changed. All other sessions have been signed out.');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <div className="page__header">
        <h1>My account</h1>
      </div>
      <div className="grid grid--2">
        <section className="card">
          <div className="card__header">
            <h2>Profile</h2>
          </div>
          <dl className="details">
            {[
              ['Name', user.full_name],
              ['Email', user.email],
              ['Role', humanize(user.role)],
              ['Last sign-in', formatDateTime(user.last_login_at)],
              ['Member since', formatDateTime(user.created_at)],
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
            <h2>Change password</h2>
          </div>
          <Alert>{error}</Alert>
          <Alert kind="success">{notice}</Alert>
          <form className="form" onSubmit={submit}>
            <label className="field">
              <span>Current password</span>
              <input type="password" autoComplete="current-password" required value={form.current}
                onChange={(e) => setForm({ ...form, current: e.target.value })} />
            </label>
            <label className="field">
              <span>New password</span>
              <input type="password" autoComplete="new-password" required minLength={12} value={form.next}
                onChange={(e) => setForm({ ...form, next: e.target.value })} />
              <small className="muted">At least 12 characters with three of: lowercase, uppercase, digit, symbol.</small>
            </label>
            <label className="field">
              <span>Confirm new password</span>
              <input type="password" autoComplete="new-password" required minLength={12} value={form.confirm}
                onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
            </label>
            <button type="submit" className="btn btn--primary" disabled={saving}>
              {saving ? 'Saving…' : 'Change password'}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
