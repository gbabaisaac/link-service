"""Partial Link outreach test (no forum)."""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("TEST_MODE", "true")

from config import settings
import supabase_client as db
import link_orchestrator as lo

EMAIL = "isaacgbaba4@gmail.com"
QUESTION = "looking for friends to go fishing"


def main():
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

    client = db.get_supabase_client()
    profiles = client.table("profiles").select("*").eq("email", EMAIL).execute().data
    if not profiles:
        raise SystemExit(f"No profile found for email {EMAIL}")
    requester = profiles[0]
    requester_id = requester["id"]
    university_id = requester.get("university_id")

    intent = {
        "intent": "person_search",
        "tags": ["fishing"],
        "time_window": None,
        "needs_outreach": True,
    }

    convo = db.get_or_create_link_conversation(requester_id)
    if not convo:
        raise SystemExit("No link conversation found")

    res = lo.start_outreach(
        user_id=requester_id,
        university_id=university_id,
        link_conversation_id=convo["id"],
        question=QUESTION,
        intent=intent,
        session_id=None,
        access_token=None,
    )
    run_id = res["run_id"]

    targets = db.list_link_outreach_targets(run_id)
    if not targets:
        # Fallback: pick any other profile as target for demo
        pool = (
            client.table("profiles")
            .select("id")
            .neq("id", requester_id)
            .limit(5)
            .execute()
            .data
        )
        if not pool:
            raise SystemExit("No targets found; check seed data")
        for row in pool:
            target_user_id = row["id"]
            convo = db.get_or_create_dm_conversation(requester_id, target_user_id)
            if not convo:
                continue
            msg = db.insert_message(
                convo["id"],
                requester_id,
                "demo outreach: are you into fishing? reply YES if you're down.",
                {"shareType": "text"},
            )
            db.create_link_outreach_targets(
                [
                    {
                        "run_id": run_id,
                        "target_user_id": target_user_id,
                        "dm_conversation_id": convo["id"],
                        "outreach_message_id": msg.get("id"),
                        "status": "sent",
                    }
                ]
            )
        targets = db.list_link_outreach_targets(run_id)
        if not targets:
            raise SystemExit("No targets found; check seed data")

    first = targets[0]
    reply_text = "yeah I fish, down to connect. YES"
    msg = db.insert_message(first["dm_conversation_id"], first["target_user_id"], reply_text, {"shareType": "text"})

    result = lo.collect_outreach(run_id, university_id, session_id=None, access_token=None)
    run = db.get_link_outreach_run(run_id)

    print("run_id", run_id)
    print("outreach_result", result)
    print("run_status", run.get("status"))
    print("suggested_user", run.get("suggested_connection_user_id"))
    print("reply_message_id", msg.get("id"))

    suggested = run.get("suggested_connection_user_id")
    if suggested:
        print("---- consent flow: requester says NO ----")
        res_no = lo.resolve_consent(
            run_id=run_id,
            requester_user_id=requester_id,
            target_user_id=suggested,
            requester_ok=False,
            target_ok=True,
        )
        print("consent_no", res_no)
        run_no = db.get_link_outreach_run(run_id)
        print("status_after_no", run_no.get("status"))

        print("---- consent flow: requester says YES ----")
        res_yes = lo.resolve_consent(
            run_id=run_id,
            requester_user_id=requester_id,
            target_user_id=suggested,
            requester_ok=True,
            target_ok=True,
        )
        print("consent_yes", res_yes)
        run_yes = db.get_link_outreach_run(run_id)
        print("status_after_yes", run_yes.get("status"))


if __name__ == "__main__":
    main()
