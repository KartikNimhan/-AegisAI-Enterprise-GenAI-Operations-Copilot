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
  { to: '/conversations', label: 'Conversations', icon: 'history' },
  { to: '/documents', label: 'Documents', icon: 'documents' },
  { to: '/memory', label: 'Memory', icon: 'memory' },
  { to: '/operations', label: 'Operations', icon: 'operations' },
  { to: '/system', label: 'System Status', icon: 'status', adminOnly: true },
]

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const admin = isAdmin(useAccount())
  const items = NAV_ITEMS.filter((item) => admin || !item.adminOnly)

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      <div className={styles.brand}>
        <div className={styles.logo}>A</div>
        {!collapsed && <span className={styles.brandName}>AegisAI</span>}
      </div>

      <nav className={styles.nav}>
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ''}`}
            title={collapsed ? item.label : undefined}
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
