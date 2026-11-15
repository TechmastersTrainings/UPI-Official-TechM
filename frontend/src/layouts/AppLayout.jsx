import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useTheme } from '../theme/ThemeContext';
import { humanize } from '../utils/format';

// Navigation lists only modules whose backend endpoints exist. New phases add entries here.
const NAV = [
  { to: '/admin/dashboard', label: 'Dashboard', icon: '▦', perm: 'dashboard:view' },
  { to: '/admin/merchants', label: 'Merchants', icon: '▤', perm: 'merchants:view' },
  { to: '/merchant/overview', label: 'Overview', icon: '▦', perm: 'merchant:view' },
  { to: '/merchant/profile', label: 'Business profile', icon: '▤', perm: 'merchant:view' },
  { to: '/merchant/bank-accounts', label: 'Bank accounts', icon: '₹', perm: 'merchant:bank_view' },
  { to: '/merchant/providers', label: 'Payment providers', icon: '⇄', perm: 'merchant:view' },
  { to: '/merchant/api-keys', label: 'API keys', icon: '⚿', perm: 'merchant:keys_manage' },
  { to: '/merchant/webhooks', label: 'Webhooks', icon: '↯', perm: 'merchant:webhooks_manage' },
  { to: '/admin/users', label: 'Platform users', icon: '◎', perm: 'platform_users:view' },
  { to: '/admin/audit-logs', label: 'Audit logs', icon: '≣', perm: 'audit:view' },
  { to: '/account', label: 'My account', icon: '⚙' },
];

const THEME_LABEL = { system: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' };

export default function AppLayout() {
  const { user, logout, can } = useAuth();
  const { mode, cycle } = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setNavOpen(false), [location.pathname]);

  return (
    <div className={`shell${navOpen ? ' shell--nav-open' : ''}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">T</span>
          <div>
            <div className="brand__name">TechMasters</div>
            <div className="brand__sub">Payment Gateway</div>
          </div>
        </div>
        <nav className="nav">
          {NAV.filter((n) => !n.perm || can(n.perm)).map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav__item${isActive ? ' nav__item--active' : ''}`}>
              <span className="nav__icon" aria-hidden="true">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="sidebar__company">TechMasters Innovations Private Limited</div>
        </div>
      </aside>
      <div className="sidebar-backdrop" onClick={() => setNavOpen(false)} aria-hidden="true" />

      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn topbar__menu" aria-label="Open navigation" onClick={() => setNavOpen(true)}>
            ☰
          </button>
          <div className="topbar__spacer" />
          <button type="button" className="btn btn--ghost btn--sm" onClick={cycle} title="Switch theme">
            {THEME_LABEL[mode]}
          </button>
          <div className="topbar__user">
            <div className="topbar__name">{user?.full_name}</div>
            <div className="topbar__role">{humanize(user?.role)}</div>
          </div>
          <button type="button" className="btn btn--secondary btn--sm" onClick={logout}>
            Sign out
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
