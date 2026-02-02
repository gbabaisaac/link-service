import time
import signal
import sys
from datetime import datetime, timezone
import supabase_client as db
from link_instance import LinkInstance

# --- Configuration ---
POLL_INTERVAL_SECONDS = 60
MAX_JOBS_PER_BATCH = 50

def handle_jobs():
    """Fetch and process pending jobs."""
    try:
        jobs = db.list_pending_jobs(limit=MAX_JOBS_PER_BATCH)
        if not jobs:
            return

        print(f"[{datetime.now()}] Found {len(jobs)} pending jobs.")
        
        for job in jobs:
            try:
                # 1. Mark as processing
                db.update_job_status(job["id"], "processing")
                
                # 2. Instantiate Link for User
                user_id = job["user_id"]
                instance = LinkInstance(user_id) # Service Role (admin) access implied
                
                # 3. Execute
                instance.run_scheduled_job(job)
                
                # 4. Mark Complete
                db.update_job_status(job["id"], "completed")
                print(f"[{datetime.now()}] Completed job {job['id']} for user {user_id}")
                
            except Exception as e:
                print(f"[{datetime.now()}] FAILED job {job['id']}: {e}")
                db.update_job_status(job["id"], "failed")
                
    except Exception as e:
        print(f"[{datetime.now()}] Worker Error: {e}")

def run_worker():
    """Main loop."""
    print(f"[{datetime.now()}] Link Scheduler Worker Started.")
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds...")
    
    while True:
        handle_jobs()
        time.sleep(POLL_INTERVAL_SECONDS)

# Graceful Shutdown
def signal_handler(sig, frame):
    print('Stopping worker...')
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    run_worker()
