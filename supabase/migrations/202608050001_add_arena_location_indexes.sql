create index if not exists arenas_active_city_normalized_idx
    on public.arenas ((lower(btrim(city))))
    where is_active = true and status = 'active';

create index if not exists arenas_active_coordinates_idx
    on public.arenas (latitude, longitude)
    where is_active = true
      and status = 'active'
      and latitude is not null
      and longitude is not null;
