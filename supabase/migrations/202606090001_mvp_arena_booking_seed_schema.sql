create extension if not exists pgcrypto;

create or replace function public.normalize_phone(value text)
returns text
language sql
immutable
as $$
    select nullif(regexp_replace(coalesce(value, ''), '\D', '', 'g'), '')
$$;

alter table public.players
    add column if not exists phone_normalized text;

alter table public.owners
    add column if not exists phone_normalized text;

update public.players
set phone_normalized = public.normalize_phone(phone)
where phone_normalized is null and phone is not null;

update public.owners
set phone_normalized = public.normalize_phone(phone)
where phone_normalized is null and phone is not null;

create unique index if not exists players_user_id_unique_idx
    on public.players (user_id);

create unique index if not exists owners_user_id_unique_idx
    on public.owners (user_id);

create unique index if not exists players_phone_normalized_unique_idx
    on public.players (phone_normalized)
    where phone_normalized is not null;

create unique index if not exists owners_phone_normalized_unique_idx
    on public.owners (phone_normalized)
    where phone_normalized is not null;

create table if not exists public.profile_phone_registry (
    normalized_phone text primary key,
    user_id uuid not null unique references auth.users(id) on delete cascade,
    profile_kind text not null check (profile_kind in ('player', 'owner')),
    profile_id uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function public.set_profile_phone_normalized()
returns trigger
language plpgsql
as $$
begin
    new.phone_normalized = public.normalize_phone(new.phone);
    return new;
end;
$$;

create or replace function public.sync_profile_phone_registry()
returns trigger
language plpgsql
as $$
declare
    profile_kind_value text;
    existing_profile record;
begin
    profile_kind_value := case when TG_TABLE_NAME = 'players' then 'player' else 'owner' end;

    if TG_OP = 'DELETE' then
        delete from public.profile_phone_registry
        where profile_kind = profile_kind_value
          and profile_id = old.id;
        return old;
    end if;

    if TG_OP = 'UPDATE' and old.phone_normalized is distinct from new.phone_normalized then
        delete from public.profile_phone_registry
        where profile_kind = profile_kind_value
          and profile_id = old.id;
    end if;

    if new.phone_normalized is null or new.user_id is null then
        return new;
    end if;

    select *
    into existing_profile
    from public.profile_phone_registry
    where normalized_phone = new.phone_normalized
      and not (profile_kind = profile_kind_value and profile_id = new.id);

    if found then
        raise exception 'Phone number is already used by another profile';
    end if;

    insert into public.profile_phone_registry (
        normalized_phone,
        user_id,
        profile_kind,
        profile_id
    )
    values (
        new.phone_normalized,
        new.user_id,
        profile_kind_value,
        new.id
    )
    on conflict (user_id) do update
    set normalized_phone = excluded.normalized_phone,
        profile_kind = excluded.profile_kind,
        profile_id = excluded.profile_id,
        updated_at = now();

    return new;
end;
$$;

drop trigger if exists set_players_phone_normalized on public.players;
create trigger set_players_phone_normalized
    before insert or update of phone on public.players
    for each row
    execute function public.set_profile_phone_normalized();

drop trigger if exists set_owners_phone_normalized on public.owners;
create trigger set_owners_phone_normalized
    before insert or update of phone on public.owners
    for each row
    execute function public.set_profile_phone_normalized();

drop trigger if exists sync_players_phone_registry on public.players;
create trigger sync_players_phone_registry
    after insert or update of phone, user_id or delete on public.players
    for each row
    execute function public.sync_profile_phone_registry();

drop trigger if exists sync_owners_phone_registry on public.owners;
create trigger sync_owners_phone_registry
    after insert or update of phone, user_id or delete on public.owners
    for each row
    execute function public.sync_profile_phone_registry();

insert into public.profile_phone_registry (
    normalized_phone,
    user_id,
    profile_kind,
    profile_id
)
select phone_normalized, user_id, 'player', id
from public.players
where phone_normalized is not null
  and user_id is not null
on conflict (normalized_phone) do nothing;

insert into public.profile_phone_registry (
    normalized_phone,
    user_id,
    profile_kind,
    profile_id
)
select phone_normalized, user_id, 'owner', id
from public.owners
where phone_normalized is not null
  and user_id is not null
on conflict (normalized_phone) do nothing;

create table if not exists public.arenas (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.owners(id) on delete cascade,
    name text not null,
    sport text not null,
    description text,
    address text not null,
    city text not null,
    state text,
    country text not null default 'India',
    latitude numeric,
    longitude numeric,
    base_price numeric(12, 2) not null default 0,
    price_unit text not null default 'slot',
    status text not null default 'active' check (status in ('active', 'inactive')),
    is_active boolean not null default true,
    rating numeric(3, 2) not null default 0,
    review_count integer not null default 0,
    amenities jsonb not null default '[]'::jsonb,
    images jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.arenas
    add column if not exists owner_id uuid references public.owners(id) on delete cascade;

do $$
declare
    constraint_row record;
begin
    for constraint_row in
        select conname, pg_get_constraintdef(oid) as definition
        from pg_constraint
        where conrelid = 'public.arenas'::regclass
          and contype = 'f'
          and conkey = array[
              (
                  select attnum
                  from pg_attribute
                  where attrelid = 'public.arenas'::regclass
                    and attname = 'owner_id'
              )
          ]::smallint[]
    loop
        if constraint_row.definition not ilike '%REFERENCES public.owners%' then
            execute format('alter table public.arenas drop constraint %I', constraint_row.conname);
        end if;
    end loop;

    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.arenas'::regclass
          and conname = 'arenas_owner_id_fkey'
    ) then
        alter table public.arenas
            add constraint arenas_owner_id_fkey
            foreign key (owner_id) references public.owners(id) on delete cascade;
    end if;
end;
$$;

alter table public.arenas
    add column if not exists description text;

alter table public.arenas
    add column if not exists address text;

alter table public.arenas
    add column if not exists city text;

alter table public.arenas
    add column if not exists state text;

alter table public.arenas
    add column if not exists country text not null default 'India';

alter table public.arenas
    add column if not exists latitude numeric;

alter table public.arenas
    add column if not exists longitude numeric;

alter table public.arenas
    add column if not exists sport text;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arenas'
          and column_name = 'sports_supported'
    ) then
        update public.arenas
        set sport = coalesce(sport, sports_supported[1], 'Football')
        where sport is null;
    else
        update public.arenas
        set sport = coalesce(sport, 'Football')
        where sport is null;
    end if;
