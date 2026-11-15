export const BUSINESS_TYPES = [
  ['SOLE_PROPRIETORSHIP', 'Sole proprietorship'],
  ['PARTNERSHIP', 'Partnership'],
  ['LLP', 'Limited liability partnership'],
  ['PRIVATE_LIMITED', 'Private limited company'],
  ['PUBLIC_LIMITED', 'Public limited company'],
  ['TRUST', 'Trust'],
  ['SOCIETY', 'Society'],
  ['GOVERNMENT', 'Government entity'],
  ['INDIVIDUAL', 'Individual'],
  ['OTHER', 'Other'],
];

export const WEBHOOK_EVENTS = [
  'payment.created',
  'payment.initiated',
  'payment.pending',
  'payment.success',
  'payment.failed',
  'payment.expired',
  'payment.refund_initiated',
  'payment.refunded',
  'settlement.updated',
  'payment.cancelled',
  'payment.refund_failed',
];

export const INDIAN_STATES = [
  'Andaman and Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chandigarh', 'Chhattisgarh',
  'Dadra and Nagar Haveli and Daman and Diu', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir',
  'Jharkhand', 'Karnataka', 'Kerala', 'Ladakh', 'Lakshadweep', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
  'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
  'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
];

/** Sandbox amount rules (the paise decide the simulated outcome). Mirrors app/providers/sandbox.py. */
export const SANDBOX_AMOUNTS = [
  ['₹x.00', 'Succeeds a few seconds after the customer opens the payment'],
  ['₹x.01', 'Fails (declined by the bank)'],
  ['₹x.02', 'Moves to processing and stays there'],
  ['₹x.03', 'Nothing happens; expires at the payment deadline'],
  ['Any other', 'No automatic outcome; use Simulate on the test checkout or POST /api/v1/payments/{id}/simulate'],
  ['Refund of ₹x.01', 'Refund fails; any other refund amount succeeds'],
];
