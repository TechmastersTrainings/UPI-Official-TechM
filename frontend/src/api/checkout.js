import axios from 'axios';
import { API_BASE_URL } from './client';

// Public, cookie-less client for the hosted checkout. The checkout token in the URL is the only credential.
const http = axios.create({ baseURL: API_BASE_URL, timeout: 20000, withCredentials: false });

export const checkoutApi = {
  get: (token) => http.get(`/api/v1/checkout/${encodeURIComponent(token)}`).then((r) => r.data),
  simulate: (token, outcome) =>
    http.post(`/api/v1/checkout/${encodeURIComponent(token)}/simulate`, { outcome }).then((r) => r.data),
  initiate: (token) => http.post(`/api/v1/checkout/${encodeURIComponent(token)}/initiate`).then((r) => r.data),
};
