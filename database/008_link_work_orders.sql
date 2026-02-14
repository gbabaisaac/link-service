-- Link work orders for Brain B (Public Runner)

create table if not exists link_work_orders (
  id uuid primary key default gen_random_uuid(),
  university_id uuid not null references universities(id),
  intent text not null,
  query text not null,
  public_tags jsonb not null default '{}'::jsonb,
  status text not null default 'pending'
    check (status in ('pending','processing','completed','failed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists link_work_orders_status_idx on link_work_orders(status);
create index if not exists link_work_orders_university_idx on link_work_orders(university_id);

create table if not exists link_work_order_results (
  id uuid primary key default gen_random_uuid(),
  work_order_id uuid not null references link_work_orders(id) on delete cascade,
  target_user_id uuid not null references profiles(id),
  status text not null default 'selected'
    check (status in ('selected','notified','declined','accepted')),
  created_at timestamptz not null default now()
);

create index if not exists link_work_order_results_order_idx on link_work_order_results(work_order_id);
create index if not exists link_work_order_results_target_idx on link_work_order_results(target_user_id);

-- Mapping table kept private (Vault only)
create table if not exists link_work_order_map (
  id uuid primary key default gen_random_uuid(),
  work_order_id uuid not null references link_work_orders(id) on delete cascade,
  requester_user_id uuid not null references profiles(id),
  conversation_id uuid,
  created_at timestamptz not null default now()
);

create index if not exists link_work_order_map_order_idx on link_work_order_map(work_order_id);
