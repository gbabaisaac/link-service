-- Forum fallback for outreach

alter table link_outreach_runs
  add column if not exists forum_id uuid,
  add column if not exists forum_post_id uuid,
  add column if not exists forum_posted_at timestamptz;

alter table link_outreach_runs
  drop constraint if exists link_outreach_runs_status_check;

alter table link_outreach_runs
  add constraint link_outreach_runs_status_check
  check (status in ('collecting','ranking','awaiting_consent','done','failed','forum_posted'));

alter table link_outreach_targets
  add column if not exists source_comment_id uuid;
