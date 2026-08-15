-- Admin users may retain a valid Owner profile and own arenas through that profile.

create or replace function public.admin_assign_arena_owner(
    p_arena_id uuid,
    p_owner_id uuid
)
returns public.arenas
language plpgsql
security definer
set search_path = public
as $$
declare
    assigned_arena public.arenas;
begin
    if not public.is_active_admin() then
        raise exception 'Only an active PLAYNEXIS Admin can assign an arena owner';
    end if;

    if not exists (select 1 from public.owners where id = p_owner_id) then
        raise exception 'Owner not found';
    end if;

    if not exists (select 1 from public.arenas where id = p_arena_id) then
        raise exception 'Arena not found';
    end if;

    update public.turfs
    set owner_id = p_owner_id
    where arena_id = p_arena_id;

    update public.bookings
    set owner_id = p_owner_id
    where arena_id = p_arena_id;

    update public.arena_maintenance_windows
    set owner_id = p_owner_id
    where arena_id = p_arena_id;

    update public.analytics_events
    set owner_id = p_owner_id
    where arena_id = p_arena_id;

    update public.arenas
    set owner_id = p_owner_id,
        management_mode = 'owner'
    where id = p_arena_id
    returning * into assigned_arena;

    return assigned_arena;
end;
$$;

revoke all on function public.admin_assign_arena_owner(uuid, uuid) from public;
grant execute on function public.admin_assign_arena_owner(uuid, uuid) to authenticated;
