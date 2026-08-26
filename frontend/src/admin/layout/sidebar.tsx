import { useAuth } from '../../auth/auth-context'
import { matchesBase } from '../router'

/**
 * sidebar.tsx — ports Sidebar.dc.html's nav data + active-state logic
 * verbatim (same 4 groups, same order, same badge). Design source is a
 * static `active` string prop; this version derives the same thing from
 * the current route so the highlight tracks real navigation.
 */
interface NavItem {
  label: string
  path: string
  badge?: string
}

interface NavGroup {
  label: string | null
  items: NavItem[]
}

const NAV: NavGroup[] = [
  { label: null, items: [{ label: 'Tổng quan', path: '/admin' }] },
  {
    label: 'KHÁCH SẠN',
    items: [
      { label: 'Danh sách khách sạn', path: '/admin/hotels' },
      { label: 'Trạng thái embedding', path: '/admin/embedding' },
      { label: 'Danh mục tiện ích', path: '/admin/amenities-catalog' },
    ],
  },
  { label: 'ĐƠN HÀNG', items: [{ label: 'Danh sách đơn hàng', path: '/admin/orders' }] },
]

interface SidebarProps {
  path: string
  navigate: (to: string) => void
  pendingOrderCount?: number
  pendingAmenityCount?: number
}

const BADGE_COUNT_BY_PATH: Record<string, keyof SidebarProps> = {
  '/admin/orders': 'pendingOrderCount',
  '/admin/amenities-catalog': 'pendingAmenityCount',
}

export function Sidebar({ path, navigate, pendingOrderCount, pendingAmenityCount }: SidebarProps) {
  const badgeCounts: Partial<Record<string, number>> = { pendingOrderCount, pendingAmenityCount }
  const { user, signOut } = useAuth()

  // Longest matching path wins so a nested route (e.g. /admin/hotels) doesn't
  // also light up its ancestor (/admin) via matchesBase's prefix check.
  const activePath = NAV.flatMap((g) => g.items)
    .map((item) => item.path)
    .filter((p) => matchesBase(path, p))
    .sort((a, b) => b.length - a.length)[0]

  return (
    <div
      style={{
        width: 240,
        height: '100%',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--g2)',
        backdropFilter: 'blur(22px)',
        borderRight: '1px solid var(--stroke)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '18px 16px 14px' }}>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 9,
            background: 'var(--btn)',
            color: 'var(--btn-fg)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: '.02em',
          }}
        >
          VSF
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.1 }}>Trip Planner</div>
          <div style={{ fontSize: 11, color: 'var(--t4)', lineHeight: 1.1 }}>Bảng quản trị</div>
        </div>
      </div>

      <nav style={{ flex: 1, minHeight: 0, padding: '4px 12px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {NAV.map((group, gi) => (
          <div key={gi} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {group.label && (
              <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: '.09em', color: 'var(--t4)', padding: '8px 10px 4px' }}>
                {group.label}
              </div>
            )}
            {group.items.map((item) => {
              const active = item.path === activePath
              const badgeKey = BADGE_COUNT_BY_PATH[item.path]
              const badge = badgeKey ? badgeCounts[badgeKey] : undefined
              return (
                <button
                  key={item.path}
                  type="button"
                  onClick={() => navigate(item.path)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    height: 34,
                    padding: '0 10px',
                    borderRadius: 10,
                    fontSize: 13,
                    cursor: 'pointer',
                    border: 'none',
                    textAlign: 'left',
                    background: active ? 'var(--acc-soft)' : 'transparent',
                    color: active ? 'var(--acc)' : 'var(--t2)',
                    fontWeight: active ? 600 : 500,
                    boxShadow: active ? 'inset 2px 0 0 var(--acc)' : 'none',
                  }}
                >
                  <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.label}
                  </span>
                  {badge !== undefined && badge > 0 && (
                    <span
                      className="tabular-nums"
                      style={{
                        minWidth: 18,
                        height: 18,
                        padding: '0 5px',
                        borderRadius: 999,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 10.5,
                        fontWeight: 700,
                        background: 'var(--warn-soft)',
                        color: 'var(--warn-ink)',
                      }}
                    >
                      {badge}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </nav>

      <div style={{ borderTop: '1px solid var(--line)', padding: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 999,
            background: 'var(--acc-soft)',
            color: 'var(--acc)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 12,
            fontWeight: 700,
            flex: 'none',
          }}
        >
          VH
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.2 }}>Vận hành</div>
          <div
            style={{
              fontSize: 11,
              color: 'var(--t4)',
              lineHeight: 1.2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {user?.email}
          </div>
        </div>
        <button
          type="button"
          title="Đăng xuất"
          onClick={() => signOut()}
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            border: '1px solid var(--stroke)',
            background: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--t3)',
            fontSize: 13,
            cursor: 'pointer',
          }}
        >
          ⏻
        </button>
      </div>
    </div>
  )
}
