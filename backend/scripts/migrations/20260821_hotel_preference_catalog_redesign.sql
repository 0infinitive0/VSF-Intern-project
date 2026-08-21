begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

alter table public.amenity_catalog
  add column if not exists parent_id text,
  add column if not exists needs_review boolean not null default false,
  add column if not exists retired_at timestamptz;

alter table public.amenity_catalog
  drop constraint if exists amenity_catalog_parent_id_fkey,
  add constraint amenity_catalog_parent_id_fkey
    foreign key (parent_id) references public.amenity_catalog(id)
    on update cascade on delete restrict,
  drop constraint if exists amenity_catalog_not_self_parent,
  add constraint amenity_catalog_not_self_parent
    check (parent_id is null or parent_id <> id);

create index if not exists amenity_catalog_parent_id_idx
  on public.amenity_catalog(parent_id)
  where parent_id is not null;

-- Reviewed exact-synonym map. Related facilities with the same Vietnamese
-- label are deliberately relabelled below instead of being merged.
create temporary table amenity_merge_map (
  removed_id text primary key,
  canonical_id text not null
) on commit drop;

insert into amenity_merge_map (removed_id, canonical_id) values
  ('medical_clinic', 'in_house_clinic'),
  ('private_apartment', 'private_apartment_in_the_building'),
  ('sanitation_certification', 'hygiene_certification'),
  ('on_site_grocery_store', 'on_site_convenience_store'),
  ('boating', 'boat_trip'),
  ('beauty_services', 'beauty_service'),
  ('makeup_services', 'makeup_service'),
  ('cctv_in_public_areas', 'cctv_in_common_areas'),
  ('cctv_system_in_common_area', 'cctv_in_common_areas'),
  ('indoor_cctv_system', 'cctv_in_common_areas'),
  ('visual_impairment_support_braille', 'support_for_visually_impaired_braille'),
  ('sunbathing_room', 'sun_bathing_room'),
  ('caf_styled_room', 'caf_style_room'),
  ('cafe_style_room_design', 'caf_style_room'),
  ('full_body_scrub', 'body_scrub'),
  ('korean_language', 'korean'),
  ('vietnamese_language', 'vietnamese'),
  ('lockers', 'locker'),
  ('wi_fi_in_public_areas', 'public_wi_fi'),
  ('wheelchair_accessible', 'wheelchair_accessible_throughout_property'),
  ('parking_outside_the_property', 'parking_outside_the_premises')
on conflict (removed_id) do update set canonical_id = excluded.canonical_id;

do $$
begin
  if exists (
    select 1 from amenity_merge_map map
    left join public.amenity_catalog canonical on canonical.id = map.canonical_id
    where canonical.id is null
  ) then
    raise exception 'amenity merge map references a missing canonical ID';
  end if;
end
$$;

-- Preserve aliases from every removed row before remapping references.
update public.amenity_catalog canonical
set match_keywords = merged.keywords
from (
  select m.canonical_id,
         array_agg(distinct keyword order by keyword) as keywords
  from amenity_merge_map m
  join public.amenity_catalog source on source.id in (m.removed_id, m.canonical_id)
  cross join lateral unnest(
    source.match_keywords || array[source.id, source.label_vi, source.label_en]
  ) keyword
  where btrim(keyword) <> ''
  group by m.canonical_id
) merged
where canonical.id = merged.canonical_id;

