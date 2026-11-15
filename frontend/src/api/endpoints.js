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
