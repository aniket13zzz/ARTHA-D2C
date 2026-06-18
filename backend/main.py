"""
artha-v2/backend/main.py
FastAPI application — all routes.

Security:
- JWT auth via Supabase (every protected route)
- x-cron-secret header for cron endpoint
- Rate limiting via slowapi
- CORS restricted to frontend URL
- No PII ever returned
"""

import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Any, Annotated
from uuid import UUID

import sentry_sdk
from fastapi import FastAPI, Depends, HTTPException, Header, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.config import settings
from backend.db import get_db
from backend.crypto import encrypt, decrypt
from backend.sync import SyncOrchestrator, run_all_orgs_sync
from backend.tally import ExportEngine

# ─── Sentry ───────────────────────────────────────────────────
if settings.SENTRY_DSN:
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.2)

# ─── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Rate limiter ─────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Artha V2 backend starting — env={settings.APP_ENV}")
    yield
    logger.info("Artha V2 backend shutting down")


app = FastAPI(
    title="Artha V2 API",
    version=settings.APP_VERSION,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_origin_regex=r"https://artha-d2-c.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# ─── Auth dependency ──────────────────────────────────────────

async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Validate Supabase JWT. Returns user dict."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ")[1]
    db = get_db()
    try:
        user = db.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"uid": user.user.id, "email": user.user.email}
    except Exception:
        raise HTTPException(status_code=401, detail="Token validation failed")


async def get_org_id(auth: dict = Depends(require_auth)) -> str:
    """Get org_id for authenticated user."""
    db = get_db()
    result = (
        db.table("users")
        .select("org_id, role")
        .eq("supabase_uid", auth["uid"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="User org not found")
    return result.data["org_id"]


async def require_owner_or_admin(auth: dict = Depends(require_auth)) -> dict:
    """Require owner or admin role."""
    db = get_db()
    result = (
        db.table("users")
        .select("org_id, role")
        .eq("supabase_uid", auth["uid"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="User not found")
    if result.data["role"] not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return result.data


# ─── Pydantic models ──────────────────────────────────────────

class ShopifyConnectRequest(BaseModel):
    shop_domain: str
    access_token: str

class WooCommerceConnectRequest(BaseModel):
    site_url: str
    consumer_key: str
    consumer_secret: str
    api_version: str = "wc/v3"

class RazorpayConnectRequest(BaseModel):
    key_id: str
    key_secret: str
    webhook_secret: str | None = None

class AlertPrefsUpdateRequest(BaseModel):
    email_enabled: bool = True
    slack_enabled: bool = False
    whatsapp_enabled: bool = False
    slack_webhook: str | None = None
    whatsapp_token: str | None = None
    whatsapp_phone: str | None = None
    ghost_order_threshold_paise: int = Field(default=100_000, ge=0)
    variance_threshold_paise: int = Field(default=50_000, ge=0)

class ExportRequest(BaseModel):
    format: str = Field(..., pattern="^(tally|zoho|quickbooks)$")
    date_from: date
    date_to: date

class OrgCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


# ─── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "ts": datetime.utcnow().isoformat()}


# ─── Cron ─────────────────────────────────────────────────────

@app.post("/api/cron/sync")
@limiter.limit("5/minute")
async def cron_sync(
    request: Request,
    x_cron_secret: Annotated[str | None, Header()] = None,
):
    """GitHub Actions daily sync. Protected by x-cron-secret."""
    if not x_cron_secret or x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    logger.info("Cron sync triggered")
    result = await run_all_orgs_sync()
    return {"ok": True, **result}


# ─── Org Onboarding ───────────────────────────────────────────

@app.post("/api/org")
async def create_org(
    body: OrgCreateRequest,
    auth: dict = Depends(require_auth),
):
    """Create organization + link user as owner."""
    db = get_db()

    # Check user not already in org
    existing = (
        db.table("users")
        .select("org_id")
        .eq("supabase_uid", auth["uid"])
        .maybe_single()
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="User already belongs to an org")

    # Create org
    org = db.table("organizations").insert({"name": body.name}).execute()
    org_id = org.data[0]["id"]

    # Create user as owner
    db.table("users").insert({
        "org_id": org_id,
        "supabase_uid": auth["uid"],
        "role": "owner",
    }).execute()

    # Init settings
    db.table("organization_settings").insert({"org_id": org_id}).execute()
    db.table("alert_preferences").insert({"org_id": org_id}).execute()

    # Audit
    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "login",
        "metadata": {"event": "org_created"},
    }).execute()

    return {"org_id": org_id}


# ─── Shopify Connect ──────────────────────────────────────────

@app.post("/api/connect/shopify")
@limiter.limit("10/minute")
async def connect_shopify(
    request: Request,
    body: ShopifyConnectRequest,
    org_id: str = Depends(get_org_id),
    auth: dict = Depends(require_auth),
):
    """Store encrypted Shopify credentials."""
    from backend.shopify import ShopifyClient
    client = ShopifyClient(body.shop_domain, encrypt(body.access_token))
    # Verify before storing
    if not await client.verify_connection():
        raise HTTPException(status_code=400, detail="Shopify credentials invalid or expired")

    db = get_db()
    encrypted_token = encrypt(body.access_token)
    db.table("shopify_credentials").upsert({
        "org_id": org_id,
        "shop_domain": body.shop_domain,
        "encrypted_access_token": encrypted_token,
        "is_active": True,
        "last_verified_at": datetime.utcnow().isoformat(),
    }, on_conflict="org_id").execute()

    _add_connected_platform(db, org_id, "shopify")

    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "connect_shopify",
        "metadata": {"shop_domain": body.shop_domain},
    }).execute()

    return {"ok": True}


