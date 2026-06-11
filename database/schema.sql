-- ============================================================
-- ARTHA V2 — MASTER DATABASE SCHEMA
-- Region: AWS Mumbai (ap-south-1) via Supabase
-- All money: BIGINT paise. NO FLOAT/DOUBLE.
-- All tables: RLS enabled.
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUM TYPES
-- ============================================================

CREATE TYPE plan_tier AS ENUM ('starter', 'growth', 'enterprise');
CREATE TYPE transaction_type AS ENUM ('sale', 'refund', 'partial_refund', 'chargeback');
CREATE TYPE reconciliation_status AS ENUM ('matched', 'ghost_order', 'variance', 'refund_trap', 'unmatched');
CREATE TYPE sync_status AS ENUM ('pending', 'running', 'success', 'failed', 'dead');
CREATE TYPE alert_channel AS ENUM ('email', 'slack', 'whatsapp');
CREATE TYPE alert_severity AS ENUM ('critical', 'high', 'medium', 'low');
CREATE TYPE alert_type AS ENUM (
  'sync_failure', 'api_expiry', 'auth_failure',
  'refund_trap', 'ghost_order', 'chargeback',
  'variance', 'upgrade_required', 'payment_due'
);
CREATE TYPE export_format AS ENUM ('tally', 'zoho', 'quickbooks');
CREATE TYPE export_status AS ENUM ('pending', 'generating', 'ready', 'expired', 'failed');
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'ca', 'viewer');
CREATE TYPE audit_action AS ENUM (
  'login', 'logout', 'connect_shopify', 'connect_razorpay',
  'disconnect_shopify', 'disconnect_razorpay',
  'export_generated', 'settings_changed', 'billing_changed',
  'ca_invited', 'ca_removed', 'sync_triggered'
);

-- ============================================================
-- WEEK 1: CORE — ORGANIZATIONS, USERS
-- ============================================================

