-- Internal PLAYNEXIS administrators and arena management responsibility.

alter table public.user_roles
    drop constraint if exists user_roles_role_check;
alter table public.user_roles
    add constraint user_roles_role_check
    check (role in ('player', 'owner', 'admin'));

create table if not exists public.admins (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null unique references auth.users(id) on delete cascade,
    email text not null,
    full_name text,
    status text not null default 'invited'
        check (status in ('invited', 'active', 'disabled')),
    invited_by_user_id uuid references auth.users(id) on delete set null,
    previous_role text check (previous_role is null or previous_role in ('player', 'owner')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.arenas
    add column if not exists management_mode text not null default 'owner';

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.arenas'::regclass
          and conname = 'arenas_management_mode_check'
    ) then
        alter table public.arenas
            add constraint arenas_management_mode_check
            check (management_mode in ('owner', 'admin'));
    end if;
end $$;

create table if not exists public.admin_audit_logs (
    id uuid primary key default gen_random_uuid(),
    admin_user_id uuid not null references auth.users(id) on delete restrict,
    action text not null,
    entity_type text not null,
    entity_id text,
    before_data jsonb,
    after_data jsonb,
    created_at timestamptz not null default now()
);

create index if not exists admins_status_idx on public.admins(status);
create index if not exists arenas_management_mode_idx on public.arenas(management_mode);
create index if not exists admin_audit_logs_admin_created_idx
    on public.admin_audit_logs(admin_user_id, created_at desc);
create index if not exists admin_audit_logs_entity_idx
    on public.admin_audit_logs(entity_type, entity_id, created_at desc);

drop trigger if exists set_admins_updated_at on public.admins;
create trigger set_admins_updated_at
    before update on public.admins
    for each row execute function public.set_updated_at();

create or replace function public.protect_final_active_admin()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    if old.status = 'active' and new.status <> 'active' then
        perform pg_advisory_xact_lock(hashtext('playnexis-active-admin-status'));
        if (select count(*) from public.admins where status = 'active') <= 1 then
            raise exception 'The final active Admin cannot be disabled';
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists protect_final_active_admin_trigger on public.admins;
create trigger protect_final_active_admin_trigger
    before update of status on public.admins
    for each row execute function public.protect_final_active_admin();

create or replace function public.is_active_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.user_roles roles
        join public.admins admins on admins.user_id = roles.user_id
        where roles.user_id = auth.uid()
          and roles.role = 'admin'
          and admins.status = 'active'
    );
$$;

revoke all on function public.is_active_admin() from public;
grant execute on function public.is_active_admin() to authenticated;

alter table public.admins enable row level security;
alter table public.admin_audit_logs enable row level security;

drop policy if exists "Admins can read admin profiles" on public.admins;
create policy "Admins can read admin profiles"
    on public.admins for select
    using (public.is_active_admin() or user_id = auth.uid());

drop policy if exists "Admins can read audit logs" on public.admin_audit_logs;
create policy "Admins can read audit logs"
    on public.admin_audit_logs for select
    using (public.is_active_admin());

drop policy if exists "Admins manage all arenas" on public.arenas;
create policy "Admins manage all arenas"
    on public.arenas for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all turfs" on public.turfs;
create policy "Admins manage all turfs"
    on public.turfs for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all arena slots" on public.arena_slots;
create policy "Admins manage all arena slots"
    on public.arena_slots for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all bookings" on public.bookings;
create policy "Admins manage all bookings"
    on public.bookings for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all payments" on public.payments;
create policy "Admins manage all payments"
    on public.payments for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all reviews" on public.reviews;
create policy "Admins manage all reviews"
    on public.reviews for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all maintenance" on public.arena_maintenance_windows;
create policy "Admins manage all maintenance"
    on public.arena_maintenance_windows for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all analytics events" on public.analytics_events;
create policy "Admins manage all analytics events"
    on public.analytics_events for all
    using (public.is_active_admin())
    with check (public.is_active_admin());

drop policy if exists "Admins manage all notifications" on public.notifications;
create policy "Admins manage all notifications"
    on public.notifications for all
    using (public.is_active_admin())
    with check (public.is_active_admin());
