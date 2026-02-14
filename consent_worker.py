import time
import supabase_client as db
from datetime import datetime, timezone

POLL_INTERVAL = 60

def process_accepted_results():
    """
    Find work order results that are 'accepted' but haven't been 
    handled by the requester's Link yet.
    """
    # 1. List work order results with 'accepted' status
    # Note: We need a status like 'delivered' or 'handshake_pending' 
    # to avoid double-processing.
    client = db.get_supabase_client()
    accepted_results = (
        client.table("link_work_order_results")
        .select("*")
        .eq("status", "accepted")
        .execute()
        .data
    )
    
    for result in accepted_results:
        work_order_id = result["work_order_id"]
        target_user_id = result["target_user_id"]
        
        # 2. Find the requester via the private map (Vault access only)
        mapping = db.get_work_order_map(work_order_id)
        if not mapping:
            continue
            
        requester_id = mapping["requester_user_id"]
        convo_id = mapping.get("conversation_id")
        
        if not convo_id:
            # Fallback: Find most recent convo
            continue

        # 3. Inform the requester's Link Instance
        # We push a message into the requester's thread
        intro_text = f"I found someone who can help with your request! Should I introduce you? (Reply YES to share your contact info)."
        
        db.insert_link_message(
            conversation_id=convo_id,
            sender_id=None, # System/Link
            content=intro_text,
            sender_type="link",
            metadata={"action": "consent_prompt", "target_user_id": str(target_user_id), "work_order_id": str(work_order_id)}
        )
        
        # 4. Mark result as 'processed' to avoid duplicate prompts
        # We'll use status 'fulfilled' or 'consented'
        db.update_work_order_result_status(result["id"], "handshake_pending")

if __name__ == "__main__":
    print(f"[{datetime.now(timezone.utc).isoformat()}] Consent Worker started...")
    while True:
        try:
            process_accepted_results()
        except Exception as e:
            print(f"Error in Consent Worker: {e}")
        time.sleep(POLL_INTERVAL)
