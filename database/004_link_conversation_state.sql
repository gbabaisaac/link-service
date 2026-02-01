-- Conversation state machine storage for Link
create table if not exists link_conversation_state (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  conversation_id uuid not null,
  mode text not null default 'idle'
    check (mode in ('idle','conversation','agent','outreach','awaiting_consent')),
  active_task jsonb,
  pending_consents jsonb default '[]'::jsonb,
  resolved_tasks jsonb default '[]'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists link_conversation_state_user_id_idx
  on link_conversation_state(user_id);

create index if not exists link_conversation_state_conversation_id_idx
  on link_conversation_state(conversation_id);

create unique index if not exists link_conversation_state_user_convo_idx
  on link_conversation_state(user_id, conversation_id);
