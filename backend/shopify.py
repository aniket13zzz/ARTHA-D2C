"""
artha-v2/backend/shopify.py
Shopify integration — fetch orders.
DATA MINIMIZATION: store only order_id, amount, status, created_at.
NO PII: names, emails, addresses, phones are NEVER stored.
"""

import logging
import httpx
from datetime import datetime, timedelta
from typing import Any
from backend.crypto import decrypt

logger = logging.getLogger(__name__)

SHOPIFY_API_VERSION = "2024-04"
PAGE_LIMIT = 250  # max per Shopify page


class ShopifyClient:
    def __init__(self, shop_domain: str, encrypted_token: str):
        self.shop_domain = shop_domain
        self.access_token = decrypt(encrypted_token)
        self.base_url = f"https://{shop_domain}/admin/api/{SHOPIFY_API_VERSION}"
        self.headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    async def verify_connection(self) -> bool:
        """Verify Shopify credentials are still valid."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/shop.json",
                    headers=self.headers,
                )
                return resp.status_code == 200
        except Exception:
            logger.error("Shopify connection verify failed", exc_info=True)
            return False

    async def fetch_orders(
        self,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch orders from Shopify.
        Returns stripped records — NO PII.
        """
        if since_dt is None:
            since_dt = datetime.utcnow() - timedelta(days=1)

        params: dict[str, Any] = {
            "status": "any",
            "limit": PAGE_LIMIT,
            "created_at_min": since_dt.isoformat() + "Z",
            "fields": "id,financial_status,total_price,created_at,refunds",
        }
        if until_dt:
            params["created_at_max"] = until_dt.isoformat() + "Z"

        orders: list[dict] = []
        url = f"{self.base_url}/orders.json"

        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                resp = await client.get(url, headers=self.headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                raw_orders = data.get("orders", [])
                orders.extend(self._strip_pii(o) for o in raw_orders)

                # Pagination via Link header
                link = resp.headers.get("Link", "")
                url = self._parse_next_link(link)
                params = {}  # next page URL already has params

        logger.info(f"Shopify: fetched {len(orders)} orders from {self.shop_domain}")
        return orders

    async def fetch_refunds(self, order_id: str) -> list[dict[str, Any]]:
        """Fetch refunds for a specific order."""
        url = f"{self.base_url}/orders/{order_id}/refunds.json"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self.headers)
                resp.raise_for_status()
                refunds = resp.json().get("refunds", [])
                return [self._strip_refund_pii(r) for r in refunds]
        except Exception:
            logger.error(f"Failed to fetch refunds for order {order_id}", exc_info=True)
            return []

    def _strip_pii(self, order: dict) -> dict:
        """Strip PII. Return only safe fields."""
        return {
            "shopify_order_id": str(order.get("id", "")),
            "status": order.get("financial_status", ""),
            # Convert rupees string → paise BIGINT
            "amount_paise": self._rupees_to_paise(order.get("total_price", "0")),
            "created_at": order.get("created_at"),
            "refunds": [
                self._strip_refund_pii(r)
                for r in order.get("refunds", [])
            ],
        }

    def _strip_refund_pii(self, refund: dict) -> dict:
        """Strip PII from refund record."""
        total_paise = sum(
            self._rupees_to_paise(t.get("amount", "0"))
            for t in refund.get("transactions", [])
        )
        return {
            "refund_id": str(refund.get("id", "")),
            "order_id": str(refund.get("order_id", "")),
            "amount_paise": total_paise,
            "status": refund.get("transactions", [{}])[0].get("status", ""),
            "created_at": refund.get("created_at"),
        }

    @staticmethod
    def _rupees_to_paise(value: str | float | int) -> int:
        """Convert rupee string/float → BIGINT paise. NO FLOAT stored."""
        try:
            rupees = float(str(value).replace(",", ""))
            return int(round(rupees * 100))
        except (ValueError, TypeError):
            logger.warning(f"Invalid rupee value: {value}")
            return 0

    @staticmethod
    def _parse_next_link(link_header: str) -> str | None:
        """Parse Shopify Link header for next page URL."""
        if not link_header:
            return None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return url
        return None
