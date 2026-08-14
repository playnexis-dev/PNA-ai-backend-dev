create table if not exists public.site_counters (
    counter_key text primary key,
    counter_value bigint not null default 0 check (counter_value >= 0),
    updated_at timestamptz not null default now()
);

insert into public.site_counters (counter_key, counter_value)
values ('home_page', 8910)
on conflict (counter_key) do update
set counter_value = greatest(public.site_counters.counter_value, excluded.counter_value);

create or replace function public.increment_site_counter(
    p_counter_key text,
    p_baseline bigint default 0
)
returns bigint
language plpgsql
security definer
set search_path = public
as $$
declare
    next_value bigint;
begin
    insert into public.site_counters (counter_key, counter_value, updated_at)
    values (p_counter_key, greatest(p_baseline, 0) + 1, now())
    on conflict (counter_key) do update
    set counter_value = greatest(public.site_counters.counter_value, greatest(p_baseline, 0)) + 1,
        updated_at = now()
    returning counter_value into next_value;

    return next_value;
end;
$$;

alter table public.site_counters enable row level security;

revoke all on table public.site_counters from anon, authenticated;
revoke all on function public.increment_site_counter(text, bigint) from public;
grant execute on function public.increment_site_counter(text, bigint) to anon, authenticated, service_role;