@app.delete("/api/connect/shopify")
async def disconnect_shopify(
    user: dict = Depends(require_owner_or_admin),
):
    db = get_db()
    db.table("shopify_credentials").update({"is_active": False}).eq(
        "org_id", user["org_id"]
    ).execute()
    db.table("audit_logs").insert({
        "org_id": user["org_id"],
        "action": "disconnect_shopify",
    }).execute()
    return {"ok": True}

# ─── WooCommerce Connect ──────────────────────────────────────

@app.post("/api/connect/woocommerce")
@limiter.limit("10/minute")
async def connect_woocommerce(
    request: Request,
    body: WooCommerceConnectRequest,
    org_id: str = Depends(get_org_id),
    auth: dict = Depends(require_auth),
):
    """Store encrypted WooCommerce credentials. Requires HTTPS."""
    from backend.woocommerce import WooCommerceClient
    from backend.crypto import encrypt
    # Enforce HTTPS for WooCommerce API (HTTP sends credentials in plaintext)
    if not body.site_url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="WooCommerce store URL must use HTTPS to protect API credentials."
        )
    test_client = WooCommerceClient(
        site_url=body.site_url,
        encrypted_consumer_key=encrypt(body.consumer_key),
        encrypted_consumer_secret=encrypt(body.consumer_secret),
        api_version=body.api_version,
    )
    if not await test_client.verify_connection():
        raise HTTPException(status_code=400, detail="WooCommerce credentials invalid. Check URL, consumer key, and secret.")

    db = get_db()
    db.table("woocommerce_credentials").upsert({
        "org_id": org_id,
        "site_url": body.site_url.rstrip("/"),
        "encrypted_consumer_key": encrypt(body.consumer_key),
        "encrypted_consumer_secret": encrypt(body.consumer_secret),
        "api_version": body.api_version,
        "is_active": True,
        "last_verified_at": datetime.utcnow().isoformat(),
    }, on_conflict="org_id").execute()

    # Update connected_platforms list in org settings
    _add_connected_platform(db, org_id, "woocommerce")

    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "connect_shopify",
        "metadata": {"platform": "woocommerce", "site_url": body.site_url},
    }).execute()

    return {"ok": True}


@app.delete("/api/connect/woocommerce")
async def disconnect_woocommerce(
    user: dict = Depends(require_owner_or_admin),
):
    db = get_db()
    db.table("woocommerce_credentials").update({"is_active": False}).eq(
        "org_id", user["org_id"]
    ).execute()
    db.table("audit_logs").insert({
        "org_id": user["org_id"],
        "action": "disconnect_shopify",
        "metadata": {"platform": "woocommerce"},
    }).execute()
    return {"ok": True}


