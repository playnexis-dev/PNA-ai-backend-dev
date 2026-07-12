create extension if not exists pgcrypto;

create table if not exists public.user_roles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    role text not null check (role in ('player', 'owner')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.players (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null unique references auth.users(id) on delete cascade,
    full_name text not null,
    email text not null,
    phone text,
    avatar_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.owners (
    id uuid primary key default gen_random_uuid(),
    user_id uuid unique references auth.users(id) on delete cascade,
    full_name text not null,
    email text not null,
    phone text not null,
    company_name text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.owners
    add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table public.owners
    add column if not exists created_at timestamptz not null default now();

alter table public.owners
    add column if not exists updated_at timestamptz not null default now();

create unique index if not exists players_email_unique_idx
    on public.players (lower(email));

create unique index if not exists owners_email_unique_idx
    on public.owners (lower(email));

create unique index if not exists owners_user_id_unique_idx
    on public.owners (user_id)
    where user_id is not null;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists set_players_updated_at on public.players;
create trigger set_players_updated_at
    before update on public.players
    for each row
    execute function public.set_updated_at();

drop trigger if exists set_user_roles_updated_at on public.user_roles;
create trigger set_user_roles_updated_at
    before update on public.user_roles
    for each row
    execute function public.set_updated_at();

drop trigger if exists set_owners_updated_at on public.owners;
create trigger set_owners_updated_at
    before update on public.owners
    for each row
    execute function public.set_updated_at();

alter table public.players enable row level security;
alter table public.owners enable row level security;
alter table public.user_roles enable row level security;

drop policy if exists "Players can read their own profile" on public.players;
create policy "Players can read their own profile"
    on public.players
    for select
    using (auth.uid() = user_id);

drop policy if exists "Backend can create player profiles" on public.players;
drop policy if exists "Users can create their own player profile" on public.players;
create policy "Users can create their own player profile"
    on public.players
    for insert
    with check (auth.uid() = user_id);

drop policy if exists "Players can update their own profile" on public.players;
create policy "Players can update their own profile"
    on public.players
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can read their own role" on public.user_roles;
create policy "Users can read their own role"
    on public.user_roles
    for select
    using (auth.uid() = user_id);

drop policy if exists "Backend can create user roles" on public.user_roles;
drop policy if exists "Users can create their own role" on public.user_roles;
create policy "Users can create their own role"
    on public.user_roles
    for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can update their own role" on public.user_roles;
create policy "Users can update their own role"
    on public.user_roles
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Owners can read their own profile" on public.owners;
create policy "Owners can read their own profile"
    on public.owners
    for select
    using (auth.uid() = user_id);

drop policy if exists "Backend can create owner profiles" on public.owners;
drop policy if exists "Users can create their own owner profile" on public.owners;
create policy "Users can create their own owner profile"
    on public.owners
    for insert
    with check (auth.uid() = user_id);

drop policy if exists "Owners can update their own profile" on public.owners;
create policy "Owners can update their own profile"
    on public.owners
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
