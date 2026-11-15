import { useState } from 'react';
import { errorMessage } from '../api/client';

/** Run a mutating API call with busy/error/notice state. Returns the result or undefined on error. */
export default function useAction() {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function run(key, fn, successMessage) {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      const result = await fn();
      if (successMessage) setNotice(successMessage);
      return result;
    } catch (err) {
      const details = err?.response?.data?.error?.details;
      const base = errorMessage(err);
      setError(
        Array.isArray(details) && details[0]?.label
          ? `${base}: ${details.map((d) => d.label).join('; ')}`
          : base,
      );
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  return { busy, error, notice, run, setError, setNotice };
}
