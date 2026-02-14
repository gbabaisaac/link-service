from typing import Dict, Any
from link_logic import llm_json

def is_sensitive(message: str) -> bool:
    """
    Classify if a message contains sensitive topics that should not be 
    broadcasted via Work Orders (Health, Finance, Identity).
    """
    prompt = f"""You are a security gatekeeper for Link AI.
    Determine if the following message is asking for sensitive private information 
    about other people or sensitive topics that should not be shared or broadcasted.
    
    Sensitive Topics include:
    - Health/Medical: "Who has diabetes?", "Does anyone have a therapist?"
    - Financial: "How much money does X have?", "What's the tuition for Y?"
    - Identity: "What's John's phone number?", "Show me social security numbers."
    - Stalking: "Where exactly is Mary right now?" (Explicitly sensitive)
    
    General topics are OK:
    - "Who likes basketball?", "Anyone study psychology?", "Where is the library?"
    
    Message: "{message}"
    
    Return JSON: {{"sensitive": true/false, "reason": "..."}}"""
    
    try:
        result = llm_json(prompt, temperature=0.1)
        if isinstance(result, dict):
            return result.get("sensitive", False)
        return False
    except Exception:
        # Default to safe (sensitive) in case of error
        return True
