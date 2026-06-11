"""
artha-v2/backend/integrations/__init__.py
Platform factory — returns correct ecom client for org.
"""

from backend.integrations.factory import get_ecom_client, EcomClient

__all__ = ["get_ecom_client", "EcomClient"]
