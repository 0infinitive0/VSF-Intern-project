-- Storage bucket for B3's "Hình ảnh" tab (phase-09-hotel-edit.md, L38)
-- admin-uploaded hotel photos. Public read (hotel images are already
-- publicly viewable content -- the existing `images`/`image_url` columns
-- hold public OTA CDN URLs) so the chat app and this admin screen can both
-- render them with a plain <img src>, no signed URL round-trip needed.
--
-- Writes are NOT gated by a Storage RLS policy here: the only writer is
-- `POST /api/v1/admin/hotels/{id}/images/upload`
-- (backend/src/api/admin/hotels.py), which is require_admin-gated and uses
-- the service_role key -- service_role bypasses Storage RLS the same way it
-- bypasses table RLS everywhere else in this schema, so no anon/authenticated
-- policy is needed (and none is granted) for INSERT/UPDATE/DELETE.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('hotel-images', 'hotel-images', true, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;
