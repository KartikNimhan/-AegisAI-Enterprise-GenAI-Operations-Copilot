import { NavLink } from 'react-router-dom'
import { Icon, type IconName } from '../Icon'
import styles from './Sidebar.module.css'

interface NavItem {
  to: string
  label: string
  icon: IconName
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Copilot', icon: 'chat' },
  { to: '/documents', label: 'Documents', icon: 'documents' },
  { to: '/operations', label: 'Operations', icon: 'operations' },
  { to: '/system', label: 'System Status', icon: 'status' },
]

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      <div className={styles.brand}>
        <div className={styles.logo}>A</div>
        {!collapsed && <span className={styles.brandName}>AegisAI</span>}
      </div>

      <nav className={styles.nav}>
        {NAV_ITEMS.map((item) => (
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
