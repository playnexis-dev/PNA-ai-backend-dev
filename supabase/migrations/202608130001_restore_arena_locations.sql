-- Arena is the location owner. Preserve existing data by backfilling each
-- unlocated arena from its earliest located turf before clients stop writing
-- turf-level coordinates.
with located_turfs as (
    select distinct on (arena_id)
        arena_id,
        address,
        city,
        state,
        country,
        latitude,
        longitude
    from public.turfs
    where latitude is not null
      and longitude is not null
    order by arena_id, created_at, id
)
update public.arenas as arena
set latitude = located_turf.latitude,
    longitude = located_turf.longitude,
    address = coalesce(nullif(arena.address, ''), located_turf.address),
    city = coalesce(nullif(arena.city, ''), located_turf.city),
    state = coalesce(arena.state, located_turf.state),
    country = coalesce(nullif(arena.country, ''), located_turf.country)
from located_turfs as located_turf
where arena.id = located_turf.arena_id
  and (arena.latitude is null or arena.longitude is null);

create index if not exists idx_arenas_active_location
    on public.arenas (latitude, longitude)
    where is_active = true
      and latitude is not null
      and longitude is not null;
