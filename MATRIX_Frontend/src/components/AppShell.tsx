import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router'
import { ArrowUpRight, Bell, ChevronDown, CircleHelp, Command, FileText, KeyRound, LayoutDashboard, LogOut, Menu, Settings2, Shield, Sparkles, UserRound, X } from 'lucide-react'
import { Brand } from './Brand'
import { apiRequest, supabase } from '../lib/client'

const productItems = [
  { to: '/dashboard', label: 'Overview', icon: LayoutDashboard },
  { to: '/premium', label: 'MATRIX Premium', icon: Sparkles },
  { to: '/reports', label: 'Reports', icon: FileText },
]

export function AppShell({ children, section = 'Workspace' }: { children: React.ReactNode; section?: string }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [notice, setNotice] = useState(false)
  const [isVerifiedAdmin, setIsVerifiedAdmin] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => { let alive = true; void apiRequest<unknown>('/api/v1/admin/profiles/pending?limit=1&offset=0').then(() => { if (alive) setIsVerifiedAdmin(true) }).catch(() => { if (alive) setIsVerifiedAdmin(false) }); return () => { alive = false } }, [location.pathname])
  return (
    <div className="app-frame">
      <aside className={`sidebar ${menuOpen ? 'sidebar--open' : ''}`}>
        <div className="sidebar__brand"><Brand /></div>
        <div className="sidebar__label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Workspace navigation">
          {productItems.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} onClick={() => setMenuOpen(false)} className={({ isActive }) => `side-nav__link ${isActive ? 'is-active' : ''}`}><Icon size={17} strokeWidth={1.7} /><span>{label}</span></NavLink>)}
        </nav>
        <div className="sidebar__label sidebar__label--lower">MANAGE</div>
        <nav className="side-nav" aria-label="Management navigation">
          <NavLink to="/account" onClick={() => setMenuOpen(false)} className={({ isActive }) => `side-nav__link ${isActive ? 'is-active' : ''}`}><Settings2 size={17} strokeWidth={1.7} /><span>Account</span></NavLink>
          <NavLink to="/access-status" onClick={() => setMenuOpen(false)} className={({ isActive }) => `side-nav__link ${isActive ? 'is-active' : ''}`}><KeyRound size={17} strokeWidth={1.7} /><span>Access status</span></NavLink>
          <NavLink to="/request-access" onClick={() => setMenuOpen(false)} className={({ isActive }) => `side-nav__link ${isActive ? 'is-active' : ''}`}><Sparkles size={17} strokeWidth={1.7} /><span>Request access</span></NavLink>
          {isVerifiedAdmin && <NavLink to="/admin" onClick={() => setMenuOpen(false)} className={({ isActive }) => `side-nav__link ${isActive ? 'is-active' : ''}`}><Shield size={17} strokeWidth={1.7} /><span>Admin Portal</span></NavLink>}
        </nav>
        <div className="sidebar__bottom">
          <div className="plan-card"><span className="plan-card__icon"><Command size={15} /></span><span><b>Your workspace</b><small>Development preview</small></span><ArrowUpRight size={14} /></div>
          <button className="sidebar__help" onClick={() => setNotice(true)}><CircleHelp size={16} /> Help center</button>
        </div>
      </aside>
      {menuOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
      <div className="workspace">
        <header className="topbar">
          <button className="icon-button mobile-menu-button" aria-label={menuOpen ? 'Close menu' : 'Open menu'} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={19} /> : <Menu size={19} />}</button>
          <div className="topbar__title"><span>{section}</span><span className="topbar__crumb">/</span><b>{titleFor(location.pathname)}</b></div>
          <div className="topbar__actions">
            <span className="preview-pill"><i /> DEV PREVIEW</span>
            <button className="icon-button" aria-label="Notifications" onClick={() => setNotice(!notice)}><Bell size={18} /><i className="notification-dot" /></button>
            <div className="profile-wrap">
              <button className="profile-button" aria-expanded={profileOpen} onClick={() => setProfileOpen(!profileOpen)}><span className="avatar">M</span><span className="profile-name">MATRIX account</span><ChevronDown size={15} /></button>
              {profileOpen && <div className="profile-menu"><div className="profile-menu__intro"><span className="avatar">M</span><span><b>MATRIX account</b><small>Signed-in account</small></span></div><Link to="/account" onClick={() => setProfileOpen(false)}><UserRound size={15} /> Account settings</Link><button onClick={async () => { setProfileOpen(false); await supabase?.auth.signOut(); navigate('/login') }}><LogOut size={15} /> Log out</button></div>}
            </div>
          </div>
          {notice && <div className="notice-pop"><span className="notice-pop__orb"><Bell size={15} /></span><span><b>You're all caught up</b><small>Notifications will appear here.</small></span><button aria-label="Dismiss notification" onClick={() => setNotice(false)}><X size={14} /></button></div>}
        </header>
        <div className="preview-banner"><span>MATRIX WORKSPACE</span><i /> Your account data and assessment records are loaded from the connected services.</div>
        <main className="page-content">{children}</main>
      </div>
    </div>
  )
}

function titleFor(path: string) {
  if (path.startsWith('/premium')) return 'MATRIX Premium'
  if (path.startsWith('/admin')) return 'Admin Portal'
  if (path.startsWith('/reports')) return 'Reports'
  if (path.startsWith('/account')) return 'Account'
  if (path.startsWith('/activate')) return 'Activation code'
  if (path.startsWith('/request-access')) return 'Request access'
  if (path.startsWith('/access-status')) return 'Access status'
  return 'Dashboard'
}
