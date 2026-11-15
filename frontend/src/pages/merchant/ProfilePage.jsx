import { useEffect, useState } from 'react';
import { merchantApi } from '../../api/endpoints';
import { useAuth } from '../../auth/AuthContext';
import Alert from '../../components/Alert';
import { AddressFields, BusinessFields, ContactFields, blanksToNull } from '../../components/forms';
import Spinner from '../../components/Spinner';
import useAction from '../../hooks/useAction';
import useLoad from '../../hooks/useLoad';

function toForm(m) {
  const p = m.profile || {};
  return {
    business: {
      business_name: m.business_name, legal_business_name: m.legal_business_name, business_email: m.business_email,
      mobile: m.mobile, business_type: m.business_type, website_url: m.website_url || '',
    },
    address: {
      address_line1: p.address_line1 || '', address_line2: p.address_line2 || '', city: p.city || '', state: p.state || '',
      postal_code: p.postal_code || '',
    },
    contact: {
      contact_person_name: p.contact_person_name || '', contact_person_email: p.contact_person_email || '',
      contact_person_mobile: p.contact_person_mobile || '', pan: p.pan || '', gstin: p.gstin || '',
    },
  };
}

export default function ProfilePage() {
  const { can } = useAuth();
  const editable = can('merchant:profile_edit');
  const { data, error, loading, reload } = useLoad(() => merchantApi.profile());
  const [form, setForm] = useState(null);
  const action = useAction();

  useEffect(() => {
    if (data) setForm(toForm(data));
  }, [data]);

  if (loading && !form) return <Spinner />;
  if (!form) return <Alert onRetry={reload}>{error}</Alert>;

  const section = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  async function save(e) {
    e.preventDefault();
    // eslint-disable-next-line no-unused-vars
    const { business_email, ...business } = form.business;
    const updated = await action.run('save', () => merchantApi.updateProfile({
      ...blanksToNull(business),
      address: blanksToNull(form.address),
      contact: blanksToNull(form.contact),
    }), 'Profile saved');
    if (updated) setForm(toForm(updated));
  }

  return (
    <div className="page">
      <div className="page__header">
        <h1>Business profile</h1>
      </div>
      <Alert>{action.error}</Alert>
      <Alert kind="success">{action.notice}</Alert>
      <form className="form" onSubmit={save}>
        <fieldset className="card fieldset" disabled={!editable}>
          <legend>Business</legend>
          <BusinessFields business={form.business} setBusiness={section('business')} lockEmail />
        </fieldset>
        <fieldset className="card fieldset" disabled={!editable}>
          <legend>Registered address</legend>
          <AddressFields address={form.address} setAddress={section('address')} />
        </fieldset>
        <fieldset className="card fieldset" disabled={!editable}>
          <legend>Contact &amp; tax details</legend>
          <ContactFields contact={form.contact} setContact={section('contact')} />
        </fieldset>
        {editable && (
          <div>
            <button type="submit" className="btn btn--primary" disabled={action.busy === 'save'}>
              {action.busy === 'save' ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}
