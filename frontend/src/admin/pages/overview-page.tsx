import { useState } from 'react'
import { PageHeader } from '../layout/page-header'
import { Banner } from '../ui/banner'
import { Button } from '../ui/button'
import { EmptyState } from '../ui/empty-state'
import { ErrorState } from '../ui/error-state'
import { SkeletonTable } from '../ui/skeleton-table'
import { StatusChip } from '../ui/status-chip'

type DemoState = 'skeleton' | 'empty' | 'error'

/**
 * Tổng quan (A3) route stub. Phase 17 owns the real KPI content -- until
 * then this route demonstrates the shared skeleton/empty/error states
 * (plan's Success Criteria: "Ba trạng thái ... render được trên một trang
 * mẫu") on the one nav item every admin actually lands on first.
 */
export function OverviewPage() {
  const [demoState, setDemoState] = useState<DemoState>('skeleton')

  return (
    <>
      <PageHeader breadcrumb="Quản trị · Tổng quan" title="Tổng quan vận hành" />
      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <Banner tone="warn">
          Màn KPI thật sẽ được xây ở Phase 17. Bên dưới là bộ trạng thái dùng chung
          (skeleton · rỗng · lỗi) mà mọi màn danh sách sau này đều dùng lại.
        </Banner>

        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            size="sm"
            variant={demoState === 'skeleton' ? 'primary' : 'secondary'}
            onClick={() => setDemoState('skeleton')}
          >
            Đang tải
          </Button>
          <Button
            size="sm"
            variant={demoState === 'empty' ? 'primary' : 'secondary'}
            onClick={() => setDemoState('empty')}
          >
            Rỗng
          </Button>
          <Button
            size="sm"
            variant={demoState === 'error' ? 'primary' : 'secondary'}
            onClick={() => setDemoState('error')}
          >
            Lỗi tải
          </Button>
        </div>

        {demoState === 'skeleton' && <SkeletonTable rows={5} />}
        {demoState === 'empty' && (
          <div className="card">
            <EmptyState action={<Button variant="secondary" size="sm">Xoá bộ lọc</Button>} />
          </div>
        )}
        {demoState === 'error' && (
          <div className="card">
            <ErrorState
              description="Máy chủ trả về lỗi 503 khi truy vấn danh sách đơn. Dữ liệu hiển thị có thể đã cũ."
              requestId="7f2c-91ab"
              onRetry={() => setDemoState('skeleton')}
            />
          </div>
        )}

        <div style={{ display: 'flex', gap: 8 }}>
          <StatusChip status="PENDING" label="Chờ xử lý" />
          <StatusChip status="RESERVED" label="Đang giữ" />
          <StatusChip status="CONFIRMED" label="Đã xác nhận" />
          <StatusChip status="CANCELLED" label="Đã huỷ" />
        </div>
      </div>
    </>
  )
}
