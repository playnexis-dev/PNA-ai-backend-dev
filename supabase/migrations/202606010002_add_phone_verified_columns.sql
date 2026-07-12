alter table public.players
    add column if not exists phone_verified boolean not null default false;

alter table public.owners
    add column if not exists phone_verified boolean not null default false;

update public.players
set phone_verified = true
where phone is not null and btrim(phone) <> '';

update public.owners
set phone_verified = true
where phone is not null and btrim(phone) <> '';
