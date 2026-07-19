alter table public.arena_maintenance_windows
    add column if not exists turf_id uuid references public.turfs(id) on delete cascade;

create index if not exists arena_maintenance_windows_turf_idx
    on public.arena_maintenance_windows (turf_id, status, start_at, end_at);
