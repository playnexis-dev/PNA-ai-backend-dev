create table if not exists public.email_verifications (
    user_id uuid primary key references auth.users(id) on delete cascade,
    email text not null,
    verified_at timestamptz,
    token_version integer not null default 1 check (token_version > 0),
    last_sent_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists email_verifications_email_lower_idx
    on public.email_verifications (lower(email));

alter table public.email_verifications enable row level security;

-- Preserve the verification status of existing accounts. Google and previously
-- confirmed password accounts remain verified; pending password accounts do not.
insert into public.email_verifications (user_id, email, verified_at)
select id, email, email_confirmed_at
from auth.users
where email is not null
on conflict (user_id) do nothing;

