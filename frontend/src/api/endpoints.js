import { api } from './client';

export const authApi = {
  login: (email, password) => api.post('/api/auth/login', { email, password }, { _skipAuthRetry: true }).then((r) => r.data),
  logout: () => api.post('/api/auth/logout', null, { _skipAuthRetry: true }),
  me: () => api.get('/api/auth/me').then((r) => r.data),
  changePassword: (current_password, new_password) =>
    api.post('/api/auth/change-password', { current_password, new_password }).then((r) => r.data),
};

export const adminApi = {
  summary: (environment) => api.get('/api/admin/dashboard/summary', { params: { environment } }).then((r) => r.data),
  timeseries: (environment, days) =>
    api.get('/api/admin/dashboard/timeseries', { params: { environment, days } }).then((r) => r.data),
  activity: (environment) => api.get('/api/admin/dashboard/activity', { params: { environment } }).then((r) => r.data),
  auditLogs: (params) => api.get('/api/admin/audit-logs', { params }).then((r) => r.data),
  users: () => api.get('/api/admin/users').then((r) => r.data),
  createUser: (body) => api.post('/api/admin/users', body).then((r) => r.data),
  updateUser: (id, body) => api.patch(`/api/admin/users/${id}`, body).then((r) => r.data),
};

export const merchantApi = {
  register: (body) => api.post('/api/merchant/register', body, { _skipAuthRetry: true }).then((r) => r.data),
  profile: () => api.get('/api/merchant/profile').then((r) => r.data),
  updateProfile: (body) => api.patch('/api/merchant/profile', body).then((r) => r.data),
  readiness: () => api.get('/api/merchant/live-readiness').then((r) => r.data),

  bankAccounts: () => api.get('/api/merchant/bank-accounts').then((r) => r.data),
  createBankAccount: (body) => api.post('/api/merchant/bank-accounts', body).then((r) => r.data),
  updateBankAccount: (id, body) => api.patch(`/api/merchant/bank-accounts/${id}`, body).then((r) => r.data),
  bankAccountAction: (id, action) => api.post(`/api/merchant/bank-accounts/${id}/${action}`).then((r) => r.data),

  providers: () => api.get('/api/merchant/providers').then((r) => r.data),
  providerConfigs: () => api.get('/api/merchant/provider-configs').then((r) => r.data),
  createProviderConfig: (body) => api.post('/api/merchant/provider-configs', body).then((r) => r.data),
  updateProviderConfig: (id, body) => api.patch(`/api/merchant/provider-configs/${id}`, body).then((r) => r.data),
  submitProviderConfig: (id) => api.post(`/api/merchant/provider-configs/${id}/submit`).then((r) => r.data),

  credentials: () => api.get('/api/merchant/api-credentials').then((r) => r.data),
  generateCredential: (body) => api.post('/api/merchant/api-credentials', body).then((r) => r.data),
  regenerateCredential: (id) => api.post(`/api/merchant/api-credentials/${id}/regenerate`).then((r) => r.data),
  revokeCredential: (id) => api.post(`/api/merchant/api-credentials/${id}/revoke`).then((r) => r.data),
  setApiAccess: (enabled) => api.put('/api/merchant/api-access', { enabled }).then((r) => r.data),
  requestLogs: (params) => api.get('/api/merchant/api-request-logs', { params }).then((r) => r.data),

  webhooks: () => api.get('/api/merchant/webhooks').then((r) => r.data),
  saveWebhook: (env, body) => api.put(`/api/merchant/webhooks/${env}`, body).then((r) => r.data),
  rotateWebhookSecret: (env) => api.post(`/api/merchant/webhooks/${env}/rotate-secret`).then((r) => r.data),

  payments: (params) => api.get('/api/merchant/payments', { params }).then((r) => r.data),
  payment: (id) => api.get(`/api/merchant/payments/${id}`).then((r) => r.data),
  webhookDeliveries: (params) => api.get('/api/merchant/webhook-deliveries', { params }).then((r) => r.data),
  webhookDelivery: (id) => api.get(`/api/merchant/webhook-deliveries/${id}`).then((r) => r.data),
  redeliverWebhook: (id) => api.post(`/api/merchant/webhook-deliveries/${id}/redeliver`).then((r) => r.data),
  sendTestWebhook: (env) => api.post(`/api/merchant/webhook-deliveries/test/${env}`).then((r) => r.data),
  cancelPayment: (id, reason) => api.post(`/api/merchant/payments/${id}/cancel`, { reason }).then((r) => r.data),
};

export const adminPaymentApi = {
  list: (params) => api.get('/api/admin/payments', { params }).then((r) => r.data),
  detail: (id) => api.get(`/api/admin/payments/${id}`).then((r) => r.data),
};

export const adminMerchantApi = {
  list: (params) => api.get('/api/admin/merchants', { params }).then((r) => r.data),
  detail: (id) => api.get(`/api/admin/merchants/${id}`).then((r) => r.data),
  statusAction: (id, action, reason) =>
    api.post(`/api/admin/merchants/${id}/${action}`, reason ? { reason } : {}).then((r) => r.data),
  setLive: (id, on) => api.post(`/api/admin/merchants/${id}/live/${on ? 'enable' : 'disable'}`).then((r) => r.data),
  setApiAccess: (id, on) => api.post(`/api/admin/merchants/${id}/api-access/${on ? 'enable' : 'disable'}`).then((r) => r.data),
  verifyBank: (accountId, decision, note) =>
    api.post(`/api/admin/bank-accounts/${accountId}/verification`, { decision, note: note || null }).then((r) => r.data),
  revealBank: (accountId) => api.post(`/api/admin/bank-accounts/${accountId}/reveal`).then((r) => r.data),
  providerAction: (configId, action, reason) =>
    api.post(`/api/admin/provider-configs/${configId}/${action}`, reason ? { reason } : undefined).then((r) => r.data),
};
