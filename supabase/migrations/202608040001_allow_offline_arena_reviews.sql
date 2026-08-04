-- Allow authenticated players to leave one bookingless review per arena.
alter table public.reviews
    alter column booking_id drop not null;

create unique index if not exists reviews_player_arena_offline_unique_idx
    on public.reviews (player_id, arena_id)
    where booking_id is null;
