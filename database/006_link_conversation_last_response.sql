alter table link_conversation_state
  add column if not exists last_db_response jsonb default null;

