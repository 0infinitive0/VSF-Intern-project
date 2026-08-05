// Conversation-history data access — the sidebar's trip list and each
// trip's scripted chat transcript. Synchronous today, same rationale as
// hotel.service.js.
//
// Root Logic still owns *mutating* this.convos in place (new trip, delete
// trip) — that's local-list editing, not a data fetch, and stays exactly
// as it is today. This service only supplies the initial read.
window.VOTA = window.VOTA || {};
window.VOTA.Services = window.VOTA.Services || {};

window.VOTA.Services.history = {
  // Future: GET /api/conversations.
  getConversations() {
    return window.VOTA.MockData.convos;
  },

  // Root keeps the whole id->messages map and looks up by id at
  // interaction time (switching conversations), so this mirrors that
  // shape rather than taking an id itself. Future: a real backend would
  // more naturally expose GET /api/conversations/{id}/messages per
  // conversation instead of one bulk map — worth revisiting once history
  // is lazy-loaded instead of loaded whole at boot (see BACKEND_INTEGRATION.md).
  getConversationMessages() {
    return window.VOTA.MockData.convoChat;
  },
};
