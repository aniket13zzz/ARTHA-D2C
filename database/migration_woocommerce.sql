-- ============================================================
-- ARTHA V2 — MIGRATION: Add WooCommerce Support
-- Run AFTER schema.sql. Fully idempotent — safe to re-run.
-- ============================================================

-- ─── 1. Platform enum ────────────────────────────────────────
DO $$ BEGIN
  CREATE TYPE ecom_platform AS ENUM ('shopify', 'woocommerce');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ─── 2. Add platform column to shopify_credentials ───────────
ALTER TABLE shopify_credentials
  ADD COLUMN IF NOT EXISTS platform ecom_platform NOT NULL DEFAULT 'shopify';

-- ─── 3. WooCommerce credentials table ────────────────────────
CREATE TABLE IF NOT EXISTS woocommerce_credentials (
  id                        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  org_id                    UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  site_url                  TEXT NOT NULL,
  encrypted_consumer_key    TEXT NOT NULL,              -- Fernet encrypted
  encrypted_consumer_secret TEXT NOT NULL,              -- Fernet encrypted
  api_version               TEXT NOT NULL DEFAULT 'wc/v3',
  last_verified_at          TIMESTAMPTZ,
  is_active                 BOOLEAN NOT NULL DEFAULT TRUE,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_woo_org ON woocommerce_credentials(org_id);

-- ─── 4. RLS on woocommerce_credentials ───────────────────────
ALTER TABLE woocommerce_credentials ENABLE ROW LEVEL SECURITY;

-- DROP before CREATE — CREATE POLICY IF NOT EXISTS is not valid Postgres syntax
DO $$ BEGIN
  DROP POLICY IF EXISTS woo_isolation ON woocommerce_credentials;
  EXECUTE $pol$
    CREATE POLICY woo_isolation ON woocommerce_credentials
      USING (org_id = get_user_org_id() AND get_user_role() != 'ca')
  $pol$;
EXCEPTION WHEN undefined_function THEN
  -- get_user_org_id not yet defined; will be created by schema.sql
  NULL;
END $$;

-- ─── 5. ecom_platform column on reconciled_transactions ──────
ALTER TABLE reconciled_transactions
  ADD COLUMN IF NOT EXISTS ecom_platform ecom_platform NOT NULL DEFAULT 'shopify';

-- Index for platform-based filtering (dashboard, exports)
CREATE INDEX IF NOT EXISTS idx_recon_platform
  ON reconciled_transactions(org_id, ecom_platform);

-- ─── 6. ecom_platform on sync_logs ───────────────────────────
ALTER TABLE sync_logs
  ADD COLUMN IF NOT EXISTS ecom_platform ecom_platform;

-- ─── 7. updated_at trigger — idempotent ──────────────────────
DROP TRIGGER IF EXISTS trg_woo_updated ON woocommerce_credentials;
CREATE TRIGGER trg_woo_updated
  BEFORE UPDATE ON woocommerce_credentials
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── 8. connected_platforms on organization_settings ─────────
ALTER TABLE organization_settings
  ADD COLUMN IF NOT EXISTS connected_platforms ecom_platform[]
    NOT NULL DEFAULT '{}';

-- ─── 9. Update anonymize_old_transactions — handle ecom_platform ─
CREATE OR REPLACE FUNCTION anonymize_old_transactions()
RETURNS void AS $$
BEGIN
  UPDATE reconciled_transactions
  SET
    shopify_order_id      = 'ANON-' || id::TEXT,
    razorpay_payment_id   = NULL,
    updated_at            = NOW()
    -- ecom_platform intentionally retained for analytics
  WHERE synced_at < NOW() - INTERVAL '24 months';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ─── 10. Update RTBF to include woocommerce_credentials ──────
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
  DELETE FROM woocommerce_credentials  WHERE org_id = p_org_id;  -- added
  DELETE FROM razorpay_credentials     WHERE org_id = p_org_id;
  DELETE FROM audit_logs               WHERE org_id = p_org_id;
  DELETE FROM users                    WHERE org_id = p_org_id;
  DELETE FROM organizations            WHERE id     = p_org_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