end;
$$;

alter table public.arenas
    alter column sport set not null;

alter table public.arenas
    add column if not exists base_price numeric(12, 2) not null default 0;

alter table public.arenas
    add column if not exists price_unit text not null default 'slot';

alter table public.arenas
    alter column price_unit set default 'slot';

update public.arenas
set price_unit = 'slot'
where price_unit is null
   or price_unit = 'hour';

alter table public.arenas
    add column if not exists status text not null default 'active';

alter table public.arenas
    add column if not exists is_active boolean not null default true;

alter table public.arenas
    add column if not exists rating numeric(3, 2) not null default 0;

alter table public.arenas
    add column if not exists review_count integer not null default 0;

alter table public.arenas
    add column if not exists amenities jsonb not null default '[]'::jsonb;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arenas'
          and column_name = 'amenities'
          and data_type = 'ARRAY'
    ) then
        alter table public.arenas
            alter column amenities drop default;

        alter table public.arenas
            alter column amenities type jsonb
            using to_jsonb(coalesce(amenities, '{}'::text[]));

        alter table public.arenas
            alter column amenities set default '[]'::jsonb;
    end if;
end;
$$;

alter table public.arenas
    add column if not exists images jsonb not null default '[]'::jsonb;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arenas'
          and column_name = 'images'
          and data_type = 'ARRAY'
    ) then
        alter table public.arenas
            alter column images drop default;

        alter table public.arenas
            alter column images type jsonb
            using to_jsonb(coalesce(images, '{}'::text[]));

        alter table public.arenas
            alter column images set default '[]'::jsonb;
    end if;