CREATE TABLE organizations (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name                TEXT NOT NULL,
  plan                plan_tier NOT NULL DEFAULT 'starter',
  plan_started_at     TIMESTAMPTZ,
  plan_expires_at     TIMESTAMPTZ,
  razorpay_sub_id     TEXT,                          -- encrypted at app layer
  is_active           BOOLEAN NOT NULL DEFAULT TRUE,
  right_to_forget_at  TIMESTAMPTZ,                   -- RTBF requested timestamp
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  supabase_uid    UUID NOT NULL UNIQUE,              -- links to auth.users
  role            user_role NOT NULL DEFAULT 'viewer',
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_org ON users(org_id);
CREATE INDEX idx_users_supabase ON users(supabase_uid);

-- ============================================================
-- WEEK 2: INTEGRATIONS — SHOPIFY, RAZORPAY CREDENTIALS
-- ============================================================

CREATE TABLE shopify_credentials (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id            UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  shop_domain       TEXT NOT NULL,
  -- encrypted_access_token: Fernet encrypted, stored as TEXT
  encrypted_access_token TEXT NOT NULL,
  scopes            TEXT[],
  installed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_verified_at  TIMESTAMPTZ,
  expires_at        TIMESTAMPTZ,                     -- for expiry alerts
  is_active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_shopify_org ON shopify_credentials(org_id);

CREATE TABLE razorpay_credentials (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id                UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  -- encrypted_key_id / encrypted_key_secret: Fernet encrypted
  encrypted_key_id      TEXT NOT NULL,
  encrypted_key_secret  TEXT NOT NULL,
  webhook_secret        TEXT,                        -- Fernet encrypted
  last_verified_at      TIMESTAMPTZ,
  is_active             BOOLEAN NOT NULL DEFAULT TRUE,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_razorpay_org ON razorpay_credentials(org_id);

-- ============================================================
-- WEEK 3: RECONCILIATION ENGINE
-- ============================================================

CREATE TABLE reconciled_transactions (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id                UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

  -- Shopify data (NO PII)
  shopify_order_id      TEXT NOT NULL,
  shopify_status        TEXT,
  shopify_amount_paise  BIGINT NOT NULL,             -- BIGINT paise only
  shopify_created_at    TIMESTAMPTZ,

  -- Razorpay data (NO PII)
  razorpay_payment_id   TEXT,
  razorpay_status       TEXT,
  razorpay_amount_paise BIGINT,                      -- BIGINT paise only
  razorpay_fee_paise    BIGINT DEFAULT 0,
  razorpay_tax_paise    BIGINT DEFAULT 0,            -- for ITC
  razorpay_settled_at   TIMESTAMPTZ,

  -- Reconciliation result
  transaction_type      transaction_type NOT NULL DEFAULT 'sale',
  recon_status          reconciliation_status NOT NULL,
  variance_paise        BIGINT DEFAULT 0,            -- shopify - razorpay
  parent_transaction_id UUID REFERENCES reconciled_transactions(id),  -- for refunds

  -- Metadata
  synced_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT no_float_check CHECK (
    shopify_amount_paise >= 0 AND
    (razorpay_amount_paise IS NULL OR razorpay_amount_paise >= 0)
  )
);

CREATE INDEX idx_recon_org ON reconciled_transactions(org_id);
CREATE INDEX idx_recon_shopify ON reconciled_transactions(shopify_order_id);
CREATE INDEX idx_recon_razorpay ON reconciled_transactions(razorpay_payment_id);
CREATE INDEX idx_recon_status ON reconciled_transactions(recon_status);
CREATE INDEX idx_recon_type ON reconciled_transactions(transaction_type);
CREATE INDEX idx_recon_synced ON reconciled_transactions(synced_at);

-- ============================================================
-- WEEK 4: SYNC INFRASTRUCTURE
-- ============================================================

CREATE TABLE sync_logs (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  sync_type       TEXT NOT NULL,                     -- 'shopify', 'razorpay', 'reconcile'
  status          sync_status NOT NULL DEFAULT 'pending',
  started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at    TIMESTAMPTZ,
  records_fetched INT DEFAULT 0,
  records_matched INT DEFAULT 0,
  records_failed  INT DEFAULT 0,
  error_message   TEXT,
  retry_count     INT DEFAULT 0,
  metadata        JSONB DEFAULT '{}'::JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sync_org ON sync_logs(org_id);
CREATE INDEX idx_sync_status ON sync_logs(status);
CREATE INDEX idx_sync_created ON sync_logs(created_at);

CREATE TABLE dead_letter_queue (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  queue_name      TEXT NOT NULL,                     -- 'shopify_sync', 'razorpay_sync', etc.
  payload         JSONB NOT NULL,
  error_message   TEXT,
  retry_count     INT NOT NULL DEFAULT 0,
  max_retries     INT NOT NULL DEFAULT 3,
  last_attempted  TIMESTAMPTZ,
  resolved_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dlq_org ON dead_letter_queue(org_id);
CREATE INDEX idx_dlq_queue ON dead_letter_queue(queue_name);
CREATE INDEX idx_dlq_resolved ON dead_letter_queue(resolved_at);

-- ============================================================
-- WEEK 5: ALERTS
-- ============================================================

CREATE TABLE alert_preferences (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id          UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,

  -- Channels
  email_enabled   BOOLEAN NOT NULL DEFAULT TRUE,
  slack_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
  whatsapp_enabled BOOLEAN NOT NULL DEFAULT FALSE,

  -- Encrypted credentials
  slack_webhook_encrypted   TEXT,
  whatsapp_token_encrypted  TEXT,
  whatsapp_phone            TEXT,

  -- Thresholds (paise)
  ghost_order_threshold_paise   BIGINT NOT NULL DEFAULT 100000,  -- ₹1000
  variance_threshold_paise      BIGINT NOT NULL DEFAULT 50000,   -- ₹500
  chargeback_threshold_paise    BIGINT NOT NULL DEFAULT 100000,  -- ₹1000

  -- Per-severity toggles
  critical_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
  high_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
  medium_enabled    BOOLEAN NOT NULL DEFAULT TRUE,

  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE notifications (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  alert_type      alert_type NOT NULL,
  severity        alert_severity NOT NULL,
  channel         alert_channel NOT NULL,
  title           TEXT NOT NULL,
  body            TEXT NOT NULL,
  metadata        JSONB DEFAULT '{}'::JSONB,
  is_read         BOOLEAN NOT NULL DEFAULT FALSE,
  sent_at         TIMESTAMPTZ,
  failed_at       TIMESTAMPTZ,
  error_message   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notif_org ON notifications(org_id);
CREATE INDEX idx_notif_type ON notifications(alert_type);
CREATE INDEX idx_notif_unread ON notifications(org_id, is_read);

-- ============================================================
-- WEEK 6: BILLING / USAGE METERING
-- ============================================================

CREATE TABLE monthly_gmv (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id                UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  month_year            TEXT NOT NULL,               -- 'YYYY-MM'
  total_gmv_paise       BIGINT NOT NULL DEFAULT 0,   -- BIGINT paise
  order_count           INT NOT NULL DEFAULT 0,
  plan_at_month         plan_tier NOT NULL DEFAULT 'starter',
  billing_amount_paise  BIGINT DEFAULT 0,
  invoice_sent          BOOLEAN NOT NULL DEFAULT FALSE,
  razorpay_payment_link TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(org_id, month_year)
);

CREATE INDEX idx_gmv_org ON monthly_gmv(org_id);
CREATE INDEX idx_gmv_month ON monthly_gmv(month_year);

-- ============================================================
-- WEEK 7: EXPORTS + SETTINGS
-- ============================================================

CREATE TABLE tally_exports (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  format          export_format NOT NULL DEFAULT 'tally',
  date_from       DATE NOT NULL,
  date_to         DATE NOT NULL,
  status          export_status NOT NULL DEFAULT 'pending',
  record_count    INT DEFAULT 0,
  signed_url      TEXT,                              -- expiring S3/Supabase Storage URL
  url_expires_at  TIMESTAMPTZ,
  generated_by    UUID REFERENCES users(id),
  error_message   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_export_org ON tally_exports(org_id);
CREATE INDEX idx_export_status ON tally_exports(status);

CREATE TABLE organization_settings (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id                UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  gst_number            TEXT,
  timezone              TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  fiscal_year_start     INT NOT NULL DEFAULT 4,      -- April
  tally_company_name    TEXT,
  zoho_org_id           TEXT,
  quickbooks_realm_id   TEXT,
  auto_upgrade_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- WEEK 8: AUDIT LOGS (Append-only)
-- ============================================================

CREATE TABLE audit_logs (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id     UUID REFERENCES users(id),
  action      audit_action NOT NULL,
  ip_address  INET,
  user_agent  TEXT,
  metadata    JSONB DEFAULT '{}'::JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_org ON audit_logs(org_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_created ON audit_logs(created_at);

-- Audit logs are append-only — block UPDATE and DELETE
CREATE RULE audit_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;

-- ============================================================
-- ROW LEVEL SECURITY (RLS) — MANDATORY ON ALL TABLES
-- ============================================================

ALTER TABLE organizations            ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE shopify_credentials      ENABLE ROW LEVEL SECURITY;
ALTER TABLE razorpay_credentials     ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconciled_transactions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_logs                ENABLE ROW LEVEL SECURITY;
ALTER TABLE dead_letter_queue        ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_preferences        ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications            ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_gmv              ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally_exports            ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_settings    ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs               ENABLE ROW LEVEL SECURITY;

-- Helper function: get org_id for current JWT user
CREATE OR REPLACE FUNCTION get_user_org_id()
RETURNS UUID AS $$
  SELECT org_id FROM users WHERE supabase_uid = auth.uid()
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

-- Helper function: get user role
CREATE OR REPLACE FUNCTION get_user_role()
RETURNS user_role AS $$
  SELECT role FROM users WHERE supabase_uid = auth.uid()
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

-- organizations: user sees own org only
CREATE POLICY org_isolation ON organizations
  USING (id = get_user_org_id());

-- users: see only own org users
CREATE POLICY users_isolation ON users
  USING (org_id = get_user_org_id());

-- shopify_credentials: CA blocked
CREATE POLICY shopify_isolation ON shopify_credentials
  USING (org_id = get_user_org_id() AND get_user_role() != 'ca');

-- razorpay_credentials: CA blocked
CREATE POLICY razorpay_isolation ON razorpay_credentials
  USING (org_id = get_user_org_id() AND get_user_role() != 'ca');

-- reconciled_transactions: all roles can read
CREATE POLICY recon_isolation ON reconciled_transactions
  USING (org_id = get_user_org_id());

-- sync_logs: CA allowed read
CREATE POLICY sync_isolation ON sync_logs
  USING (org_id = get_user_org_id());

-- dead_letter_queue: CA blocked
CREATE POLICY dlq_isolation ON dead_letter_queue
  USING (org_id = get_user_org_id() AND get_user_role() != 'ca');

-- alert_preferences: CA blocked
CREATE POLICY alert_pref_isolation ON alert_preferences
  USING (org_id = get_user_org_id() AND get_user_role() != 'ca');

-- notifications: all roles
CREATE POLICY notif_isolation ON notifications
  USING (org_id = get_user_org_id());

-- monthly_gmv: CA allowed read
CREATE POLICY gmv_isolation ON monthly_gmv
  USING (org_id = get_user_org_id());

-- tally_exports: CA allowed read
CREATE POLICY export_isolation ON tally_exports
  USING (org_id = get_user_org_id());

-- organization_settings: CA blocked (no billing/settings)
CREATE POLICY settings_isolation ON organization_settings
  USING (org_id = get_user_org_id() AND get_user_role() != 'ca');

-- audit_logs: owner/admin only
CREATE POLICY audit_isolation ON audit_logs
  USING (org_id = get_user_org_id() AND get_user_role() IN ('owner', 'admin'));

-- ============================================================
-- RETENTION / ANONYMIZATION (24 months)
-- Run via GitHub Actions monthly
-- ============================================================

CREATE OR REPLACE FUNCTION anonymize_old_transactions()
RETURNS void AS $$
BEGIN
  UPDATE reconciled_transactions
  SET
    shopify_order_id      = 'ANON-' || id::TEXT,
    razorpay_payment_id   = NULL,
    updated_at            = NOW()
  WHERE synced_at < NOW() - INTERVAL '24 months';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Right To Be Forgotten: delete all org data within 24h
CREATE OR REPLACE FUNCTION execute_rtbf(p_org_id UUID)
RETURNS void AS $$
BEGIN
  DELETE FROM reconciled_transactions  WHERE org_id = p_org_id;
  DELETE FROM sync_logs                WHERE org_id = p_org_id;
  DELETE FROM dead_letter_queue        WHERE org_id = p_org_id;
  DELETE FROM notifications            WHERE org_id = p_org_id;
  DELETE FROM monthly_gmv              WHERE org_id = p_org_id;
  DELETE FROM tally_exports            WHERE org_id = p_org_id;
  DELETE FROM alert_preferences        WHERE org_id = p_org_id;
  DELETE FROM organization_settings    WHERE org_id = p_org_id;
  DELETE FROM shopify_credentials      WHERE org_id = p_org_id;
  DELETE FROM razorpay_credentials     WHERE org_id = p_org_id;
  DELETE FROM audit_logs               WHERE org_id = p_org_id;
  DELETE FROM users                    WHERE org_id = p_org_id;
  DELETE FROM organizations            WHERE id     = p_org_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- UPDATED_AT triggers
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_orgs_updated         BEFORE UPDATE ON organizations            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_users_updated        BEFORE UPDATE ON users                    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_shopify_updated      BEFORE UPDATE ON shopify_credentials      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_razorpay_updated     BEFORE UPDATE ON razorpay_credentials     FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_recon_updated        BEFORE UPDATE ON reconciled_transactions  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_gmv_updated          BEFORE UPDATE ON monthly_gmv              FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_exports_updated      BEFORE UPDATE ON tally_exports            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_settings_updated     BEFORE UPDATE ON organization_settings    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_alertpref_updated    BEFORE UPDATE ON alert_preferences        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
