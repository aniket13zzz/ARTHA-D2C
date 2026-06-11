"""
artha-v2/backend/razorpay.py
Razorpay integration — fetch payments, refunds, settlements.
DATA MINIMIZATION: store only payment_id, amount, status, fee, tax, settled_at.
NO PII stored.
"""

import logging
import httpx
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Any
from backend.crypto import decrypt

logger = logging.getLogger(__name__)

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"
PAGE_COUNT = 100


class RazorpayClient:
    def __init__(self, encrypted_key_id: str, encrypted_key_secret: str):
        self.key_id = decrypt(encrypted_key_id)
        self.key_secret = decrypt(encrypted_key_secret)
        self.auth = (self.key_id, self.key_secret)

    async def verify_connection(self) -> bool:
        """Verify Razorpay credentials. Returns False on auth failure or network error."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=8.0, read=10.0, write=5.0, pool=5.0)
            ) as client:
                resp = await client.get(
                    f"{RAZORPAY_BASE_URL}/payments",
                    auth=self.auth,
                    params={"count": 1},
                )
                if resp.status_code == 200:
                    return True
                if resp.status_code == 401:
                    logger.warning("Razorpay auth failed: invalid key_id or key_secret")
                else:
                    logger.warning(f"Razorpay verify returned HTTP {resp.status_code}")
                return False
        except httpx.TimeoutException:
            logger.error("Razorpay connection timed out during verify")
            return False
        except Exception:
            logger.error("Razorpay connection verify failed", exc_info=True)
            return False

    async def fetch_payments(
        self,
        since_dt: datetime | None = None,
        until_dt: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch payments. Returns stripped records — NO PII."""
        if since_dt is None:
            since_dt = datetime.utcnow() - timedelta(days=1)

        from_ts = int(since_dt.timestamp())
        to_ts = int((until_dt or datetime.utcnow()).timestamp())

        payments: list[dict] = []
        skip = 0

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                resp = await client.get(
                    f"{RAZORPAY_BASE_URL}/payments",
                    auth=self.auth,
                    params={
                        "count": PAGE_COUNT,
                        "skip": skip,
                        "from": from_ts,
                        "to": to_ts,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                if not items:
                    break
                payments.extend(self._strip_payment_pii(p) for p in items)
                skip += PAGE_COUNT
                if len(items) < PAGE_COUNT:
                    break

        logger.info(f"Razorpay: fetched {len(payments)} payments")
        return payments

    async def fetch_refunds(self, payment_id: str) -> list[dict[str, Any]]:
        """Fetch refunds for a payment."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{RAZORPAY_BASE_URL}/payments/{payment_id}/refunds",
                    auth=self.auth,
                )
                resp.raise_for_status()
                items = resp.json().get("items", [])
                return [self._strip_refund_pii(r) for r in items]
        except Exception:
            logger.error(f"Failed to fetch refunds for {payment_id}", exc_info=True)
            return []

    async def create_payment_link(
        self,
        amount_paise: int,
        description: str,
        org_id: str,
    ) -> str | None:
        """Create Razorpay Payment Link for billing. Returns URL."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{RAZORPAY_BASE_URL}/payment_links",
                    auth=self.auth,
                    json={
                        "amount": amount_paise,
                        "currency": "INR",
                        "description": description,
                        "notes": {"org_id": org_id},
                    },
                )
                resp.raise_for_status()
                return resp.json().get("short_url")
        except Exception:
            logger.error("Failed to create payment link", exc_info=True)
            return None

    def verify_webhook_signature(
        self, payload: bytes, signature: str, webhook_secret: str
    ) -> bool:
        """Verify Razorpay webhook HMAC-SHA256 signature."""
        expected = hmac.new(
            key=webhook_secret.encode(),
            msg=payload,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def _strip_payment_pii(self, payment: dict) -> dict:
        """Strip PII from payment record."""
        return {
            "razorpay_payment_id": payment.get("id", ""),
            "status": payment.get("status", ""),
            # Razorpay already returns amounts in paise
            "amount_paise": int(payment.get("amount", 0)),
            "fee_paise": int(payment.get("fee", 0)),
            "tax_paise": int(payment.get("tax", 0)),
            "order_id": payment.get("order_id"),
            "created_at": datetime.fromtimestamp(
                payment.get("created_at", 0)
            ).isoformat(),
        }

    def _strip_refund_pii(self, refund: dict) -> dict:
        """Strip PII from refund record."""
        return {
            "refund_id": refund.get("id", ""),
            "payment_id": refund.get("payment_id", ""),
            "amount_paise": int(refund.get("amount", 0)),
            "status": refund.get("status", ""),
            "created_at": datetime.fromtimestamp(
                refund.get("created_at", 0)
            ).isoformat(),
        }
