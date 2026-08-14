create or replace function public.protect_arena_management_mode()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if new.management_mode is distinct from old.management_mode
       and coalesce(auth.role(), '') <> 'service_role'
       and not public.is_active_admin() then
        raise exception 'Only an active PLAYNEXIS Admin can change arena management';
    end if;

    return new;
end;
$$;

revoke all on function public.protect_arena_management_mode() from public;

drop trigger if exists protect_arena_management_mode_trigger on public.arenas;
create trigger protect_arena_management_mode_trigger
    before update of management_mode on public.arenas
    for each row execute function public.protect_arena_management_mode();

drop policy if exists "Admins can read owner profiles" on public.owners;
create policy "Admins can read owner profiles"
    on public.owners for select
    using (public.is_active_admin());

drop policy if exists "Admins can read player profiles" on public.players;
create policy "Admins can read player profiles"
    on public.players for select
    using (public.is_active_admin());

drop policy if exists "Admins can write audit logs" on public.admin_audit_logs;
create policy "Admins can write audit logs"
    on public.admin_audit_logs for insert
    with check (
        public.is_active_admin()
        and admin_user_id = auth.uid()
    );
