import { useState } from 'react'
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import styles from './AppShell.module.css'

export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className={styles.shell}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div className={styles.main}>
        <Topbar title={title} />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  )
}
