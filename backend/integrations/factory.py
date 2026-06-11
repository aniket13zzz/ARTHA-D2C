"""
artha-v2/backend/integrations/factory.py

Platform factory pattern.
Returns EcomClient wrapping either ShopifyClient or WooCommerceClient.
Reconciliation engine stays platform-agnostic — receives normalized orders.

Normalized order shape (same from both platforms):
{
  "shopify_order_id": str,     # order ID (Shopify) or WooCommerce order ID
  "status":           str,     # "paid" | "refunded" | "voided" | "pending"
  "amount_paise":     int,     # BIGINT paise
  "created_at":       str,     # ISO datetime
  "refunds":          list,    # list of normalized refund dicts
  "razorpay_order_id": str|None  # extracted Razorpay payment ID if available
}
"""

import logging
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EcomClientProtocol(Protocol):
    async def verify_connection(self) -> bool: ...
    async def fetch_orders(
        self,
        since_dt: datetime | None,
        until_dt: datetime | None,
    ) -> list[dict[str, Any]]: ...
    async def fetch_refunds(self, order_id: str) -> list[dict[str, Any]]: ...


class EcomClient:
    """
    Wraps platform-specific client.
    Exposes unified interface to sync.py + reconciliation.py.
    """

    def __init__(self, platform: str, client: EcomClientProtocol):
        self.platform = platform
        self._client = client

    async def verify_connection(self) -> bool:
        return await self._client.verify_connection()

    async def fetch_orders(
        self,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch normalized orders from platform."""
        return await self._client.fetch_orders(since_dt=since_dt, until_dt=until_dt)

    async def fetch_refunds(self, order_id: str) -> list[dict[str, Any]]:
        return await self._client.fetch_refunds(order_id)


def get_ecom_client(platform: str, creds: dict) -> EcomClient:
    """
    Factory: returns EcomClient for given platform.

    Args:
        platform: 'shopify' | 'woocommerce'
        creds: raw credential row from DB (fields vary by platform)

    Returns:
        EcomClient wrapping platform-specific client
    """
    if platform == "shopify":
        from backend.shopify import ShopifyClient
        client = ShopifyClient(
            shop_domain=creds["shop_domain"],
            encrypted_token=creds["encrypted_access_token"],
        )
        return EcomClient(platform="shopify", client=client)

    elif platform == "woocommerce":
        from backend.woocommerce import WooCommerceClient
        client = WooCommerceClient(
            site_url=creds["site_url"],
            encrypted_consumer_key=creds["encrypted_consumer_key"],
            encrypted_consumer_secret=creds["encrypted_consumer_secret"],
            api_version=creds.get("api_version", "wc/v3"),
        )
        return EcomClient(platform="woocommerce", client=client)

    else:
        raise ValueError(f"Unsupported ecom platform: {platform}")


def get_ecom_creds_from_db(db, org_id: str) -> list[dict[str, Any]]:
    """
    Load ALL active ecom credentials for org.
    Returns list with platform tag so factory can instantiate correct client.
    Supports orgs connected to both Shopify + WooCommerce simultaneously.

    Handles DB errors gracefully — if one platform fails to load,
    the other still syncs.
    """
    results = []

    # Shopify
    try:
        shopify = (
            db.table("shopify_credentials")
            .select("shop_domain, encrypted_access_token")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        if shopify.data:
            results.append({**shopify.data, "platform": "shopify"})
    except Exception as e:
        logger.error(f"Failed to load Shopify creds for org {org_id}: {e}")

    # WooCommerce
    try:
        woo = (
            db.table("woocommerce_credentials")
            .select("site_url, encrypted_consumer_key, encrypted_consumer_secret, api_version")
            .eq("org_id", org_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        if woo.data:
            results.append({**woo.data, "platform": "woocommerce"})
    except Exception as e:
        logger.error(f"Failed to load WooCommerce creds for org {org_id}: {e}")

    if not results:
        logger.warning(f"No active ecom credentials found for org {org_id}")

    return results
