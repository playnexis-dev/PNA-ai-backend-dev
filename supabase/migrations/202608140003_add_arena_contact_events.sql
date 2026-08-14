create table if not exists public.arena_contact_events (
    id uuid primary key default gen_random_uuid(),
    arena_id uuid not null references public.arenas(id) on delete cascade,
    arena_name text not null,
    user_id uuid references auth.users(id) on delete set null,
    anonymous_id uuid not null,
    event_type text not null check (event_type in ('view_number', 'whatsapp')),
    created_at timestamptz not null default now()
);

create index if not exists idx_arena_contact_events_arena_created
    on public.arena_contact_events(arena_id, created_at desc);

create index if not exists idx_arena_contact_events_user_created
    on public.arena_contact_events(user_id, created_at desc)
    where user_id is not null;

create index if not exists idx_arena_contact_events_anonymous
    on public.arena_contact_events(anonymous_id)
    where user_id is null;

alter table public.arena_contact_events enable row level security;

comment on table public.arena_contact_events is
    'Tracks explicit View Number and WhatsApp actions for arena contacts.';
