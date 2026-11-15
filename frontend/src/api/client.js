import axios from 'axios';

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

// The access token lives only in memory; the refresh token is an HttpOnly cookie the JS can't read.
let accessToken = null;
let onSessionLost = () => {};

export function setAccessToken(token) {
  accessToken = token;
}

export function setSessionLostHandler(fn) {
  onSessionLost = fn;
}

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  timeout: 20000,
  headers: { 'X-TM-Client': 'dashboard' },
});

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

let refreshPromise = null;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function doRefresh() {
  try {
    return await api.post('/api/auth/refresh', null, { _skipAuthRetry: true });
  } catch (err) {
    // Another tab rotated the cookie a moment ago; the browser now holds the new one.
    if (err.response?.status === 409) {
      await sleep(300);
      return api.post('/api/auth/refresh', null, { _skipAuthRetry: true });
    }
    throw err;
  }
}

/** Single-flight refresh: concurrent 401s share one refresh request. */
export function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = doRefresh()
      .then((res) => {
        setAccessToken(res.data.access_token);
        return res.data;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

const RETRYABLE_AUTH_CODES = new Set(['TOKEN_EXPIRED', 'TOKEN_INVALID', 'AUTH_REQUIRED']);

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const { config, response } = error;
    const code = response?.data?.error?.code;
    if (response?.status === 401 && config && !config._skipAuthRetry && !config._retried && RETRYABLE_AUTH_CODES.has(code)) {
      config._retried = true;
      try {
        await refreshSession();
        return api(config);
      } catch {
        setAccessToken(null);
        onSessionLost();
      }
    } else if (response?.status === 401 && !config?._skipAuthRetry) {
      setAccessToken(null);
      onSessionLost();
    }
    return Promise.reject(error);
  },
);

/** Turn an axios error into a user-facing message using the backend error envelope. */
export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  const e = err?.response?.data?.error;
  if (e?.code === 'VALIDATION_ERROR' && Array.isArray(e.details) && e.details.length) {
    return e.details.map((d) => (d.field ? `${d.field}: ${d.message}` : d.message)).join('; ');
  }
  if (e?.message) return e.message;
  if (err?.code === 'ERR_NETWORK') return 'Cannot reach the server. Check that the API is running.';
  return fallback;
}
