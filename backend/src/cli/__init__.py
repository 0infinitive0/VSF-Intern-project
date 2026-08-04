"""Terminal Chat CLI package — terminal I/O only.

No planning function or agent-visible `@tool` lives here anymore; those moved
to `src.services` and `src.agents` in this phase. Nothing re-exported at
package-init time to avoid import-order surprises.
"""
