/**
 * test-setup.ts — vitest-only environment shims. Not bundled into the app
 * (vitest's setupFiles run only under the test runner).
 *
 * @supabase/supabase-js's createClient() unconditionally constructs an
 * internal RealtimeClient, which probes for a global WebSocket constructor
 * at construction time even though this app never opens a realtime channel
 * (see src/lib/supabase-client.ts — only .auth.* is used). Real browsers
 * always have one; this project's pinned Node (20.18, see package.json
 * engine warnings) does not, so importing anything that transitively
 * imports supabase-client.ts under vitest's Node environment throws before
 * a single test runs. `ws` supplies a spec-compatible constructor for the
 * test environment only.
 */
import { WebSocket } from 'ws'

if (typeof globalThis.WebSocket === 'undefined') {
  // ws's WebSocket is not 100% type-identical to lib.dom's, but is what
  // supabase-js's RealtimeClient constructor needs at this call site.
  globalThis.WebSocket = WebSocket as unknown as typeof globalThis.WebSocket
}
