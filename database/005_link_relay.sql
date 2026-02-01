-- Link-to-Link relay runs for asking another user's Link instance
create table if not exists link_relay_runs (
  id uuid primary key default gen_random_uuid(),
  requester_user_id uuid not null references profiles(id),
  requester_conversation_id uuid not null,
  target_user_id uuid not null references profiles(id),
  question text not null,
  status text not null default 'pending'
    check (status in ('pending','awaiting_target','answered','declined','failed')),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists link_relay_runs_requester_idx
  on link_relay_runs(requester_user_id);

create index if not exists link_relay_runs_target_idx
  on link_relay_runs(target_user_id);

create table if not exists link_relay_targets (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references link_relay_runs(id) on delete cascade,
  dm_conversation_id uuid not null,
  outreach_message_id uuid not null,
  reply_message_id uuid null,
  status text not null default 'sent'
    check (status in ('sent','replied','declined','timed_out')),
  sent_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists link_relay_targets_run_idx
  on link_relay_targets(run_id);
