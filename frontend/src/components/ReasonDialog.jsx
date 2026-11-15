import { useEffect, useState } from 'react';
import Modal from './Modal';

/** Confirmation dialog that optionally collects a reason (required for reject/suspend actions). */
export default function ReasonDialog({ open, title, message, confirmLabel = 'Confirm', reasonRequired, reasonOptional, danger, onConfirm, onClose }) {
  const [reason, setReason] = useState('');
  useEffect(() => {
    if (open) setReason('');
  }, [open]);
  const needsInput = reasonRequired || reasonOptional;
  const invalid = reasonRequired && reason.trim().length < 3;

  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={`btn ${danger ? 'btn--danger' : 'btn--primary'}`}
            disabled={invalid}
            onClick={() => onConfirm(reason.trim() || null)}
          >
            {confirmLabel}
          </button>
        </>
      }
    >
      {message && <p>{message}</p>}
      {needsInput && (
        <label className="field">
          <span>{reasonRequired ? 'Reason (required)' : 'Note (optional)'}</span>
          <textarea rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
    </Modal>
  );
}
