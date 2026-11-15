import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { errorMessage } from '../api/client';
import Alert from '../components/Alert';
import Spinner from '../components/Spinner';

export default function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (status === 'loading') return <Spinner fullPage label="Checking session" />;
  if (status === 'authenticated') return <Navigate to={location.state?.from || '/'} replace />;

  async function onSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(location.state?.from || '/', { replace: true });
    } catch (err) {
      setError(errorMessage(err, 'Sign in failed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="brand brand--center">
          <span className="brand__mark" aria-hidden="true">T</span>
          <div>
            <div className="brand__name">TechMasters</div>
            <div className="brand__sub">Payment Gateway</div>
          </div>
        </div>
        <h1 className="auth-card__title">Sign in</h1>
        <p className="muted auth-card__subtitle">Use your TechMasters console account.</p>
        <Alert>{error}</Alert>
        <form onSubmit={onSubmit} className="form">
          <label className="field">
            <span>Email</span>
            <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
      <p className="auth-footer muted">© TechMasters Innovations Private Limited</p>
    </div>
  );
}
