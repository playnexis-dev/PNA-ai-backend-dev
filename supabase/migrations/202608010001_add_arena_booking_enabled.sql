alter table public.arenas
    add column if not exists booking_enabled boolean not null default true;

update public.arenas
set booking_enabled = true
where booking_enabled is null;

create index if not exists idx_arenas_booking_enabled
    on public.arenas(booking_enabled);
