-- User sharing rules for privacy dashboard

create table if not exists link_sharing_rules (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  rule_type text not null,
  target_user_id uuid,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists link_sharing_rules_user_idx on link_sharing_rules(user_id);
create index if not exists link_sharing_rules_target_idx on link_sharing_rules(target_user_id);

alter table public.link_sharing_rules enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies where schemaname='public' and tablename='link_sharing_rules' and policyname='link_sharing_rules_owner'
  ) then
    execute 'create policy link_sharing_rules_owner on public.link_sharing_rules
      for all using (user_id = auth.uid()) with check (user_id = auth.uid())';
  end if;
end $$;
