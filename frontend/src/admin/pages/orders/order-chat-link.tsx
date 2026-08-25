import { DateText } from '../../ui/date-text'
import type { OrderDetailResponse } from '../../api/orders-client'

/** order-chat-link.tsx — D2's "Xem cuộc trò chuyện gốc" block
 * (phase-05-order-detail.md). The chat app's own entry (App.tsx /
 * use-chat-session.ts) never reads a `?session=` query param -- it restores
 * sessions from local state, not the URL -- so a `/?session=<id>` link
 * would silently land on a fresh session instead of the right one. Per the
 * plan ("không làm link chết"), the session id is shown as plain text for
 * manual lookup instead of a broken link. */
export function OrderChatLink({ chatSession }: { chatSession: OrderDetailResponse['chat_session'] }) {
  if (!chatSession) return null

  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ fontSize: 13.5, fontWeight: 700 }}>Xem cuộc trò chuyện gốc</div>
      <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 6 }}>
        Phiên chat #{chatSession.session_id}
        {chatSession.started_at && (
          <>
            {' · '}
            <DateText value={chatSession.started_at} withTime />
          </>
        )}
        {' · '}
        {chatSession.message_count} tin nhắn
      </div>
    </div>
  )
}