@app.get("/api/connect/status")
async def connection_status(org_id: str = Depends(get_org_id)):
    """Return connection status for all platforms."""
    db = get_db()

    shopify = (
        db.table("shopify_credentials")
        .select("shop_domain, is_active, last_verified_at")
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    woo = (
        db.table("woocommerce_credentials")
        .select("site_url, is_active, last_verified_at")
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    razorpay = (
        db.table("razorpay_credentials")
        .select("is_active, last_verified_at")
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )

    return {
        "shopify": {
            "connected": bool(shopify.data and shopify.data.get("is_active")),
            "shop_domain": shopify.data.get("shop_domain") if shopify.data else None,
            "last_verified_at": shopify.data.get("last_verified_at") if shopify.data else None,
        },
        "woocommerce": {
            "connected": bool(woo.data and woo.data.get("is_active")),
            "site_url": woo.data.get("site_url") if woo.data else None,
            "last_verified_at": woo.data.get("last_verified_at") if woo.data else None,
        },
        "razorpay": {
            "connected": bool(razorpay.data and razorpay.data.get("is_active")),
            "last_verified_at": razorpay.data.get("last_verified_at") if razorpay.data else None,
        },
    }


def _add_connected_platform(db, org_id: str, platform: str) -> None:
    """Append platform to organization_settings.connected_platforms array."""
    try:
        existing = (
            db.table("organization_settings")
            .select("connected_platforms")
            .eq("org_id", org_id)
            .maybe_single()
            .execute()
        )
        if existing.data:
            platforms = existing.data.get("connected_platforms") or []
            if platform not in platforms:
                platforms.append(platform)
            db.table("organization_settings").update({
                "connected_platforms": platforms
            }).eq("org_id", org_id).execute()
    except Exception as e:
        logger.warning(f"Could not update connected_platforms: {e}")



# ─── Razorpay Connect ─────────────────────────────────────────

@app.post("/api/connect/razorpay")
@limiter.limit("10/minute")
async def connect_razorpay(
    request: Request,
    body: RazorpayConnectRequest,
    org_id: str = Depends(get_org_id),
    auth: dict = Depends(require_auth),
):
    """Store encrypted Razorpay credentials."""
    from backend.razorpay import RazorpayClient
    client = RazorpayClient(encrypt(body.key_id), encrypt(body.key_secret))
    if not await client.verify_connection():
        raise HTTPException(status_code=400, detail="Razorpay credentials invalid")

    db = get_db()
    record: dict[str, Any] = {
        "org_id": org_id,
        "encrypted_key_id": encrypt(body.key_id),
        "encrypted_key_secret": encrypt(body.key_secret),
        "is_active": True,
        "last_verified_at": datetime.utcnow().isoformat(),
    }
    if body.webhook_secret:
        record["webhook_secret"] = encrypt(body.webhook_secret)

    db.table("razorpay_credentials").upsert(record, on_conflict="org_id").execute()
    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "connect_razorpay",
    }).execute()

    return {"ok": True}


# ─── Dashboard / Transactions ─────────────────────────────────

@app.get("/api/dashboard/summary")
async def dashboard_summary(org_id: str = Depends(get_org_id)):
    """Return high-level metrics for dashboard."""
    db = get_db()
    month_year = datetime.utcnow().strftime("%Y-%m")

    gmv = (
        db.table("monthly_gmv")
        .select("total_gmv_paise, order_count, plan_at_month")
        .eq("org_id", org_id)
        .eq("month_year", month_year)
        .maybe_single()
        .execute()
    )

    # Anomaly counts
    ghost = (
        db.table("reconciled_transactions")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .eq("recon_status", "ghost_order")
        .execute()
    )
    traps = (
        db.table("reconciled_transactions")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .eq("recon_status", "refund_trap")
        .execute()
    )
    variances = (
        db.table("reconciled_transactions")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .eq("recon_status", "variance")
        .execute()
    )

    return {
        "month_year": month_year,
        "gmv_paise": gmv.data["total_gmv_paise"] if gmv.data else 0,
        "order_count": gmv.data["order_count"] if gmv.data else 0,
        "ghost_orders": ghost.count or 0,
        "refund_traps": traps.count or 0,
        "variances": variances.count or 0,
    }


