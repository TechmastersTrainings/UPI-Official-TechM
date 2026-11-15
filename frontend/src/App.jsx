import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import ProtectedRoute from './auth/ProtectedRoute';
import EmptyState from './components/EmptyState';
import AppLayout from './layouts/AppLayout';
import AccountPage from './pages/AccountPage';
import LoginPage from './pages/LoginPage';
import AuditLogsPage from './pages/admin/AuditLogsPage';
import DashboardPage from './pages/admin/DashboardPage';
import UsersPage from './pages/admin/UsersPage';

function HomeRedirect() {
  const { can } = useAuth();
  return <Navigate to={can('dashboard:view') ? '/admin/dashboard' : '/account'} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
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
        <Route path="/account" element={<AccountPage />} />
        <Route path="*" element={<EmptyState title="Page not found" message="Check the address and try again." />} />
      </Route>
    </Routes>
  );
}
