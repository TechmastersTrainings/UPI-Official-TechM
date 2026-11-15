import { BUSINESS_TYPES, INDIAN_STATES } from '../utils/constants';

/** Controlled text input bound to obj[key]. */
export function Field({ label, value, onChange, hint, type = 'text', required, ...rest }) {
  return (
    <label className="field">
      <span>
        {label}
        {required && <span className="req" aria-hidden="true"> *</span>}
      </span>
      <input type={type} value={value ?? ''} required={required} onChange={(e) => onChange(e.target.value)} {...rest} />
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export function SelectField({ label, value, onChange, options, required }) {
  return (
    <label className="field">
      <span>
        {label}
        {required && <span className="req" aria-hidden="true"> *</span>}
      </span>
      <select value={value ?? ''} required={required} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>
          Select…
        </option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

const STATE_OPTIONS = INDIAN_STATES.map((s) => [s, s]);

/** Business, address and contact sections shared by registration and profile editing. */
export function BusinessFields({ business, setBusiness, lockEmail }) {
  const set = (k) => (v) => setBusiness({ ...business, [k]: v });
  return (
    <div className="form-grid">
      <Field label="Business name" required value={business.business_name} onChange={set('business_name')} maxLength={200} />
      <Field label="Legal business name" required value={business.legal_business_name} onChange={set('legal_business_name')} maxLength={200} />
      <Field label="Business email" type="email" required value={business.business_email} onChange={set('business_email')}
        disabled={lockEmail} hint={lockEmail ? 'Contact TechMasters support to change this' : undefined} />
      <Field label="Mobile number" type="tel" required value={business.mobile} onChange={set('mobile')} placeholder="98765 43210" />
      <SelectField label="Business type" required value={business.business_type} onChange={set('business_type')} options={BUSINESS_TYPES} />
      <Field label="Website URL" type="url" value={business.website_url} onChange={set('website_url')} placeholder="https://" />
    </div>
  );
}

export function AddressFields({ address, setAddress }) {
  const set = (k) => (v) => setAddress({ ...address, [k]: v });
  return (
    <div className="form-grid">
      <Field label="Address line 1" required value={address.address_line1} onChange={set('address_line1')} maxLength={255} />
      <Field label="Address line 2" value={address.address_line2} onChange={set('address_line2')} maxLength={255} />
      <Field label="City" required value={address.city} onChange={set('city')} maxLength={100} />
      <SelectField label="State / UT" required value={address.state} onChange={set('state')} options={STATE_OPTIONS} />
      <Field label="PIN code" required value={address.postal_code} onChange={set('postal_code')} inputMode="numeric" maxLength={6} />
    </div>
  );
}

export function ContactFields({ contact, setContact }) {
  const set = (k) => (v) => setContact({ ...contact, [k]: v });
  return (
    <div className="form-grid">
      <Field label="Contact person" required value={contact.contact_person_name} onChange={set('contact_person_name')} maxLength={150} />
      <Field label="Contact email" type="email" value={contact.contact_person_email} onChange={set('contact_person_email')} />
      <Field label="Contact mobile" type="tel" value={contact.contact_person_mobile} onChange={set('contact_person_mobile')} />
      <Field label="PAN" value={contact.pan} onChange={(v) => set('pan')(v.toUpperCase())} maxLength={10} hint="Required before live payments" />
      <Field label="GSTIN" value={contact.gstin} onChange={(v) => set('gstin')(v.toUpperCase())} maxLength={15} />
    </div>
  );
}

/** Convert '' to null so optional fields validate server-side as absent. */
export function blanksToNull(obj) {
  return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, typeof v === 'string' && v.trim() === '' ? null : v]));
}