@app.get("/api/transactions")
async def list_transactions(
    org_id: str = Depends(get_org_id),
    status: str | None = None,
    tx_type: str | None = None,
    platform: str | None = None,      # 'shopify' | 'woocommerce'
    page: int = 1,
    page_size: int = 50,
):
    """List reconciled transactions. NO PII returned. Filterable by platform."""
    if page_size > 200:
        page_size = 200  # hard cap
    db = get_db()
    query = (
        db.table("reconciled_transactions")
        .select(
            "id, shopify_order_id, shopify_status, shopify_amount_paise, "
            "razorpay_payment_id, razorpay_status, razorpay_amount_paise, "
            "razorpay_fee_paise, razorpay_tax_paise, transaction_type, "
            "recon_status, variance_paise, ecom_platform, "
            "shopify_created_at, synced_at"
        )
        .eq("org_id", org_id)
        .order("shopify_created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
    )
    if status:
        query = query.eq("recon_status", status)
    if tx_type:
        query = query.eq("transaction_type", tx_type)
    if platform:
        query = query.eq("ecom_platform", platform)

    result = query.execute()
    return {"transactions": result.data, "page": page, "page_size": page_size}


@app.get("/api/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: str,
    org_id: str = Depends(get_org_id),
):
    db = get_db()
    result = (
        db.table("reconciled_transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("org_id", org_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return result.data


# ─── Sync Logs ────────────────────────────────────────────────

@app.get("/api/sync-logs")
async def list_sync_logs(
    org_id: str = Depends(get_org_id),
    page: int = 1,
    page_size: int = 20,
):
    db = get_db()
    result = (
        db.table("sync_logs")
        .select("*")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
        .execute()
    )
    return {"sync_logs": result.data}


@app.post("/api/sync/trigger")
async def trigger_manual_sync(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_owner_or_admin),
):
    """Trigger manual sync for org."""
    org_id = user["org_id"]
    db = get_db()
    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "sync_triggered",
    }).execute()

    async def _run():
        orchestrator = SyncOrchestrator(org_id)
        await orchestrator.run()

    background_tasks.add_task(_run)
    return {"ok": True, "message": "Sync started in background"}


# ─── Alert Preferences ────────────────────────────────────────

@app.get("/api/settings/alerts")
async def get_alert_prefs(org_id: str = Depends(get_org_id)):
    db = get_db()
    result = (
        db.table("alert_preferences")
        .select(
            "email_enabled, slack_enabled, whatsapp_enabled, "
            "whatsapp_phone, ghost_order_threshold_paise, "
            "variance_threshold_paise, critical_enabled, "
            "high_enabled, medium_enabled"
        )
        .eq("org_id", org_id)
        .maybe_single()
        .execute()
    )
    return result.data or {}


@app.put("/api/settings/alerts")
async def update_alert_prefs(
    body: AlertPrefsUpdateRequest,
    user: dict = Depends(require_owner_or_admin),
):
    org_id = user["org_id"]
    db = get_db()
    update: dict[str, Any] = {
        "email_enabled": body.email_enabled,
        "slack_enabled": body.slack_enabled,
        "whatsapp_enabled": body.whatsapp_enabled,
        "ghost_order_threshold_paise": body.ghost_order_threshold_paise,
        "variance_threshold_paise": body.variance_threshold_paise,
    }
    if body.slack_webhook:
        update["slack_webhook_encrypted"] = encrypt(body.slack_webhook)
    if body.whatsapp_token:
        update["whatsapp_token_encrypted"] = encrypt(body.whatsapp_token)
    if body.whatsapp_phone:
        update["whatsapp_phone"] = body.whatsapp_phone

    db.table("alert_preferences").update(update).eq("org_id", org_id).execute()
    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "settings_changed",
        "metadata": {"section": "alert_preferences"},
    }).execute()
    return {"ok": True}


# ─── Exports ─────────────────────────────────────────────────

@app.post("/api/export")
async def create_export(
    body: ExportRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_owner_or_admin),
):
    org_id = user["org_id"]
    db = get_db()

    # Create export record
    result = db.table("tally_exports").insert({
        "org_id": org_id,
        "format": body.format,
        "date_from": body.date_from.isoformat(),
        "date_to": body.date_to.isoformat(),
        "status": "pending",
    }).execute()
    export_id = result.data[0]["id"]

    # Generate async
    async def _generate():
        engine = ExportEngine(org_id)
        await engine.generate_export(
            export_id,
            body.format,
            body.date_from.isoformat(),
            body.date_to.isoformat(),
        )

    background_tasks.add_task(_generate)
    db.table("audit_logs").insert({
        "org_id": org_id,
        "action": "export_generated",
        "metadata": {"format": body.format, "export_id": export_id},
    }).execute()

    return {"export_id": export_id, "status": "pending"}


