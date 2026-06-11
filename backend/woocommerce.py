"""
artha-v2/backend/woocommerce.py
WooCommerce REST API client — production-grade.

Mirrors ShopifyClient interface exactly.
DATA MINIMIZATION: order_id, amount, status, created_at only.
NO PII: names, emails, addresses, phones NEVER stored.

Auth: HTTP Basic (consumer_key:consumer_secret) over HTTPS only.
Handles: pagination, rate limits (429), timeouts, SSL errors.
"""

import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Any
from backend.crypto import decrypt

logger = logging.getLogger(__name__)

WC_DEFAULT_API_VERSION = "wc/v3"
PAGE_SIZE = 100
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 45.0
MAX_PAGES = 500          # safety cap — 50,000 orders max per sync
RATE_LIMIT_BACKOFF = 60  # seconds to wait on 429


class WooCommerceClient:
    """
    WooCommerce REST API v3 client.
    All monetary values returned as BIGINT paise.
    """

    def __init__(
        self,
        site_url: str,
        encrypted_consumer_key: str,
        encrypted_consumer_secret: str,
        api_version: str = WC_DEFAULT_API_VERSION,
    ):
        self.site_url = site_url.rstrip("/")
        self.consumer_key = decrypt(encrypted_consumer_key)
        self.consumer_secret = decrypt(encrypted_consumer_secret)
        self.api_version = api_version
        self.base_url = f"{self.site_url}/wp-json/{api_version}"
        self.auth = (self.consumer_key, self.consumer_secret)
        self._timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT,
            read=READ_TIMEOUT,
            write=10.0,
            pool=5.0,
        )

    async def verify_connection(self) -> bool:
        """
        Verify WooCommerce credentials.
        Tests /orders?per_page=1 — requires Read permission.
        Returns False on any error (auth, SSL, timeout, DNS).
        """
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=8.0, read=10.0, write=5.0, pool=5.0),
                verify=True,
                follow_redirects=False,  # no redirects on credential verify
            ) as client:
                resp = await client.get(
                    f"{self.base_url}/orders",
                    auth=self.auth,
                    params={"per_page": 1},
                )
                if resp.status_code == 200:
                    return True
                if resp.status_code == 401:
                    logger.warning(
                        f"WooCommerce auth failed for {self.site_url}: "
                        "Check consumer key/secret and permissions (needs Read)."
                    )
                elif resp.status_code == 404:
                    logger.warning(
                        f"WooCommerce API not found at {self.base_url}. "
                        "Ensure WooCommerce is installed and REST API is enabled."
                    )
                else:
                    logger.warning(
                        f"WooCommerce verify returned HTTP {resp.status_code} "
                        f"for {self.site_url}"
                    )
                return False
        except httpx.ConnectError:
            logger.error(
                f"WooCommerce: cannot connect to {self.site_url}. "
                "Check the site URL is correct and accessible."
            )
            return False
        except httpx.TimeoutException:
            logger.error(
                f"WooCommerce: connection to {self.site_url} timed out. "
                "Site may be slow or unreachable."
            )
            return False
        except httpx.SSLError:
            logger.error(
                f"WooCommerce: SSL error for {self.site_url}. "
                "Ensure the store uses HTTPS with a valid certificate."
            )
            return False
        except Exception:
            logger.error("WooCommerce connection verify failed", exc_info=True)
            return False

    async def fetch_orders(
        self,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch all orders in date range.
        Handles pagination via X-WP-TotalPages header.
        Handles 429 rate limit with backoff.
        Returns normalized records — NO PII.
        """
        if since_dt is None:
            since_dt = datetime.utcnow() - timedelta(days=1)

        params: dict[str, Any] = {
            "status": "any",
            "per_page": PAGE_SIZE,
            "after": since_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "orderby": "date",
            "order": "asc",
        }
        if until_dt:
            params["before"] = until_dt.strftime("%Y-%m-%dT%H:%M:%S")

        orders: list[dict] = []
        page = 1
        total_pages = 1

        async with httpx.AsyncClient(
            timeout=self._timeout,
            verify=True,
            follow_redirects=True,
        ) as client:
            while page <= min(total_pages, MAX_PAGES):
                params["page"] = page
                try:
                    resp = await self._get_with_retry(client, f"{self.base_url}/orders", params)
                except Exception as e:
                    logger.error(
                        f"WooCommerce: failed fetching page {page} from {self.site_url}: {e}"
                    )
                    break

                raw_orders = resp.json()
                if not isinstance(raw_orders, list) or not raw_orders:
                    break

                orders.extend(self._strip_pii(o) for o in raw_orders)

                # Read total pages from WP REST API header
                try:
                    total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
                except (ValueError, TypeError):
                    total_pages = 1

                logger.debug(
                    f"WooCommerce: page {page}/{total_pages}, "
                    f"got {len(raw_orders)} orders, total so far: {len(orders)}"
                )

                if page >= total_pages:
                    break
                page += 1

        logger.info(
            f"WooCommerce: fetched {len(orders)} orders from {self.site_url} "
            f"(since={since_dt.date()})"
        )
        return orders

    async def fetch_refunds(self, order_id: str) -> list[dict[str, Any]]:
        """
        Fetch refunds for a specific order.
        Note: WooCommerce also embeds refund summaries in the order object itself
        (order.refunds[]). This method fetches the full refund detail records.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=True) as client:
                resp = await client.get(
                    f"{self.base_url}/orders/{order_id}/refunds",
                    auth=self.auth,
                )
                resp.raise_for_status()
                refunds = resp.json()
                if not isinstance(refunds, list):
                    return []
                return [self._strip_refund_pii(r, order_id) for r in refunds]
        except httpx.HTTPStatusError as e:
            logger.error(
                f"WooCommerce: HTTP {e.response.status_code} fetching refunds "
                f"for order {order_id}"
            )
            return []
        except Exception:
            logger.error(
                f"WooCommerce: failed to fetch refunds for order {order_id}",
                exc_info=True,
            )
            return []

    async def _get_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict,
        max_retries: int = 3,
    ) -> httpx.Response:
        """
        GET with retry on 429 (rate limit) and transient 5xx errors.
        Raises on persistent failure.
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.get(url, auth=self.auth, params=params)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", RATE_LIMIT_BACKOFF))
                    logger.warning(
                        f"WooCommerce rate limited. Waiting {retry_after}s "
                        f"(attempt {attempt}/{max_retries})"
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if resp.status_code >= 500 and attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        f"WooCommerce HTTP {resp.status_code}. "
                        f"Retrying in {wait}s (attempt {attempt}/{max_retries})"
                    )
                    await asyncio.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp

            except httpx.TimeoutException as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning(
                    f"WooCommerce timeout on attempt {attempt}/{max_retries}. "
                    f"Retrying in {wait}s"
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait)

        raise last_exc or RuntimeError(
            f"WooCommerce: all {max_retries} retry attempts exhausted for {url}"
        )

    def _strip_pii(self, order: dict) -> dict:
        """
        Strip ALL PII from WooCommerce order.
        Return shape identical to ShopifyClient._strip_pii for reconciliation compat.

        Fields intentionally NOT stored: billing, shipping, customer details,
        customer_id, customer_ip_address, customer_user_agent, any meta with PII.
        """
        amount_paise = self._rupees_to_paise(order.get("total", "0"))
        payment_method = order.get("payment_method", "")

        refunds = []
        for ref in order.get("refunds", []):
            refund_amount_paise = self._rupees_to_paise(
                str(ref.get("total", "0")).lstrip("-")
            )
            if refund_amount_paise > 0:
                refunds.append({
                    "refund_id": str(ref.get("id", "")),
                    "order_id": str(order.get("id", "")),
                    "amount_paise": refund_amount_paise,
                    "status": "success",
                    "created_at": order.get("date_modified"),
                })

        return {
            "shopify_order_id": str(order.get("id", "")),  # field name kept for DB compat
            "status": self._map_status(order.get("status", "")),
            "amount_paise": amount_paise,
            "created_at": order.get("date_created"),
            "payment_method": payment_method,
            "refunds": refunds,
            "razorpay_order_id": self._extract_razorpay_id(order),
        }

    def _strip_refund_pii(self, refund: dict, order_id: str) -> dict:
        """Strip PII from standalone refund record."""
        amount_paise = self._rupees_to_paise(
            str(refund.get("total", "0")).lstrip("-")
        )
        return {
            "refund_id": str(refund.get("id", "")),
            "order_id": str(order_id),
            "amount_paise": amount_paise,
            "status": "success",
            "created_at": refund.get("date_created"),
        }

    @staticmethod
    def _map_status(woo_status: str) -> str:
        """
        Map WooCommerce order status → normalized Artha status.
        Normalized vocabulary matches Shopify financial_status for compat.
        """
        return {
            "pending":    "pending",
            "processing": "paid",       # payment received, fulfillment pending
            "on-hold":    "pending",    # awaiting payment confirmation
            "completed":  "paid",       # fully fulfilled and paid
            "cancelled":  "voided",
            "refunded":   "refunded",
            "failed":     "voided",
            "trash":      "voided",
            # Custom statuses used by some stores
            "checkout-draft": "pending",
        }.get(woo_status, woo_status)

    @staticmethod
    def _extract_razorpay_id(order: dict) -> str | None:
        """
        Extract Razorpay payment ID from WooCommerce order.

        Priority:
        1. meta_data with known Razorpay keys (_razorpay_payment_id etc.)
        2. transaction_id field (WooCommerce standard payment ID field)
        3. None — will reconcile as ghost order if Razorpay payment exists
        """
        # 1. Scan meta_data for Razorpay plugin keys
        razorpay_meta_keys = {
            "_razorpay_payment_id",
            "razorpay_payment_id",
            "_razorpay_order_id",
            "razorpay_order_id",
            "_transaction_id",
        }
        for meta in order.get("meta_data", []):
            key = meta.get("key", "")
            val = str(meta.get("value", "") or "").strip()
            if key in razorpay_meta_keys and val.startswith("pay_"):
                return val

        # 2. Standard WooCommerce transaction_id field
        txn_id = str(order.get("transaction_id", "") or "").strip()
        if txn_id.startswith("pay_"):
            return txn_id

        return None

    @staticmethod
    def _rupees_to_paise(value: str | float | int) -> int:
        """
        Convert rupee value → BIGINT paise.
        Handles: string "1500.00", float 1500.0, int 1500, negative strings.
        NEVER returns float — always int.
        """
        try:
            cleaned = str(value).replace(",", "").strip().lstrip("-")
            rupees = float(cleaned)
            return int(round(rupees * 100))
        except (ValueError, TypeError):
            logger.warning(f"WooCommerce: cannot convert to paise: {value!r}")
            return 0
