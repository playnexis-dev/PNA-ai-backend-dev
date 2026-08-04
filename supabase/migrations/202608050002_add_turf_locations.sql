alter table public.turfs
    add column if not exists address text;
alter table public.turfs
    add column if not exists city text;
alter table public.turfs
    add column if not exists state text;
alter table public.turfs
    add column if not exists country text not null default 'India';
alter table public.turfs
    add column if not exists latitude numeric;
alter table public.turfs
    add column if not exists longitude numeric;

update public.turfs turf
set address = coalesce(turf.address, arena.address),
    city = coalesce(turf.city, arena.city),
    state = coalesce(turf.state, arena.state),
    country = coalesce(turf.country, arena.country, 'India'),
    latitude = coalesce(turf.latitude, arena.latitude),
    longitude = coalesce(turf.longitude, arena.longitude)
from public.arenas arena
where arena.id = turf.arena_id
  and (
      turf.address is null
      or turf.city is null
      or turf.latitude is null
      or turf.longitude is null
  );

create index if not exists turfs_active_city_normalized_idx
    on public.turfs ((lower(btrim(city))))
    where is_active = true and status = 'active';

create index if not exists turfs_active_coordinates_idx
    on public.turfs (latitude, longitude)
    where is_active = true
      and status = 'active'
      and latitude is not null
      and longitude is not null;
