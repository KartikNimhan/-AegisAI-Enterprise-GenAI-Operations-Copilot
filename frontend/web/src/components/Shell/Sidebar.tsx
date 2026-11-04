import { NavLink } from 'react-router-dom'
import { isAdmin, useAccount } from '../../auth/AccountContext'
import { Icon, type IconName } from '../Icon'
import styles from './Sidebar.module.css'

interface NavItem {
  to: string
  label: string
  icon: IconName
  /** Listed for administrators only. The backend refuses everyone else on its own (403). */
  adminOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Copilot', icon: 'chat' },
  { to: '/overview', label: 'Overview', icon: 'overview' },
  { to: '/conversations', label: 'Conversations', icon: 'history' },
  { to: '/documents', label: 'Documents', icon: 'documents' },
  { to: '/memory', label: 'Memory', icon: 'memory' },
  { to: '/operations', label: 'Operations', icon: 'operations' },
  { to: '/system', label: 'System Status', icon: 'status', adminOnly: true },
]

export function Sidebar({
  collapsed,
  onToggle,
  id,
  className = '',
  onNavigate,
  onCloseDrawer,
}: {
  collapsed: boolean
  onToggle: () => void
  id?: string
  className?: string
  /** Called when a navigation link is followed (the drawer closes, even on the current page). */
  onNavigate?: () => void
  /** Given only while the sidebar is open as a drawer: renders the drawer's Close button. */
  onCloseDrawer?: () => void
}) {
  const admin = isAdmin(useAccount())
  const items = NAV_ITEMS.filter((item) => admin || !item.adminOnly)

  return (
    <aside id={id} className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''} ${className}`}>
      <div className={styles.brand}>
        <div className={styles.logo}>A</div>
        {!collapsed && <span className={styles.brandName}>AegisAI</span>}
        {onCloseDrawer && (
          <button
            type="button"
            className={styles.close}
            onClick={onCloseDrawer}
            aria-label="Close navigation"
          >
            <Icon name="close" size={18} />
          </button>
        )}
      </div>

      <nav className={styles.nav} aria-label="Main">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ''}`}
            title={collapsed ? item.label : undefined}
            onClick={onNavigate}
          >
            <Icon name={item.icon} />
            {!collapsed && <span>{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      <button
        type="button"
        className={styles.toggle}
        onClick={onToggle}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <Icon name={collapsed ? 'chevron-right' : 'chevron-left'} size={16} />
      </button>
    </aside>
  )
}
