---
name: supabase-direct-db-ipv6
description: Supabase's direct Postgres host db.<ref>.supabase.co is IPv6-only, so any DSN built for it fails from this project's IPv4-only dev machine, Docker bridge network, and EC2 host
metadata:
  type: project
---

Any Postgres DSN pointing at `db.<project_ref>.supabase.co:5432` will fail to
connect from this project's environments. Verified 2026-08-13: that host has an
AAAA record only (`2406:da12:...`), no A record; `getaddrinfo(..., AF_INET)`
fails on the dev machine, Docker's default bridge network is IPv4-only, and the
EC2 host (see [[ec2-deployment]]) is IPv4.

**Why:** Supabase deprecated IPv4 for direct connections in Jan 2024. IPv4 is
only available through the Supavisor pooler
(`postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres`)
or the paid IPv4 add-on.

**How to apply:** When reviewing anything that opens a direct psycopg/SQLAlchemy
connection to Supabase (LangGraph `PostgresSaver`, migrations, scripts), flag a
`db.<ref>.supabase.co` DSN as non-functional. The pooler host embeds a region
that cannot be derived from `SUPABASE_URL`, so prefer one explicit full-DSN
setting over deriving the host from the project ref.
