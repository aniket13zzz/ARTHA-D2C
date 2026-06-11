"""
artha-v2/backend/tally.py
Accounting export engine.
Formats: Tally ERP 9, Zoho Books, QuickBooks.
Rules: async generation, secure signed URL, expiring links.
All amounts: BIGINT paise → converted to rupees for export only.
"""

import logging
import csv
import io
from datetime import datetime, timedelta
from typing import Any

from backend.db import get_db
from backend.config import settings

logger = logging.getLogger(__name__)

EXPORT_URL_TTL_HOURS = 24


class ExportEngine:
    def __init__(self, org_id: str):
        self.org_id = org_id
        self.db = get_db()

    async def generate_export(
        self,
        export_id: str,
        fmt: str,
        date_from: str,
        date_to: str,
    ) -> None:
        """Generate export async. Updates tally_exports record with signed URL."""
        try:
            self.db.table("tally_exports").update({"status": "generating"}).eq(
                "id", export_id
            ).execute()

            # Fetch transactions
            txns = self._fetch_transactions(date_from, date_to)

            # Generate CSV bytes
            if fmt == "tally":
                csv_bytes = self._generate_tally_csv(txns)
                filename = f"artha_tally_{date_from}_{date_to}.csv"
            elif fmt == "zoho":
                csv_bytes = self._generate_zoho_csv(txns)
                filename = f"artha_zoho_{date_from}_{date_to}.csv"
            elif fmt == "quickbooks":
                csv_bytes = self._generate_quickbooks_csv(txns)
                filename = f"artha_qb_{date_from}_{date_to}.csv"
            else:
                raise ValueError(f"Unknown export format: {fmt}")

            # Upload to Supabase Storage and get signed URL
            signed_url = self._upload_and_sign(filename, csv_bytes)
            url_expires = (datetime.utcnow() + timedelta(hours=EXPORT_URL_TTL_HOURS)).isoformat()

            self.db.table("tally_exports").update({
                "status": "ready",
                "record_count": len(txns),
                "signed_url": signed_url,
                "url_expires_at": url_expires,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", export_id).execute()

            logger.info(f"[{self.org_id}] Export {fmt} ready: {len(txns)} records")

        except Exception as e:
            logger.error(f"Export generation failed: {e}", exc_info=True)
            self.db.table("tally_exports").update({
                "status": "failed",
                "error_message": str(e),
            }).eq("id", export_id).execute()

    def _fetch_transactions(self, date_from: str, date_to: str) -> list[dict]:
        result = (
            self.db.table("reconciled_transactions")
            .select(
                "shopify_order_id, transaction_type, recon_status, "
                "shopify_amount_paise, razorpay_payment_id, "
                "razorpay_fee_paise, razorpay_tax_paise, "
                "shopify_created_at, synced_at"
            )
            .eq("org_id", self.org_id)
            .gte("shopify_created_at", date_from)
            .lte("shopify_created_at", date_to)
            .eq("recon_status", "matched")
            .execute()
        )
        return result.data or []

    def _generate_tally_csv(self, txns: list[dict]) -> bytes:
        """
        Tally ERP 9 format.
        Columns: Voucher Type, Date, Ledger Name, Debit, Credit, Reference No
        """
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Voucher Type", "Date", "Ledger Name",
            "Debit", "Credit", "Reference No"
        ])

        for t in txns:
            date = self._format_date_tally(t.get("shopify_created_at", ""))
            amount_rupees = t["shopify_amount_paise"] / 100
            fee_rupees = t.get("razorpay_fee_paise", 0) / 100
            ref = t["shopify_order_id"]
            tx_type = t["transaction_type"]

            if tx_type == "sale":
                # Dr: Bank / Razorpay Ledger
                writer.writerow(["Receipt", date, "Razorpay Clearing Account",
                                  f"{amount_rupees:.2f}", "", ref])
                # Cr: Sales Ledger
                writer.writerow(["Receipt", date, "Sales - D2C",
                                  "", f"{amount_rupees:.2f}", ref])
                # Gateway fee
                if fee_rupees > 0:
                    writer.writerow(["Journal", date, "Payment Gateway Charges",
                                      f"{fee_rupees:.2f}", "", ref])
                    writer.writerow(["Journal", date, "Razorpay Clearing Account",
                                      "", f"{fee_rupees:.2f}", ref])
            elif tx_type in ("refund", "partial_refund"):
                writer.writerow(["Credit Note", date, "Sales Returns",
                                  f"{amount_rupees:.2f}", "", ref])
                writer.writerow(["Credit Note", date, "Razorpay Clearing Account",
                                  "", f"{amount_rupees:.2f}", ref])

        return output.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility

    def _generate_zoho_csv(self, txns: list[dict]) -> bytes:
        """Zoho Books compatible CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Transaction Type", "Reference Number",
            "Amount", "Payment Mode", "Description"
        ])

        for t in txns:
            date = self._format_date_iso(t.get("shopify_created_at", ""))
            amount_rupees = t["shopify_amount_paise"] / 100
            tx_type = "Customer Payment" if t["transaction_type"] == "sale" else "Credit Note"
            writer.writerow([
                date, tx_type, t["shopify_order_id"],
                f"{amount_rupees:.2f}", "Razorpay", f"Shopify Order {t['shopify_order_id']}"
            ])

        return output.getvalue().encode("utf-8-sig")

    def _generate_quickbooks_csv(self, txns: list[dict]) -> bytes:
        """QuickBooks compatible CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date", "Transaction Type", "Num", "Name",
            "Amount", "Account", "Memo"
        ])

        for t in txns:
            date = self._format_date_qb(t.get("shopify_created_at", ""))
            amount_rupees = t["shopify_amount_paise"] / 100
            sign = -1 if t["transaction_type"] in ("refund", "partial_refund") else 1
            writer.writerow([
                date,
                "Sales Receipt" if sign > 0 else "Refund",
                t["shopify_order_id"],
                "D2C Customer",
                f"{sign * amount_rupees:.2f}",
                "Razorpay - Undeposited Funds",
                f"Shopify Order {t['shopify_order_id']}"
            ])

        return output.getvalue().encode("utf-8-sig")

    def _upload_and_sign(self, filename: str, data: bytes) -> str:
        """Upload CSV to Supabase Storage and return signed URL."""
        db = self.db
        path = f"{self.org_id}/exports/{filename}"

        # Upload
        db.storage.from_("artha-exports").upload(
            path,
            data,
            {"content-type": "text/csv", "upsert": "true"},
        )

        # Create signed URL valid for 24h
        signed = db.storage.from_("artha-exports").create_signed_url(
            path, EXPORT_URL_TTL_HOURS * 3600
        )
        return signed.get("signedURL", "")

    @staticmethod
    def _format_date_tally(iso: str) -> str:
        """Convert ISO → DD-MMM-YYYY for Tally."""
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%d-%b-%Y")
        except Exception:
            return datetime.utcnow().strftime("%d-%b-%Y")

    @staticmethod
    def _format_date_iso(iso: str) -> str:
        """YYYY-MM-DD."""
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return datetime.utcnow().strftime("%Y-%m-%d")

    @staticmethod
    def _format_date_qb(iso: str) -> str:
        """MM/DD/YYYY for QuickBooks."""
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%m/%d/%Y")
        except Exception:
            return datetime.utcnow().strftime("%m/%d/%Y")
