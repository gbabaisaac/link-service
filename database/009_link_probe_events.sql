-- Probing detector events

create table if not exists link_probe_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id),
  query_text text,
  reason text,
  created_at timestamptz not null default now()
);

create index if not exists link_probe_events_user_idx on link_probe_events(user_id);
create index if not exists link_probe_events_created_idx on link_probe_events(created_at);