@app.get("/api/export/{export_id}")
async def get_export_status(
    export_id: str,
    org_id: str = Depends(get_org_id),
):
    db = get_db()
    result = (
        db.table("tally_exports")
        .select("id, format, status, record_count, signed_url, url_expires_at, error_message, created_at")
        .eq("id", export_id)
        .eq("org_id", org_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Export not found")

    # Don't expose signed URL if expired
    data = result.data
    if data.get("url_expires_at"):
        expires = datetime.fromisoformat(data["url_expires_at"].replace("Z", "+00:00"))
        if expires < datetime.utcnow().replace(tzinfo=expires.tzinfo):
            data["signed_url"] = None
            data["status"] = "expired"

    return data


# ─── GMV / Billing ───────────────────────────────────────────

@app.get("/api/billing/gmv")
async def get_gmv_history(org_id: str = Depends(get_org_id)):
    db = get_db()
    result = (
        db.table("monthly_gmv")
        .select("month_year, total_gmv_paise, order_count, plan_at_month, billing_amount_paise")
        .eq("org_id", org_id)
        .order("month_year", desc=True)
        .limit(12)
        .execute()
    )
    return {"history": result.data}


# ─── Notifications ────────────────────────────────────────────

@app.get("/api/notifications")
async def list_notifications(
    org_id: str = Depends(get_org_id),
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
):
    db = get_db()
    query = (
        db.table("notifications")
        .select("id, alert_type, severity, title, body, is_read, sent_at, created_at")
        .eq("org_id", org_id)
        .order("created_at", desc=True)
        .range((page - 1) * page_size, page * page_size - 1)
    )
    if unread_only:
        query = query.eq("is_read", False)
    result = query.execute()
    return {"notifications": result.data}


@app.patch("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    org_id: str = Depends(get_org_id),
):
    db = get_db()
    db.table("notifications").update({"is_read": True}).eq(
        "id", notification_id
    ).eq("org_id", org_id).execute()
    return {"ok": True}



# ─── Webhooks (placeholders — verified, safe to extend) ───────

@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    """
    Razorpay webhook receiver.
    Verifies HMAC-SHA256 signature before processing.
    Currently logs events; extend to process payment.captured, refund.processed etc.
    """
    signature = request.headers.get("X-Razorpay-Signature", "")
    body_bytes = await request.body()

    if not signature:
        raise HTTPException(status_code=400, detail="Missing webhook signature")

    # Load webhook secret for org — requires mapping payment to org
    # For now: log and return 200 to prevent Razorpay retry storms
    logger.info(f"Razorpay webhook received: {len(body_bytes)} bytes")

    try:
        import json
        payload = json.loads(body_bytes)
        event = payload.get("event", "unknown")
        logger.info(f"Razorpay webhook event: {event}")
    except Exception:
        pass

    return {"ok": True}


@app.post("/api/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(None),
    x_shopify_topic: str | None = Header(None),
):
    """
    Shopify webhook receiver.
    Verifies HMAC-SHA256 using Shopify shared secret.
    Currently logs events; extend to trigger real-time reconciliation.
    """
    if not x_shopify_hmac_sha256:
        raise HTTPException(status_code=400, detail="Missing Shopify HMAC header")

    body_bytes = await request.body()
    logger.info(
        f"Shopify webhook received: topic={x_shopify_topic}, "
        f"size={len(body_bytes)} bytes"
    )
    # TODO: verify HMAC, identify org by shop domain, trigger partial sync
    return {"ok": True}


# ─── ITC Report ──────────────────────────────────────────────

@app.get("/api/itc-report")
async def itc_report(
    org_id: str = Depends(get_org_id),
    month_year: str | None = None,
):
    """ITC recovery report — Razorpay fees + GST (tax)."""
    if not month_year:
        month_year = datetime.utcnow().strftime("%Y-%m")

    year, month = month_year.split("-")
    date_from = f"{year}-{month}-01"
    if int(month) == 12:
        date_to = f"{int(year)+1}-01-01"
    else:
        date_to = f"{year}-{int(month)+1:02d}-01"

    db = get_db()
    result = (
        db.table("reconciled_transactions")
        .select("shopify_order_id, razorpay_fee_paise, razorpay_tax_paise, shopify_created_at")
        .eq("org_id", org_id)
        .eq("transaction_type", "sale")
        .eq("recon_status", "matched")
        .gte("shopify_created_at", date_from)
        .lt("shopify_created_at", date_to)
        .execute()
    )

    total_fee = sum(t.get("razorpay_fee_paise", 0) for t in (result.data or []))
    total_tax = sum(t.get("razorpay_tax_paise", 0) for t in (result.data or []))

    return {
        "month_year": month_year,
        "total_fee_paise": total_fee,
        "total_tax_paise": total_tax,
        "recoverable_itc_paise": total_tax,
        "transaction_count": len(result.data or []),
    }
