-- Cache of verified facts for fast reuse

create table if not exists link_verified_facts (
  id uuid primary key default gen_random_uuid(),
  university_id uuid not null,
  entity_type text,
  entity_id uuid,
  fact_category text not null,
  fact_key text not null,
  fact_value text not null,
  confidence double precision not null default 0,
  source_type text not null,
  source_id uuid,
  consent_status text not null default 'opt_in',
  verified_at timestamptz not null default now(),
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists link_verified_facts_university_idx on link_verified_facts(university_id);
create index if not exists link_verified_facts_entity_idx on link_verified_facts(entity_id);
create index if not exists link_verified_facts_fact_value_idx on link_verified_facts(fact_value);
