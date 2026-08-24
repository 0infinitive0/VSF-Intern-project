import { PageHeader } from '../layout/page-header'

/** Placeholder for a route this phase only reserves -- the real screen
 * lands in the phase noted below. Not a dead-end button (plan's "Ranh giới
 * không được vượt"): the route genuinely resolves here, and says so
 * honestly, rather than looking broken or silently doing nothing. */
export function RouteStub({ title, phase }: { title: string; phase: number }) {
  return (
    <>
      <PageHeader breadcrumb="Quản trị" title={title} />
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--t3)', fontSize: 13.5 }}>
        Màn này sẽ được xây ở Phase {phase}.
      </div>
    </>
  )
}
