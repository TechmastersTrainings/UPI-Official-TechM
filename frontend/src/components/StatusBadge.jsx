import { humanize } from '../utils/format';

const TONES = {
  SUCCESS: 'success', ACTIVE: 'success', VERIFIED: 'success', DELIVERED: 'success', SETTLED: 'success', MATCHED: 'success',
  FAILED: 'danger', REJECTED: 'danger', SUSPENDED: 'danger', MISMATCH: 'danger', INACTIVE: 'danger', LOCKED: 'danger',
  PENDING: 'warning', PROCESSING: 'warning', INITIATED: 'warning', CREATED: 'neutral', PENDING_REVIEW: 'warning',
  REFUND_PENDING: 'warning', PARTIALLY_REFUNDED: 'info', REFUNDED: 'info', INVESTIGATION_REQUIRED: 'danger',
  EXPIRED: 'neutral', CANCELLED: 'neutral', TEST: 'test', LIVE: 'live',
};

export default function StatusBadge({ status, label }) {
  const tone = TONES[status] || 'neutral';
  return <span className={`badge badge--${tone}`}>{label || humanize(status)}</span>;
}
