create table if not exists public.turfs (
    id uuid primary key default gen_random_uuid(),
    arena_id uuid not null references public.arenas(id) on delete cascade,
    owner_id uuid not null references public.owners(id) on delete cascade,
    name text not null,
    sport text not null,
    price_per_slot numeric(12, 2) not null default 0,
    size text not null default 'Standard',
    flooring text not null default 'Standard',
    capacity integer not null default 1,
    status text not null default 'active' check (status in ('active', 'inactive')),
    is_active boolean not null default true,
    media jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint turfs_capacity_check check (capacity > 0)
);

alter table public.turfs
    add column if not exists arena_id uuid references public.arenas(id) on delete cascade;
alter table public.turfs
    add column if not exists owner_id uuid references public.owners(id) on delete cascade;
alter table public.turfs
    add column if not exists name text;
alter table public.turfs
    add column if not exists sport text;
alter table public.turfs
    add column if not exists price_per_slot numeric(12, 2) not null default 0;
alter table public.turfs
    add column if not exists size text not null default 'Standard';
alter table public.turfs
    add column if not exists flooring text not null default 'Standard';
alter table public.turfs
    add column if not exists capacity integer not null default 1;
alter table public.turfs
    add column if not exists status text not null default 'active';
alter table public.turfs
    add column if not exists is_active boolean not null default true;
alter table public.turfs
    add column if not exists media jsonb not null default '[]'::jsonb;
alter table public.turfs
    add column if not exists metadata jsonb not null default '{}'::jsonb;
alter table public.turfs
    add column if not exists created_at timestamptz not null default now();
alter table public.turfs
    add column if not exists updated_at timestamptz not null default now();

alter table public.arena_slots
    add column if not exists turf_id uuid references public.turfs(id) on delete set null;

alter table public.bookings
    add column if not exists turf_id uuid references public.turfs(id) on delete set null;

update public.arena_slots slot
set turf_id = (
    select id
    from public.turfs
    where turfs.arena_id = slot.arena_id
    order by created_at
    limit 1
)
where slot.turf_id is null;

update public.bookings booking
set turf_id = slot.turf_id
from public.arena_slots slot
where booking.slot_id = slot.id
  and booking.turf_id is null
  and slot.turf_id is not null;

drop index if exists public.arena_slots_unique_time_idx;
create unique index if not exists arena_slots_unique_turf_time_idx
    on public.arena_slots (
        arena_id,
        coalesce(turf_id, '00000000-0000-0000-0000-000000000000'::uuid),
        slot_date,
        start_time,
        end_time
    );

create table if not exists public.arena_maintenance_windows (
    id uuid primary key default gen_random_uuid(),
    arena_id uuid not null references public.arenas(id) on delete cascade,
    owner_id uuid not null references public.owners(id) on delete cascade,
    start_at timestamptz not null,
    end_at timestamptz not null,
    reason text,
    status text not null default 'active' check (status in ('active', 'cancelled')),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint arena_maintenance_time_check check (end_at > start_at)
);

alter table public.arena_maintenance_windows
    add column if not exists metadata jsonb not null default '{}'::jsonb;
alter table public.arena_maintenance_windows
    add column if not exists updated_at timestamptz not null default now();

drop trigger if exists set_turfs_updated_at on public.turfs;
create trigger set_turfs_updated_at
    before update on public.turfs
    for each row
    execute function public.set_updated_at();

drop trigger if exists set_arena_maintenance_windows_updated_at on public.arena_maintenance_windows;
create trigger set_arena_maintenance_windows_updated_at
    before update on public.arena_maintenance_windows
    for each row
    execute function public.set_updated_at();

alter table public.turfs enable row level security;
alter table public.arena_maintenance_windows enable row level security;

drop policy if exists "Public can read active turfs" on public.turfs;
create policy "Public can read active turfs"
    on public.turfs
    for select
    using (
        is_active = true
        and status = 'active'
        and exists (
            select 1
            from public.arenas
            where arenas.id = turfs.arena_id
              and arenas.is_active = true
              and arenas.status = 'active'
        )
    );

drop policy if exists "Owners manage own turfs" on public.turfs;
create policy "Owners manage own turfs"
    on public.turfs
    for all
    using (exists (
        select 1
        from public.owners
        where owners.id = turfs.owner_id
          and owners.user_id = auth.uid()
    ))
    with check (exists (
        select 1
        from public.owners
        where owners.id = turfs.owner_id
          and owners.user_id = auth.uid()
    ));

drop policy if exists "Owners manage own arena maintenance" on public.arena_maintenance_windows;
create policy "Owners manage own arena maintenance"
    on public.arena_maintenance_windows
    for all
    using (exists (
        select 1
        from public.owners
        where owners.id = arena_maintenance_windows.owner_id
          and owners.user_id = auth.uid()
    ))
    with check (exists (
        select 1
        from public.owners
        where owners.id = arena_maintenance_windows.owner_id
          and owners.user_id = auth.uid()
    ));
