# Artha V2 — Financial Reconciliation Engine

> **Detect hidden profit leakage before it becomes permanent loss.**

Automated Shopify × WooCommerce × Razorpay reconciliation engine for Indian D2C brands doing ₹50L–₹5Cr/month GMV.

---

## Supported Platforms

| Store Platform | Auth Method | Status |
|----------------|------------|--------|
| **Shopify** | Admin API Token (`shpat_...`) | ✅ Production |
| **WooCommerce** | Consumer Key + Secret (`ck_` / `cs_`) | ✅ Production |
| Magento | — | Planned |
| Custom | REST API | Planned |

| Payment Gateway | |
|---|---|
| **Razorpay** | ✅ Production (all plans) |

---

## Architecture

```
[D2C Founder]
      │
      ▼
Magic Link Auth (Supabase)
      │
      ▼
Next.js 14 Frontend (Vercel)
      │  HTTPS/JSON  │
      ▼              ▼
FastAPI Backend (Render)
      │
      ├── integrations/factory.py  ← Platform factory
      │     ├── shopify.py         ← Shopify REST client
      │     └── woocommerce.py     ← WooCommerce REST client
      │
      ├── razorpay.py              ← Payment data
      ├── reconciliation.py        ← Platform-agnostic engine
      ├── sync.py                  ← Orchestrator (multi-platform)
      ├── alerts.py                ← Email + Slack + WhatsApp
      ├── tally.py                 ← Export engine
      └── crypto.py                ← Fernet encryption
            │
            ▼
    Supabase PostgreSQL
    (AWS Mumbai ap-south-1)
    ├── RLS (tenant isolation)
    ├── reconciled_transactions (ecom_platform field)
    ├── shopify_credentials
    ├── woocommerce_credentials     ← NEW
    ├── woocommerce_credentials     ← NEW
    └── 11 other tables

GitHub Actions → /api/cron/sync → 2 AM IST nightly
```

---

## Project Structure

```
artha-v2/
├── database/
│   ├── schema.sql                   # Full schema — run first
│   └── migration_woocommerce.sql    # Run after schema.sql
│
├── backend/
│   ├── main.py                      # FastAPI — all routes
│   ├── sync.py                      # Sync orchestrator (multi-platform)
│   ├── reconciliation.py            # Platform-agnostic engine
│   ├── shopify.py                   # Shopify REST client
│   ├── woocommerce.py               # WooCommerce REST client
│   ├── razorpay.py                  # Razorpay client
│   ├── alerts.py                    # Multi-channel alerts
│   ├── tally.py                     # Export engine
│   ├── crypto.py                    # Fernet encrypt/decrypt
│   ├── config.py                    # Pydantic settings
│   ├── db.py                        # Supabase client
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── factory.py               # Platform factory pattern
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── login/                   # Magic link
│   │   ├── connect/                 # Platform picker + onboarding
│   │   ├── dashboard/               # Main view (platform filter tabs)
│   │   │   └── transactions/[id]/   # Transaction detail
│   │   └── settings/
│   │       └── billing/             # GMV, ITC, exports
│   ├── components/dashboard/
│   │   ├── TransactionTable.tsx     # Platform-aware table
│   │   ├── SyncLogsList.tsx
│   │   └── NotificationBell.tsx
│   └── lib/
│       ├── api.ts                   # Typed API client
│       └── supabase.ts
│
└── .github/workflows/
    └── daily-sync.yml               # 2 AM IST cron
```

---

## Security Rules

| Rule | Implementation |
|------|---------------|
| Money: BIGINT paise only | No FLOAT/DOUBLE anywhere |
| No PII stored | Only order_id, amount, status, created_at |
| Encrypted secrets | Fernet AES-256 for all API keys |
| Tenant isolation | PostgreSQL RLS on every table |
| Audit logs | Append-only (no UPDATE/DELETE) |
| Data retention | 24 months → anonymize/delete |
| RTBF | Full org deletion within 24h |
| CA role | Read-only, no credentials/billing access |

---

## Local Development

```bash
# 1. Backend
cd backend
cp .env.example .env
# Fill in all values — see .env.example for instructions

# Generate Fernet key:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000

# 2. Frontend
cd frontend
cp .env.example .env.local
# Fill in NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_URL

npm install
npm run dev
```

---

## Database Setup

```sql
-- 1. Run in Supabase SQL Editor:
-- Paste contents of database/schema.sql → Run

-- 2. Then run migration:
-- Paste contents of database/migration_woocommerce.sql → Run
```