update public.hotels hotel
set amenities = (
  select array_agg(item.id order by item.first_position) as ids
  from (
    select coalesce(map.canonical_id, value.id) as id,
           min(value.position) as first_position
    from unnest(coalesce(hotel.amenities, '{}'::text[])) with ordinality value(id, position)
    left join amenity_merge_map map on map.removed_id = value.id
    group by coalesce(map.canonical_id, value.id)
  ) item
where hotel.amenities && (select array_agg(removed_id) from amenity_merge_map);

update public.rooms room
set room_facilities = (
  select array_agg(item.id order by item.first_position) as ids
  from (
    select coalesce(map.canonical_id, value.id) as id,
           min(value.position) as first_position
    from unnest(coalesce(room.room_facilities, '{}'::text[])) with ordinality value(id, position)
    left join amenity_merge_map map on map.removed_id = value.id
    group by coalesce(map.canonical_id, value.id)
  ) item
where room.room_facilities && (select array_agg(removed_id) from amenity_merge_map);

delete from public.amenity_catalog catalog
using amenity_merge_map map
where catalog.id = map.removed_id;

-- Same translated label, different facility: keep both and make the
-- distinction visible instead of forcing a lossy merge.
update public.amenity_catalog set label_vi = 'Phòng cầu nguyện' where id = 'prayer_room';
update public.amenity_catalog set label_vi = 'Phòng đơn' where id = 'single_room';
update public.amenity_catalog set label_vi = 'Phòng tắm' where id = 'bathroom';
update public.amenity_catalog set label_vi = 'Hạt tiêu' where id = 'pepper';
update public.amenity_catalog set label_vi = 'Khu vực tắm nắng' where id = 'sunbathing_area';
update public.amenity_catalog set label_vi = 'Sân hiên / patio' where id = 'terrace_patio';
update public.amenity_catalog set label_vi = 'Xe đẩy hành lý' where id = 'luggage_cart';
update public.amenity_catalog set label_vi = 'Xe đẩy trẻ em' where id = 'stroller';

-- Reviewed high-traffic one-way hierarchy: a specific child satisfies its
-- general parent, never its siblings or the other way around.
update public.amenity_catalog
set parent_id = 'parking'
where id in (
  'free_parking', 'on_site_parking', 'paid_parking', 'nearby_parking',
  'valet_parking', 'parking_outside_the_premises', 'bicycle_parking'
);

update public.amenity_catalog
set parent_id = 'wifi'
where id in (
  'free_wi_fi', 'free_wi_fi_in_all_rooms', 'public_wi_fi',
  'wireless_internet_access'
);

update public.amenity_catalog
set parent_id = 'swimming_pool'
where id in ('private_pool', 'pool_with_a_view');

-- Scraper artifacts and genuine long-tail rows both require review; the
-- flag quarantines them from automatic promotion without deleting history.
with hotel_counts as (
  select amenity_id, count(distinct hotel_id) as n
  from (
    select id as hotel_id, unnest(coalesce(amenities, '{}'::text[])) as amenity_id
    from public.hotels
  ) value
  group by amenity_id
)
update public.amenity_catalog catalog
set needs_review = true
where catalog.is_approved
  and catalog.scope in ('hotel', 'both')
  and coalesce((select n from hotel_counts where amenity_id = catalog.id), 0) = 0;

create unique index if not exists amenity_catalog_approved_label_scope_uidx
  on public.amenity_catalog (scope, lower(btrim(label_vi)))
  where is_approved and retired_at is null;

-- Fail closed if any removed ID survived or integrity still has duplicates.
do $$
begin
  if exists (
    select 1 from public.hotels h, unnest(coalesce(h.amenities, '{}'::text[])) value(id)
    join amenity_merge_map m on m.removed_id = value.id
  ) or exists (
    select 1 from public.rooms r, unnest(coalesce(r.room_facilities, '{}'::text[])) value(id)
    join amenity_merge_map m on m.removed_id = value.id
  ) then
    raise exception 'amenity merge left removed IDs in hotel or room arrays';
  end if;

  if exists (
    select 1
    from public.amenity_catalog
    where is_approved and retired_at is null
    group by scope, lower(btrim(label_vi))
    having count(*) > 1
  ) then
    raise exception 'approved amenity labels remain duplicated within a scope';
  end if;
end
$$;

commit;

-- Rollback notes: drop the unique/parent indexes, constraints, and additive
-- columns only after restoring merged catalog rows and their array references
-- from a pre-migration backup. The data merge is intentionally not guessed in
-- an automated down migration.