end;
$$;

alter table public.arenas
    add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table public.arenas
    add column if not exists created_at timestamptz not null default now();

alter table public.arenas
    add column if not exists updated_at timestamptz not null default now();

alter table public.arenas
    alter column country set default 'India';

alter table public.arenas
    alter column is_active set default true;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'arenas_status_check'
          and conrelid = 'public.arenas'::regclass
    ) then
        alter table public.arenas
            add constraint arenas_status_check check (status in ('active', 'inactive'));
    end if;
end;
$$;

create table if not exists public.arena_slots (
    id uuid primary key default gen_random_uuid(),
    arena_id uuid not null references public.arenas(id) on delete cascade,
    slot_date date not null,
    start_time time not null,
    end_time time not null,
    price numeric(12, 2) not null default 0,
    capacity integer not null default 1,
    booked_count integer not null default 0,
    status text not null default 'active' check (status in ('active', 'blocked', 'booked')),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint arena_slots_capacity_check check (capacity > 0),
    constraint arena_slots_booked_count_check check (booked_count >= 0 and booked_count <= capacity),
    constraint arena_slots_time_check check (end_time > start_time)
);

alter table public.arena_slots
    add column if not exists slot_date date;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arena_slots'
          and column_name = 'day_of_week'
    ) then
        alter table public.arena_slots
            alter column day_of_week drop not null;
    end if;
end;
$$;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arena_slots'
          and column_name = 'day_of_week'
    ) then
        update public.arena_slots
        set slot_date = current_date + coalesce(day_of_week, 0)
        where slot_date is null;
    else
        update public.arena_slots
        set slot_date = current_date
        where slot_date is null;
    end if;
end;
$$;

alter table public.arena_slots
    alter column slot_date set default current_date;

alter table public.arena_slots
    alter column slot_date set not null;

alter table public.arena_slots
    add column if not exists price numeric(12, 2) not null default 0;

alter table public.arena_slots
    add column if not exists capacity integer not null default 1;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arena_slots'
          and column_name = 'max_bookings'
    ) then
        alter table public.arena_slots
            alter column max_bookings set default 1;

        alter table public.arena_slots
            alter column max_bookings drop not null;
    end if;
end;
$$;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arena_slots'
          and column_name = 'max_bookings'
    ) then
        update public.arena_slots
        set capacity = greatest(coalesce(max_bookings, 1), 1)
        where capacity is null or capacity = 1;
    end if;
end;
$$;

alter table public.arena_slots
    add column if not exists booked_count integer not null default 0;

alter table public.arena_slots
    add column if not exists status text not null default 'active';

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'arena_slots'
          and column_name = 'is_active'
    ) then
        update public.arena_slots
        set status = case when is_active then 'active' else 'blocked' end
        where status is null or status = 'active';
    end if;
end;
$$;

alter table public.arena_slots
    add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table public.arena_slots
    add column if not exists updated_at timestamptz not null default now();

create unique index if not exists arena_slots_unique_time_idx
    on public.arena_slots (arena_id, slot_date, start_time, end_time);

create table if not exists public.bookings (
    id uuid primary key default gen_random_uuid(),
    player_id uuid not null references public.players(id) on delete cascade,
    owner_id uuid not null references public.owners(id) on delete cascade,
    arena_id uuid not null references public.arenas(id) on delete cascade,
    slot_id uuid references public.arena_slots(id) on delete set null,
    booking_date date not null,
    start_time time not null,
    end_time time not null,
    sport text not null,
    status text not null default 'pending' check (status in ('pending', 'confirmed', 'rejected', 'completed', 'cancelled')),
    payment_status text not null default 'pending' check (payment_status in ('pending', 'paid', 'failed', 'refunded')),
    total_amount numeric(12, 2) not null default 0,
    notes text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

do $$
declare
    constraint_row record;
begin
    for constraint_row in
        select conname, pg_get_constraintdef(oid) as definition
        from pg_constraint
        where conrelid = 'public.bookings'::regclass
          and contype = 'f'
          and conkey = array[
              (
                  select attnum
                  from pg_attribute
                  where attrelid = 'public.bookings'::regclass
                    and attname = 'player_id'
              )
          ]::smallint[]
    loop
        if constraint_row.definition not ilike '%REFERENCES public.players%'
           and constraint_row.definition not ilike '%REFERENCES players%' then
            execute format('alter table public.bookings drop constraint %I', constraint_row.conname);
        end if;
    end loop;

    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.bookings'::regclass
          and conname = 'bookings_player_id_fkey'
    ) then
        alter table public.bookings
            add constraint bookings_player_id_fkey
            foreign key (player_id) references public.players(id) on delete cascade;
    end if;
