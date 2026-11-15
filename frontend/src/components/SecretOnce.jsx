import { useState } from 'react';

/** Displays secrets that the server will never return again, with copy buttons. */
export default function SecretOnce({ title, items, onDone }) {
  const [copied, setCopied] = useState(null);

  async function copy(label, value) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
    } catch {
      setCopied(null);
    }
  }

  return (
    <div className="secret-once" role="alert">
      <div className="secret-once__title">{title}</div>
      <p className="muted">Copy and store this now. For your security it will not be shown again.</p>
      {items.map(([label, value]) => (
        <div className="secret-once__row" key={label}>
          <span className="secret-once__label">{label}</span>
          <code className="secret-once__value">{value}</code>
          <button type="button" className="btn btn--secondary btn--sm" onClick={() => copy(label, value)}>
            {copied === label ? 'Copied' : 'Copy'}
          </button>
        </div>
      ))}
      <button type="button" className="btn btn--primary btn--sm" onClick={onDone}>
        I have stored it securely
      </button>
    </div>
  );
}
