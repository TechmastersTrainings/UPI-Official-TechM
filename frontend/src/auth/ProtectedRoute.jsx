import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import Spinner from '../components/Spinner';
import EmptyState from '../components/EmptyState';

export default function ProtectedRoute({ permission, children }) {
  const { status, can } = useAuth();
  const location = useLocation();

  if (status === 'loading') return <Spinner fullPage label="Restoring session" />;
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (permission && !can(permission)) {
    return <EmptyState title="Access denied" message="Your role does not have permission to view this page." />;
  }
  return children;
}
