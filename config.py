"""Environment configuration for Link AI service."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment."""

    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

    # Provider selection
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")  # "openai" or "gemini"

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Google Gemini
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

    # Link Config
    CONFIDENCE_THRESHOLD: float = float(os.getenv("LINK_CONFIDENCE_THRESHOLD", "0.75"))
    OUTREACH_BATCH_SIZE: int = int(os.getenv("LINK_OUTREACH_BATCH_SIZE", "5"))
    OUTREACH_WAIT_MINUTES: int = int(os.getenv("LINK_OUTREACH_WAIT_MINUTES", "12"))
    MAX_OUTREACH_BATCHES: int = int(os.getenv("LINK_MAX_OUTREACH_BATCHES", "3"))
    OUTREACH_HARD_CAP: int = int(os.getenv("LINK_OUTREACH_HARD_CAP", "25"))
    OUTREACH_CONFIDENCE_THRESHOLD: float = float(os.getenv("LINK_OUTREACH_CONFIDENCE_THRESHOLD", "0.75"))
    REINDEX_ON_START: bool = os.getenv("LINK_REINDEX_ON_START", "false").lower() == "true"
    TEST_MODE: bool = os.getenv("TEST_MODE", "false").lower() == "true"

    # Admin
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")

    @classmethod
    def validate(cls) -> list[str]:
        """Validate required settings, return list of missing vars."""
        missing = []
        if not cls.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not cls.SUPABASE_SERVICE_KEY:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        # LLM provider-specific checks
        if cls.LLM_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if cls.LLM_PROVIDER == "gemini" and not cls.GOOGLE_API_KEY:
            missing.append("GOOGLE_API_KEY")
        return missing


settings = Settings()
