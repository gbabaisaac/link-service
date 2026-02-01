-- Link outreach runs and targets

create table if not exists link_outreach_runs (
  id uuid primary key default gen_random_uuid(),
  link_conversation_id uuid not null references link_conversations(id) on delete cascade,
  requester_user_id uuid not null,
  query text not null,
  intent text not null,
  status text not null check (status in ('collecting','ranking','awaiting_consent','done','failed')),
  expansions integer not null default 0,
  confidence double precision,
  suggested_connection_user_id uuid,
  intent_payload jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists link_outreach_runs_link_convo_idx on link_outreach_runs(link_conversation_id);
create index if not exists link_outreach_runs_requester_idx on link_outreach_runs(requester_user_id);

create table if not exists link_outreach_targets (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references link_outreach_runs(id) on delete cascade,
  target_user_id uuid not null,
  dm_conversation_id uuid not null,
  outreach_message_id uuid not null,
  reply_message_id uuid,
  status text not null check (status in ('sent','replied','timed_out','declined')),
  sent_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists link_outreach_targets_run_idx on link_outreach_targets(run_id);
create index if not exists link_outreach_targets_target_idx on link_outreach_targets(target_user_id);
