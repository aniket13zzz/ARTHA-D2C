"""
artha-v2/backend/db.py
Supabase client — service role for backend operations.
"""

import logging
from functools import lru_cache
from supabase import create_client, Client
from backend.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_db() -> Client:
    """Return cached Supabase service-role client."""
    client = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )
    logger.info("Supabase client initialised")
    return client


def get_anon_db() -> Client:
    """Return Supabase anon client (for user-scoped queries with JWT)."""
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY,
    )
