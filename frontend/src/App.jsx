import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import ProtectedRoute from './auth/ProtectedRoute';
import EmptyState from './components/EmptyState';
import AppLayout from './layouts/AppLayout';
import AccountPage from './pages/AccountPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import MerchantDetailPage from './pages/admin/MerchantDetailPage';
import MerchantsPage from './pages/admin/MerchantsPage';
import ApiKeysPage from './pages/merchant/ApiKeysPage';
import BankAccountsPage from './pages/merchant/BankAccountsPage';
import OverviewPage from './pages/merchant/OverviewPage';
import ProfilePage from './pages/merchant/ProfilePage';
import ProvidersPage from './pages/merchant/ProvidersPage';
import WebhooksPage from './pages/merchant/WebhooksPage';
import AuditLogsPage from './pages/admin/AuditLogsPage';
import DashboardPage from './pages/admin/DashboardPage';
import UsersPage from './pages/admin/UsersPage';

function HomeRedirect() {
  const { user, can } = useAuth();
  if (user?.merchant_id) return <Navigate to="/merchant/overview" replace />;
  return <Navigate to={can('dashboard:view') ? '/admin/dashboard' : '/account'} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<HomeRedirect />} />
        <Route path="/admin/dashboard" element={<ProtectedRoute permission="dashboard:view"><DashboardPage /></ProtectedRoute>} />
        <Route path="/admin/users" element={<ProtectedRoute permission="platform_users:view"><UsersPage /></ProtectedRoute>} />
        <Route path="/admin/audit-logs" element={<ProtectedRoute permission="audit:view"><AuditLogsPage /></ProtectedRoute>} />
        <Route path="/admin/merchants" element={<ProtectedRoute permission="merchants:view"><MerchantsPage /></ProtectedRoute>} />
        <Route path="/admin/merchants/:id" element={<ProtectedRoute permission="merchants:view"><MerchantDetailPage /></ProtectedRoute>} />
        <Route path="/merchant/overview" element={<ProtectedRoute permission="merchant:view"><OverviewPage /></ProtectedRoute>} />
        <Route path="/merchant/profile" element={<ProtectedRoute permission="merchant:view"><ProfilePage /></ProtectedRoute>} />
        <Route path="/merchant/bank-accounts" element={<ProtectedRoute permission="merchant:bank_view"><BankAccountsPage /></ProtectedRoute>} />
        <Route path="/merchant/providers" element={<ProtectedRoute permission="merchant:view"><ProvidersPage /></ProtectedRoute>} />
        <Route path="/merchant/api-keys" element={<ProtectedRoute permission="merchant:keys_manage"><ApiKeysPage /></ProtectedRoute>} />
        <Route path="/merchant/webhooks" element={<ProtectedRoute permission="merchant:webhooks_manage"><WebhooksPage /></ProtectedRoute>} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="*" element={<EmptyState title="Page not found" message="Check the address and try again." />} />
      </Route>
    </Routes>
  );
}
