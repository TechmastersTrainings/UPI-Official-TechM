import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { merchantApi } from '../api/endpoints';
import { useAuth } from '../auth/AuthContext';
import Alert from '../components/Alert';
import { AddressFields, BusinessFields, ContactFields, Field, blanksToNull } from '../components/forms';

const EMPTY = {
  business: { business_name: '', legal_business_name: '', business_email: '', mobile: '', business_type: '', website_url: '' },
  address: { address_line1: '', address_line2: '', city: '', state: '', postal_code: '' },
  contact: { contact_person_name: '', contact_person_email: '', contact_person_mobile: '', pan: '', gstin: '' },
  owner: { full_name: '', email: '', password: '' },
};

export default function RegisterPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (status === 'authenticated') return <Navigate to="/" replace />;

  const section = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e) {
    e.preventDefault();
    setError('');
    if (form.owner.password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      await merchantApi.register({
        business: blanksToNull(form.business),
        address: blanksToNull(form.address),
        contact: blanksToNull(form.contact),
        owner: form.owner,
      });
      await login(form.owner.email, form.owner.password);
      navigate('/merchant/overview', { replace: true });
    } catch (err) {
      setError(errorMessage(err, 'Registration failed'));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page auth-page--wide">
      <div className="auth-card auth-card--wide">
        <div className="brand brand--center">
          <span className="brand__mark" aria-hidden="true">T</span>
          <div>
            <div className="brand__name">TechMasters</div>
            <div className="brand__sub">Payment Gateway</div>
          </div>
        </div>
        <h1 className="auth-card__title">Register your business</h1>
        <p className="muted auth-card__subtitle">
          You can start testing in the sandbox right away. Live payments are enabled after TechMasters review and payment
          provider onboarding.
        </p>
        <Alert>{error}</Alert>
        <form className="form" onSubmit={submit}>
          <fieldset className="fieldset">
            <legend>Business</legend>
            <BusinessFields business={form.business} setBusiness={section('business')} />
          </fieldset>
          <fieldset className="fieldset">
            <legend>Registered address</legend>
            <AddressFields address={form.address} setAddress={section('address')} />
          </fieldset>
          <fieldset className="fieldset">
            <legend>Contact &amp; tax details</legend>
            <ContactFields contact={form.contact} setContact={section('contact')} />
          </fieldset>
          <fieldset className="fieldset">
            <legend>Your login</legend>
            <div className="form-grid">
              <Field label="Your full name" required value={form.owner.full_name}
                onChange={(v) => section('owner')({ ...form.owner, full_name: v })} />
              <Field label="Login email" type="email" required autoComplete="username" value={form.owner.email}
                onChange={(v) => section('owner')({ ...form.owner, email: v })} />
              <Field label="Password" type="password" required minLength={12} autoComplete="new-password" value={form.owner.password}
                onChange={(v) => section('owner')({ ...form.owner, password: v })}
                hint="At least 12 characters with three of: lowercase, uppercase, digit, symbol" />
              <Field label="Confirm password" type="password" required minLength={12} autoComplete="new-password" value={confirm}
                onChange={setConfirm} />
            </div>
          </fieldset>
          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create merchant account'}
          </button>
          <p className="muted center">
            Already registered? <Link to="/login">Sign in</Link>
          </p>
        </form>
      </div>
    </div>
  );
}