end;
$$;

alter table public.bookings
    add column if not exists owner_id uuid references public.owners(id) on delete cascade;

update public.bookings
set owner_id = arenas.owner_id
from public.arenas
where bookings.arena_id = arenas.id
  and bookings.owner_id is null;

alter table public.bookings
    add column if not exists slot_id uuid references public.arena_slots(id) on delete set null;

alter table public.bookings
    add column if not exists booking_date date;

update public.bookings
set booking_date = slot_date
where booking_date is null
  and slot_date is not null;

update public.bookings
set booking_date = current_date
where booking_date is null;

alter table public.bookings
    alter column booking_date set default current_date;

alter table public.bookings
    alter column booking_date set not null;

alter table public.bookings
    add column if not exists payment_status text not null default 'pending';

alter table public.bookings
    add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table public.bookings
    alter column slot_date drop not null;

alter table public.bookings
    alter column notes drop not null;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'bookings'
          and column_name = 'reference_code'
    ) then
        alter table public.bookings
            alter column reference_code drop not null;
    end if;
end;
$$;

create table if not exists public.payments (
    id uuid primary key default gen_random_uuid(),
    booking_id uuid not null references public.bookings(id) on delete cascade,
    player_id uuid not null references public.players(id) on delete cascade,
    amount numeric(12, 2) not null,
    currency text not null default 'INR',
    status text not null default 'success' check (status in ('success', 'failed', 'refunded')),
    provider text not null default 'simulated',
    provider_reference text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create unique index if not exists payments_booking_id_unique_idx
    on public.payments (booking_id);

create table if not exists public.reviews (
    id uuid primary key default gen_random_uuid(),
    booking_id uuid references public.bookings(id) on delete set null,
    player_id uuid not null references public.players(id) on delete cascade,
    arena_id uuid not null references public.arenas(id) on delete cascade,
    rating integer not null check (rating between 1 and 5),
    comment text,
    created_at timestamptz not null default now()
);

create table if not exists public.notifications (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('player', 'owner')),
    title text not null,
    message text not null,
    category text not null default 'general',
    metadata jsonb not null default '{}'::jsonb,
    is_read boolean not null default false,
    created_at timestamptz not null default now()
);

alter table public.notifications
    add column if not exists metadata jsonb not null default '{}'::jsonb;

create table if not exists public.analytics_events (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.owners(id) on delete cascade,
    arena_id uuid references public.arenas(id) on delete cascade,
    event_type text not null,
    amount numeric(12, 2) not null default 0,
    metadata jsonb not null default '{}'::jsonb,
    event_date date not null default current_date,
    created_at timestamptz not null default now()
);

drop trigger if exists set_arenas_updated_at on public.arenas;
create trigger set_arenas_updated_at
    before update on public.arenas
    for each row
    execute function public.set_updated_at();

drop trigger if exists set_arena_slots_updated_at on public.arena_slots;
create trigger set_arena_slots_updated_at
    before update on public.arena_slots
    for each row
    execute function public.set_updated_at();

drop trigger if exists set_bookings_updated_at on public.bookings;
create trigger set_bookings_updated_at
    before update on public.bookings
    for each row
    execute function public.set_updated_at();

