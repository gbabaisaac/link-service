create table if not exists link_reminders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  university_id uuid not null references universities(id),
  target_time timestamptz not null,
  message_text text not null,
  status text not null default 'pending' check (status in ('pending','sent','cancelled')),
  sent_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists link_reminders_user_id_idx on link_reminders(user_id);
create index if not exists link_reminders_status_idx on link_reminders(status);
create index if not exists link_reminders_target_time_idx on link_reminders(target_time);
