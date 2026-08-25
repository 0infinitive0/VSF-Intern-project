import { useEffect, useState } from 'react'
import { getOrderDetail, type OrderDetailResponse } from '../../api/orders-client'
import { PageHeader } from '../../layout/page-header'
import { ErrorState } from '../../ui/error-state'
import { OrderChatLink } from './order-chat-link'
import { OrderGuestCard } from './order-guest-card'
import { OrderRoomsCard } from './order-rooms-card'
import { OrderTimeline } from './order-timeline'
import { BookingStatusChip, PaymentStatusChip } from './order-status-chip'
import { OrderVnpayCard } from './order-vnpay-card'

interface OrderDetailPageProps {
  paymentId: string
}

type LoadState = { status: 'loading' } | { status: 'error'; detail: string } | { status: 'ok' }

/** order-detail-page.tsx — D2 orchestrator (phase-05-order-detail.md).
 * Read-only: the plan's two header actions ("Xác nhận đơn"/"Huỷ đơn") open
 * Phase 6's dialog, which doesn't exist yet -- rather than a disabled
 * button with a "Sắp có" tooltip (the plan calls that unacceptable), they
 * simply aren't rendered until Phase 6 ships them. */
export function OrderDetailPage({ paymentId }: OrderDetailPageProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [order, setOrder] = useState<OrderDetailResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadState({ status: 'loading' })
    getOrderDetail(paymentId).then((result) => {
      if (cancelled) return
      if (!result.ok) return setLoadState({ status: 'error', detail: result.detail })
      setOrder(result.data)
      setLoadState({ status: 'ok' })
    })
    return () => {
      cancelled = true
    }
  }, [paymentId])

  if (loadState.status === 'loading') {
    return <div style={{ flex: 1, padding: 28 }} />
  }

  if (loadState.status === 'error' || !order) {
    return (
      <>
        <PageHeader breadcrumb="Quản trị · Đơn hàng" title="Đơn hàng" />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <ErrorState description={loadState.status === 'error' ? loadState.detail : 'Không tải được đơn hàng.'} />
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        breadcrumb={`Quản trị · Đơn hàng · ${order.order_code}`}
        title={`Đơn ${order.order_code}`}
        action={
          <>
            <BookingStatusChip status={order.booking_status} />
            <PaymentStatusChip status={order.payment_status} />
          </>
        }
      />

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 22 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, alignItems: 'start' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <OrderGuestCard guest={order.guest} />
            <OrderRoomsCard order={order} />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="card" style={{ padding: 18 }}>
              <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 14 }}>Dòng thời gian</div>
              <OrderTimeline events={order.timeline} />
            </div>
            <OrderVnpayCard order={order} />
            <OrderChatLink chatSession={order.chat_session} />
          </div>
        </div>
      </div>
    </>
  )
}