alter table public.profile_phone_registry enable row level security;
alter table public.arenas enable row level security;
alter table public.arena_slots enable row level security;
alter table public.bookings enable row level security;
alter table public.payments enable row level security;
alter table public.reviews enable row level security;
alter table public.notifications enable row level security;
alter table public.analytics_events enable row level security;

drop policy if exists "Public can read active arenas" on public.arenas;
create policy "Public can read active arenas"
    on public.arenas
    for select
    using (is_active = true);

drop policy if exists "Owners manage own arenas" on public.arenas;
create policy "Owners manage own arenas"
    on public.arenas
    for all
    using (exists (
        select 1 from public.owners
        where owners.id = arenas.owner_id
          and owners.user_id = auth.uid()
    ))
    with check (exists (
        select 1 from public.owners
        where owners.id = arenas.owner_id
          and owners.user_id = auth.uid()
    ));

drop policy if exists "Users can read slots for active arenas" on public.arena_slots;
create policy "Users can read slots for active arenas"
    on public.arena_slots
    for select
    using (exists (
        select 1 from public.arenas
        where arenas.id = arena_slots.arena_id
          and arenas.is_active = true
    ));

drop policy if exists "Owners manage own arena slots" on public.arena_slots;
create policy "Owners manage own arena slots"
    on public.arena_slots
    for all
    using (exists (
        select 1
        from public.arenas
        join public.owners on owners.id = arenas.owner_id
        where arenas.id = arena_slots.arena_id
          and owners.user_id = auth.uid()
    ))
    with check (exists (
        select 1
        from public.arenas
        join public.owners on owners.id = arenas.owner_id
        where arenas.id = arena_slots.arena_id
          and owners.user_id = auth.uid()
    ));

drop policy if exists "Players and owners read own bookings" on public.bookings;
create policy "Players and owners read own bookings"
    on public.bookings
    for select
    using (
        exists (
            select 1 from public.players
            where players.id = bookings.player_id
              and players.user_id = auth.uid()
        )
        or exists (
            select 1 from public.owners
            where owners.id = bookings.owner_id
              and owners.user_id = auth.uid()
        )
    );

drop policy if exists "Players create own bookings" on public.bookings;
create policy "Players create own bookings"
    on public.bookings
    for insert
    with check (exists (
        select 1 from public.players
        where players.id = bookings.player_id
          and players.user_id = auth.uid()
    ));

drop policy if exists "Owners update own bookings" on public.bookings;
create policy "Owners update own bookings"
    on public.bookings
    for update
    using (exists (
        select 1 from public.owners
        where owners.id = bookings.owner_id
          and owners.user_id = auth.uid()
    ))
    with check (exists (
        select 1 from public.owners
        where owners.id = bookings.owner_id
          and owners.user_id = auth.uid()
    ));

drop policy if exists "Players read own payments" on public.payments;
create policy "Players read own payments"
    on public.payments
    for select
    using (exists (
        select 1 from public.players
        where players.id = payments.player_id
          and players.user_id = auth.uid()
    ));

drop policy if exists "Players create own payments" on public.payments;
create policy "Players create own payments"
    on public.payments
    for insert
    with check (exists (
        select 1 from public.players
        where players.id = payments.player_id
          and players.user_id = auth.uid()
    ));

drop policy if exists "Users read own notifications" on public.notifications;
create policy "Users read own notifications"
    on public.notifications
    for select
    using (auth.uid() = user_id);

drop policy if exists "Players create reviews" on public.reviews;
create policy "Players create reviews"
    on public.reviews
    for insert
    with check (exists (
        select 1 from public.players
        where players.id = reviews.player_id
          and players.user_id = auth.uid()
    ));

drop policy if exists "Public reads reviews" on public.reviews;
create policy "Public reads reviews"
    on public.reviews
    for select
    using (true);

drop policy if exists "Owners read own analytics events" on public.analytics_events;
create policy "Owners read own analytics events"
    on public.analytics_events
    for select
    using (exists (
        select 1 from public.owners
        where owners.id = analytics_events.owner_id
          and owners.user_id = auth.uid()
    ));
