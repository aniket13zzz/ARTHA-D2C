"""
artha-v2/backend/reconciliation.py
Core reconciliation engine — platform-agnostic.

Accepts normalized orders from ANY ecom platform (Shopify, WooCommerce, etc.)
via the integrations factory. Platform field stored for audit/reporting.

Detects:
- Ghost Orders (ecom order, no Razorpay payment)
- Variances (amount mismatch)
- Refunds (matched / unmatched)
- Partial Refunds
- Chargebacks
- Refund Traps (ecom refunded, Razorpay still pending/failed)

Rule: ALL amounts BIGINT paise. NO FLOAT.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Tolerance: ₹2 variance (200 paise) — gateway rounding allowed
VARIANCE_TOLERANCE_PAISE = 200


@dataclass
class ReconResult:
    shopify_order_id: str          # order_id from any ecom platform (field name kept for DB compat)
    shopify_status: str
    shopify_amount_paise: int
    razorpay_payment_id: str | None
    razorpay_status: str | None
    razorpay_amount_paise: int | None
    razorpay_fee_paise: int
    razorpay_tax_paise: int
    transaction_type: str
    recon_status: str
    variance_paise: int
    parent_transaction_id: str | None
    shopify_created_at: str | None
    razorpay_settled_at: str | None
    ecom_platform: str = field(default="shopify")   # 'shopify' | 'woocommerce'


class ReconciliationEngine:
    def __init__(
        self,
        ecom_orders: list[dict[str, Any]],
        razorpay_payments: list[dict[str, Any]],
        ecom_platform: str = "shopify",
    ):
        self.ecom_orders = ecom_orders
        self.ecom_platform = ecom_platform

        # Index Razorpay payments by order_id for O(1) lookup
        self.rp_by_order: dict[str, dict] = {}
        self.rp_by_payment_id: dict[str, dict] = {}
        for p in razorpay_payments:
            oid = p.get("order_id")
            pid = p.get("razorpay_payment_id")
            if oid:
                self.rp_by_order[oid] = p
            if pid:
                self.rp_by_payment_id[pid] = p
            # WooCommerce: also index by embedded razorpay payment ID in order meta
            rp_meta_id = p.get("razorpay_order_id")
            if rp_meta_id:
                self.rp_by_order[rp_meta_id] = p

    def run(self) -> list[ReconResult]:
        """Run full reconciliation. Return list of results."""
        results: list[ReconResult] = []

        for order in self.ecom_orders:
            result = self._reconcile_order(order)
            results.append(result)

            # Process refunds embedded in order
            for refund in order.get("refunds", []):
                refund_result = self._reconcile_refund(refund, result)
                if refund_result:
                    results.append(refund_result)

        logger.info(
            f"Reconciliation complete [{self.ecom_platform}]: {len(results)} records, "
            f"ghost={sum(1 for r in results if r.recon_status == 'ghost_order')}, "
            f"variance={sum(1 for r in results if r.recon_status == 'variance')}, "
            f"refund_trap={sum(1 for r in results if r.recon_status == 'refund_trap')}"
        )
        return results

    def _reconcile_order(self, order: dict) -> ReconResult:
        """Reconcile single ecom order against Razorpay."""
        order_id = order["shopify_order_id"]
        order_amount = order["amount_paise"]
        order_status = order["status"]

        # Try match: by order_id first, then by embedded razorpay_order_id (WooCommerce)
        rp = self.rp_by_order.get(order_id)
        if rp is None and order.get("razorpay_order_id"):
            rp = self.rp_by_order.get(order["razorpay_order_id"])
        if rp is None and order.get("razorpay_order_id"):
            rp = self.rp_by_payment_id.get(order["razorpay_order_id"])

        if rp is None:
            # Ghost Order: ecom order exists, no Razorpay record
            if order_status in ("paid", "partially_paid"):
                return ReconResult(
                    shopify_order_id=order_id,
                    shopify_status=order_status,
                    shopify_amount_paise=order_amount,
                    razorpay_payment_id=None,
                    razorpay_status=None,
                    razorpay_amount_paise=None,
                    razorpay_fee_paise=0,
                    razorpay_tax_paise=0,
                    transaction_type="sale",
                    recon_status="ghost_order",
                    variance_paise=order_amount,
                    parent_transaction_id=None,
                    shopify_created_at=order.get("created_at"),
                    razorpay_settled_at=None,
                    ecom_platform=self.ecom_platform,
                )
            else:
                return ReconResult(
                    shopify_order_id=order_id,
                    shopify_status=order_status,
                    shopify_amount_paise=order_amount,
                    razorpay_payment_id=None,
                    razorpay_status=None,
                    razorpay_amount_paise=None,
                    razorpay_fee_paise=0,
                    razorpay_tax_paise=0,
                    transaction_type="sale",
                    recon_status="unmatched",
                    variance_paise=0,
                    parent_transaction_id=None,
                    shopify_created_at=order.get("created_at"),
                    razorpay_settled_at=None,
                    ecom_platform=self.ecom_platform,
                )

        rp_amount = rp["amount_paise"]
        variance = abs(order_amount - rp_amount)
        rp_status = rp.get("status", "")

        if rp_status == "captured":
            recon_status = "matched" if variance <= VARIANCE_TOLERANCE_PAISE else "variance"
        elif rp_status == "chargeback":
            recon_status = "variance"
        else:
            recon_status = "unmatched"

        return ReconResult(
            shopify_order_id=order_id,
            shopify_status=order_status,
            shopify_amount_paise=order_amount,
            razorpay_payment_id=rp.get("razorpay_payment_id"),
            razorpay_status=rp_status,
            razorpay_amount_paise=rp_amount,
            razorpay_fee_paise=rp.get("fee_paise", 0),
            razorpay_tax_paise=rp.get("tax_paise", 0),
            transaction_type="sale",
            recon_status=recon_status,
            variance_paise=variance,
            parent_transaction_id=None,
            shopify_created_at=order.get("created_at"),
            razorpay_settled_at=rp.get("created_at"),
            ecom_platform=self.ecom_platform,
        )

    def _reconcile_refund(
        self,
        shopify_refund: dict,
        parent: ReconResult,
    ) -> ReconResult | None:
        """Detect refund traps and classify refunds."""
        shopify_refund_amount = shopify_refund.get("amount_paise", 0)
        if shopify_refund_amount == 0:
            return None

        shopify_refund_status = shopify_refund.get("status", "")
        parent_payment_id = parent.razorpay_payment_id

        rp_payment = (
            self.rp_by_payment_id.get(parent_payment_id)
            if parent_payment_id
            else None
        )

        # Refund trap: ecom refunded, Razorpay not refunded
        if shopify_refund_status in ("success", "refunded"):
            rp_status = rp_payment.get("status", "") if rp_payment else "not_found"
            if rp_status in ("captured", "authorized", "failed", "not_found", ""):
                return ReconResult(
                    shopify_order_id=parent.shopify_order_id,
                    shopify_status="refund_trap",
                    shopify_amount_paise=shopify_refund_amount,
                    razorpay_payment_id=parent_payment_id,
                    razorpay_status=rp_status,
                    razorpay_amount_paise=None,
                    razorpay_fee_paise=0,
                    razorpay_tax_paise=0,
                    transaction_type="refund",
                    recon_status="refund_trap",
                    variance_paise=shopify_refund_amount,
                    parent_transaction_id=None,
                    shopify_created_at=shopify_refund.get("created_at"),
                    razorpay_settled_at=None,
                    ecom_platform=self.ecom_platform,
                )

        # Normal refund
        parent_amount = parent.shopify_amount_paise
        is_partial = shopify_refund_amount < parent_amount
        tx_type = "partial_refund" if is_partial else "refund"

        return ReconResult(
            shopify_order_id=parent.shopify_order_id,
            shopify_status="refunded",
            shopify_amount_paise=shopify_refund_amount,
            razorpay_payment_id=parent_payment_id,
            razorpay_status=shopify_refund_status,
            razorpay_amount_paise=shopify_refund_amount,
            razorpay_fee_paise=0,
            razorpay_tax_paise=0,
            transaction_type=tx_type,
            recon_status="matched",
            variance_paise=0,
            parent_transaction_id=None,
            shopify_created_at=shopify_refund.get("created_at"),
            razorpay_settled_at=None,
            ecom_platform=self.ecom_platform,
        )
