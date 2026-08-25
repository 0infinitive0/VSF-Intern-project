import { useEffect, useRef, useState } from 'react'
import { getOrderDetail, type OrderDetailResponse } from '../../api/orders-client'
import { PageHeader } from '../../layout/page-header'
import { cancellableRoomCount, confirmableRoomCount } from '../../lib/order-room-counts'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { ErrorState } from '../../ui/error-state'
import { CancelOrderDialog } from './cancel-order-dialog'
import { ConfirmOrderDialog } from './confirm-order-dialog'
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
type ResultBanner = { tone: 'ok' | 'err'; message: string }
type OpenDialog = 'confirm' | 'cancel' | null

/** order-detail-page.tsx — D2 orchestrator (phase-05-order-detail.md),
 * wired to D3's two header actions (phase-06-order-actions.md). Each button
 * only renders when the order actually has a room the action would touch --
 * an already fully-CONFIRMED order has nothing left to confirm, an already
 * fully-CANCELLED/EXPIRED one has nothing left to cancel. */
export function OrderDetailPage({ paymentId }: OrderDetailPageProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [order, setOrder] = useState<OrderDetailResponse | null>(null)
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null)
  const [resultBanner, setResultBanner] = useState<ResultBanner | null>(null)
  // Guards against a stale response winning a race: `load()` is called both
  // by the paymentId effect and directly from handleDialogDone (a reload
  // after confirm/cancel) -- if paymentId changes while that second call is
  // still in flight, its response must not overwrite the new order's data.
  const loadTokenRef = useRef(0)

  function load() {
    const token = ++loadTokenRef.current
    setLoadState({ status: 'loading' })
    getOrderDetail(paymentId).then((result) => {
      if (loadTokenRef.current !== token) return
      if (!result.ok) return setLoadState({ status: 'error', detail: result.detail })
      setOrder(result.data)
      setLoadState({ status: 'ok' })
    })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paymentId])

  function handleDialogDone(message: string, tone: 'ok' | 'err') {
    setOpenDialog(null)
    setResultBanner({ tone, message })
    load()
  }

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

  const canConfirm = confirmableRoomCount(order) > 0
  const canCancel = cancellableRoomCount(order) > 0

  return (
    <>
      <PageHeader
        breadcrumb={`Quản trị · Đơn hàng · ${order.order_code}`}
        title={`Đơn ${order.order_code}`}
        action={
          <>
            <BookingStatusChip status={order.booking_status} />
            <PaymentStatusChip status={order.payment_status} />
            {canCancel && (
              <Button variant="ghost" size="sm" style={{ border: '1px solid var(--err)', color: 'var(--err)' }} onClick={() => setOpenDialog('cancel')}>
                Huỷ đơn
              </Button>
            )}
            {canConfirm && (
              <Button variant="primary" size="sm" onClick={() => setOpenDialog('confirm')}>
                Xác nhận đơn
              </Button>
            )}
          </>
        }
      />

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 22 }}>
        {resultBanner && (
          <div style={{ marginBottom: 18 }}>
            <Banner tone={resultBanner.tone}>{resultBanner.message}</Banner>
          </div>
        )}

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

      <ConfirmOrderDialog open={openDialog === 'confirm'} order={order} onClose={() => setOpenDialog(null)} onDone={handleDialogDone} />
      <CancelOrderDialog open={openDialog === 'cancel'} order={order} onClose={() => setOpenDialog(null)} onDone={handleDialogDone} />
    </>
  )
}
