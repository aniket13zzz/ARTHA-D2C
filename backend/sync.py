"""
artha-v2/backend/sync.py
Sync orchestrator — platform-agnostic.

Handles Shopify + WooCommerce via integrations factory.
Runs full pipeline per org per platform.

Pipeline:
1. Load all active ecom credentials for org
2. For each platform: fetch orders via EcomClient
3. Fetch Razorpay payments
4. Run ReconciliationEngine (platform tagged)
5. Upsert reconciled_transactions with ecom_platform
6. Update monthly_gmv
7. Trigger alerts
8. Log sync result
9. Dead-letter on failure

Rules:
- Every sync creates sync_log
- Failures → dead_letter_queue
- No silent failures
- Retry max 3 times
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Any

from backend.db import get_db
from backend.razorpay import RazorpayClient
from backend.reconciliation import ReconciliationEngine, ReconResult
from backend.alerts import AlertEngine
from backend.integrations.factory import get_ecom_client, get_ecom_creds_from_db

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class SyncOrchestrator:
    def __init__(self, org_id: str):
        self.org_id = org_id
        self.db = get_db()

    async def run(self, since_dt: datetime | None = None) -> dict[str, Any]:
        """Run full sync for org across all connected platforms."""
        sync_log_id = await self._create_sync_log("full_sync")
        try:
            result = await self._execute_sync(since_dt, sync_log_id)
            await self._update_sync_log(sync_log_id, "success", result)
            return result
        except Exception as e:
            logger.error(f"Sync failed for org {self.org_id}: {e}", exc_info=True)
            await self._update_sync_log(sync_log_id, "failed", error=str(e))
            await self._enqueue_dead_letter("full_sync", {"org_id": self.org_id}, str(e))
            raise

    async def _execute_sync(
        self,
        since_dt: datetime | None,
        sync_log_id: str,
    ) -> dict[str, Any]:
        if since_dt is None:
            since_dt = datetime.utcnow() - timedelta(hours=25)  # 1h overlap

        # --- Load ALL platform credentials for org ---
        ecom_creds = get_ecom_creds_from_db(self.db, self.org_id)
        if not ecom_creds:
            raise ValueError("No ecom platform connected")

        # --- Load Razorpay credentials (shared across platforms) ---
        razorpay_cred = self._get_razorpay_creds()
        if not razorpay_cred:
            raise ValueError("Razorpay credentials not found")

        razorpay = RazorpayClient(
            razorpay_cred["encrypted_key_id"],
            razorpay_cred["encrypted_key_secret"],
        )

        # Fetch Razorpay payments once (shared by all platforms)
        logger.info(f"[{self.org_id}] Fetching Razorpay payments since {since_dt}")
        rp_payments = await razorpay.fetch_payments(since_dt=since_dt)

        # --- Run sync per platform ---
        all_results: list[ReconResult] = []
        platform_summaries: list[dict] = []

        for creds in ecom_creds:
            platform = creds["platform"]
            try:
                client = get_ecom_client(platform, creds)
                logger.info(f"[{self.org_id}] Fetching {platform} orders since {since_dt}")
                orders = await client.fetch_orders(since_dt=since_dt)

                engine = ReconciliationEngine(
                    ecom_orders=orders,
                    razorpay_payments=rp_payments,
                    ecom_platform=platform,
                )
                results = engine.run()
                all_results.extend(results)

                platform_summaries.append({
                    "platform": platform,
                    "orders_fetched": len(orders),
                    "records": len(results),
                    "ghost": sum(1 for r in results if r.recon_status == "ghost_order"),
                    "traps": sum(1 for r in results if r.recon_status == "refund_trap"),
                    "variance": sum(1 for r in results if r.recon_status == "variance"),
                })
            except Exception as e:
                logger.error(f"[{self.org_id}] {platform} sync failed: {e}", exc_info=True)
                await self._enqueue_dead_letter(
                    f"{platform}_sync", {"org_id": self.org_id, "platform": platform}, str(e)
                )

        # --- Upsert all transactions ---
        inserted, failed = await self._upsert_transactions(all_results)

        # --- Update GMV ---
        await self._update_monthly_gmv(all_results)

        # --- Trigger Alerts ---
        alert_engine = AlertEngine(self.org_id)
        await alert_engine.process_recon_results(all_results)

        summary = {
            "org_id": self.org_id,
            "since_dt": since_dt.isoformat(),
            "platforms": platform_summaries,
            "razorpay_payments": len(rp_payments),
            "records_total": len(all_results),
            "records_inserted": inserted,
            "records_failed": failed,
            "ghost_orders": sum(1 for r in all_results if r.recon_status == "ghost_order"),
            "variances": sum(1 for r in all_results if r.recon_status == "variance"),
            "refund_traps": sum(1 for r in all_results if r.recon_status == "refund_trap"),
        }

        logger.info(f"[{self.org_id}] Sync summary: {summary}")
        return summary

    async def _upsert_transactions(
        self, results: list[ReconResult]
    ) -> tuple[int, int]:
        """Upsert reconciled transactions with ecom_platform field."""
        inserted = 0
        failed = 0
        db = self.db

        for r in results:
            try:
                record = {
                    "org_id": self.org_id,
                    "shopify_order_id": r.shopify_order_id,
                    "shopify_status": r.shopify_status,
                    "shopify_amount_paise": r.shopify_amount_paise,
                    "shopify_created_at": r.shopify_created_at,
                    "razorpay_payment_id": r.razorpay_payment_id,
                    "razorpay_status": r.razorpay_status,
                    "razorpay_amount_paise": r.razorpay_amount_paise,
                    "razorpay_fee_paise": r.razorpay_fee_paise,
                    "razorpay_tax_paise": r.razorpay_tax_paise,
                    "razorpay_settled_at": r.razorpay_settled_at,
                    "transaction_type": r.transaction_type,
                    "recon_status": r.recon_status,
                    "variance_paise": r.variance_paise,
                    "ecom_platform": r.ecom_platform,
                    "synced_at": datetime.utcnow().isoformat(),
                }
                db.table("reconciled_transactions").upsert(
                    record,
                    on_conflict="org_id,shopify_order_id",
                ).execute()
                inserted += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed to upsert transaction {r.shopify_order_id}: {e}")
                await self._enqueue_dead_letter(
                    "transaction_upsert",
                    {"shopify_order_id": r.shopify_order_id, "platform": r.ecom_platform},
                    str(e),
                )

        return inserted, failed

    async def _update_monthly_gmv(self, results: list[ReconResult]) -> None:
        """Aggregate matched sales into monthly_gmv. Trigger upgrade check."""
        month_year = datetime.utcnow().strftime("%Y-%m")
        total_paise = sum(
            r.shopify_amount_paise
            for r in results
            if r.transaction_type == "sale" and r.recon_status == "matched"
        )
        if total_paise == 0:
            return

        db = self.db
        existing = (
            db.table("monthly_gmv")
            .select("*")
            .eq("org_id", self.org_id)
            .eq("month_year", month_year)
            .maybe_single()
            .execute()
        )

        matched_count = len([
            r for r in results
            if r.transaction_type == "sale" and r.recon_status == "matched"
        ])

        if existing.data:
            db.table("monthly_gmv").update({
                "total_gmv_paise": existing.data["total_gmv_paise"] + total_paise,
                "order_count": existing.data["order_count"] + matched_count,
            }).eq("id", existing.data["id"]).execute()
        else:
            db.table("monthly_gmv").insert({
                "org_id": self.org_id,
                "month_year": month_year,
                "total_gmv_paise": total_paise,
                "order_count": matched_count,
                "plan_at_month": "starter",
            }).execute()

        await self._check_upgrade_trigger(month_year)

    async def _check_upgrade_trigger(self, month_year: str) -> None:
        """Auto-upgrade starter → growth if GMV > ₹10L."""
        STARTER_LIMIT_PAISE = 10_000_000  # ₹10L

        db = self.db
        org = (
            db.table("organizations")
            .select("plan")
            .eq("id", self.org_id)
            .single()
            .execute()
        )
        if not org.data or org.data["plan"] != "starter":
            return

        gmv = (
            db.table("monthly_gmv")
            .select("total_gmv_paise")
            .eq("org_id", self.org_id)
            .eq("month_year", month_year)
            .single()
            .execute()
        )
        if not gmv.data:
            return

        if gmv.data["total_gmv_paise"] >= STARTER_LIMIT_PAISE:
            logger.warning(f"[{self.org_id}] GMV exceeds ₹10L — upgrading to growth")
            db.table("organizations").update({"plan": "growth"}).eq(
                "id", self.org_id
            ).execute()
            alert_engine = AlertEngine(self.org_id)
            await alert_engine.send_upgrade_alert(gmv.data["total_gmv_paise"])

    def _get_razorpay_creds(self) -> dict | None:
        result = (
            self.db.table("razorpay_credentials")
            .select("encrypted_key_id, encrypted_key_secret")
            .eq("org_id", self.org_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        return result.data

    async def _create_sync_log(self, sync_type: str) -> str:
        result = (
            self.db.table("sync_logs")
            .insert({
                "org_id": self.org_id,
                "sync_type": sync_type,
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
            })
            .execute()
        )
        return result.data[0]["id"]

    async def _update_sync_log(
        self,
        sync_log_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        update: dict = {
            "status": status,
            "completed_at": datetime.utcnow().isoformat(),
        }
        if result:
            update["records_fetched"] = result.get("records_total", 0)
            update["records_matched"] = result.get("records_inserted", 0)
            update["records_failed"] = result.get("records_failed", 0)
        if error:
            update["error_message"] = error
        self.db.table("sync_logs").update(update).eq("id", sync_log_id).execute()

    async def _enqueue_dead_letter(
        self, queue_name: str, payload: dict, error: str
    ) -> None:
        self.db.table("dead_letter_queue").insert({
            "org_id": self.org_id,
            "queue_name": queue_name,
            "payload": payload,
            "error_message": error,
            "retry_count": 0,
            "max_retries": MAX_RETRIES,
            "last_attempted": datetime.utcnow().isoformat(),
        }).execute()


async def run_all_orgs_sync() -> dict[str, Any]:
    """Cron entry: sync all active orgs."""
    db = get_db()
    orgs = (
        db.table("organizations")
        .select("id")
        .eq("is_active", True)
        .execute()
    )

    results = []
    errors = []

    for org in orgs.data:
        org_id = org["id"]
        try:
            orchestrator = SyncOrchestrator(org_id)
            result = await orchestrator.run()
            results.append(result)
        except Exception as e:
            logger.error(f"Sync failed for org {org_id}: {e}")
            errors.append({"org_id": org_id, "error": str(e)})

    return {
        "orgs_processed": len(results),
        "orgs_failed": len(errors),
        "errors": errors,
    }