---

## WooCommerce Setup

### Requirements
- WordPress 5.8+ with WooCommerce 7.0+
- Store must use **HTTPS** (required — HTTP sends credentials in plaintext)
- **Razorpay WooCommerce plugin** installed for payment ID matching

### Generate API Keys
1. WordPress Admin → WooCommerce → Settings → Advanced → REST API
2. **Add key** → Description: `Artha Sync`
3. User: your admin user
4. Permissions: **Read** (never Write)
5. Click **Generate API key** — copy immediately (shown once)

### Razorpay Payment ID Matching
Artha extracts Razorpay payment IDs from WooCommerce order meta:
- `_razorpay_payment_id` (Razorpay official plugin)
- `razorpay_payment_id`
- `_transaction_id`
- `transaction_id` field (WooCommerce standard)

Orders without a matching Razorpay payment ID will be classified as `ghost_order` if their status is `paid`/`processing`/`completed`.

---

## API Reference

| Method | Path | Auth | Role |
|--------|------|------|------|
| GET | `/health` | None | — |
| POST | `/api/cron/sync` | x-cron-secret | — |
| POST | `/api/org` | JWT | any |
| POST | `/api/connect/shopify` | JWT | owner/admin |
| DELETE | `/api/connect/shopify` | JWT | owner/admin |
| POST | `/api/connect/woocommerce` | JWT | owner/admin |
| DELETE | `/api/connect/woocommerce` | JWT | owner/admin |
| GET | `/api/connect/status` | JWT | any |
| POST | `/api/connect/razorpay` | JWT | owner/admin |
| GET | `/api/dashboard/summary` | JWT | any |
| GET | `/api/transactions` | JWT | any |
| GET | `/api/transactions/:id` | JWT | any |
| POST | `/api/sync/trigger` | JWT | owner/admin |
| GET | `/api/sync-logs` | JWT | any |
| GET/PUT | `/api/settings/alerts` | JWT | owner/admin |
| GET | `/api/notifications` | JWT | any |
| POST | `/api/export` | JWT | owner/admin |
| GET | `/api/export/:id` | JWT | any |
| GET | `/api/billing/gmv` | JWT | any |
| GET | `/api/itc-report` | JWT | any |
| POST | `/api/webhooks/razorpay` | HMAC | — |
| POST | `/api/webhooks/shopify` | HMAC | — |

---

## Reconciliation Logic

| Status | Meaning |
|--------|---------|
| `matched` | Store + Razorpay agree (±₹2 tolerance) |
| `ghost_order` | Store shows paid, no Razorpay payment |
| `variance` | Amount mismatch > ₹2 |
| `refund_trap` | Store refunded, Razorpay still captured |
| `unmatched` | No Razorpay record, order not in paid status |

---

## Pricing

| Plan | Price | GMV Cap |
|------|-------|---------|
| Starter | Free | ₹10L/month |
| Growth | 0.5% GMV (min ₹5k, max ₹50k) | None |
| Enterprise | 0.25–0.5% custom | None |

Auto-upgrade: Starter → Growth triggers when monthly GMV crosses ₹10L.

---

## Render Deployment

```yaml
# render.yaml — already configured
Build: pip install -r backend/requirements.txt
Start: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
Root Directory: (blank — NOT "backend")
```

Required env vars on Render: see `backend/.env.example`

---

## Testing Checklist

### Shopify
- [ ] Connect Shopify test store → verify "Connected"
- [ ] Create test order in Shopify → mark as paid
- [ ] Trigger manual sync → check sync log shows `success`
- [ ] Verify transaction appears as `matched` on dashboard
- [ ] Create refund in Shopify only → verify `refund_trap` detected
- [ ] Check alert received (email/Slack)

### WooCommerce
- [ ] Connect WooCommerce store with `ck_` + `cs_` keys
- [ ] Ensure store uses HTTPS (HTTP rejected)
- [ ] Create test order via WooCommerce
- [ ] Complete payment via Razorpay test
- [ ] Trigger sync → verify `matched` in dashboard
- [ ] Verify platform badge shows "🔧 WooCommerce" in table
- [ ] Filter by "WooCommerce" tab → shows only WooCommerce orders

### Both Platforms
- [ ] Connect both Shopify + WooCommerce for same org
- [ ] Sync runs both → transactions show correct platform badges
- [ ] Export includes transactions from both platforms
- [ ] ITC report aggregates fees from both
- [ ] RTBF deletes woocommerce_credentials too
