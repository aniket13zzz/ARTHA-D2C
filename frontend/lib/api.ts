// artha-v2/frontend/lib/api.ts
// Typed API client for Artha V2 backend

import { supabase } from "./supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL!;

async function getAuthHeaders(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not authenticated");
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

// ─── Types ───────────────────────────────────────────────────

export interface DashboardSummary {
  month_year: string;
  gmv_paise: number;
  order_count: number;
  ghost_orders: number;
  refund_traps: number;
  variances: number;
}

export interface Transaction {
  id: string;
  shopify_order_id: string;        // order_id from any ecom platform
  shopify_status: string;
  shopify_amount_paise: number;    // BIGINT paise
  razorpay_payment_id: string | null;
  razorpay_status: string | null;
  razorpay_amount_paise: number | null;
  razorpay_fee_paise: number;
  razorpay_tax_paise: number;
  transaction_type: "sale" | "refund" | "partial_refund" | "chargeback";
  recon_status: "matched" | "ghost_order" | "variance" | "refund_trap" | "unmatched";
  variance_paise: number;
  ecom_platform: "shopify" | "woocommerce";
  shopify_created_at: string;
  synced_at: string;
}

export interface SyncLog {
  id: string;
  sync_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  records_fetched: number;
  records_matched: number;
  records_failed: number;
  error_message: string | null;
  retry_count: number;
}

export interface Notification {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  body: string;
  is_read: boolean;
  sent_at: string;
  created_at: string;
}

export interface GMVHistory {
  month_year: string;
  total_gmv_paise: number;
  order_count: number;
  plan_at_month: string;
  billing_amount_paise: number;
}

export interface ExportRecord {
  id: string;
  format: string;
  status: string;
  record_count: number;
  signed_url: string | null;
  url_expires_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ITCReport {
  month_year: string;
  total_fee_paise: number;
  total_tax_paise: number;
  recoverable_itc_paise: number;
  transaction_count: number;
}


export interface ConnectionStatus {
  shopify: { connected: boolean; shop_domain: string | null; last_verified_at: string | null };
  woocommerce: { connected: boolean; site_url: string | null; last_verified_at: string | null };
  razorpay: { connected: boolean; last_verified_at: string | null };
}

// ─── API calls ───────────────────────────────────────────────

export const api = {
  // Org
  createOrg: (name: string) =>
    apiFetch<{ org_id: string }>("/api/org", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  // Connect
  connectShopify: (shopDomain: string, accessToken: string) =>
    apiFetch<{ ok: boolean }>("/api/connect/shopify", {
      method: "POST",
      body: JSON.stringify({ shop_domain: shopDomain, access_token: accessToken }),
    }),

  connectRazorpay: (keyId: string, keySecret: string, webhookSecret?: string) =>
    apiFetch<{ ok: boolean }>("/api/connect/razorpay", {
      method: "POST",
      body: JSON.stringify({ key_id: keyId, key_secret: keySecret, webhook_secret: webhookSecret }),
    }),

  disconnectShopify: () =>
    apiFetch<{ ok: boolean }>("/api/connect/shopify", { method: "DELETE" }),

  connectWooCommerce: (siteUrl: string, consumerKey: string, consumerSecret: string) =>
    apiFetch<{ ok: boolean }>("/api/connect/woocommerce", {
      method: "POST",
      body: JSON.stringify({ site_url: siteUrl, consumer_key: consumerKey, consumer_secret: consumerSecret }),
    }),

  disconnectWooCommerce: () =>
    apiFetch<{ ok: boolean }>("/api/connect/woocommerce", { method: "DELETE" }),

  getConnectionStatus: () =>
    apiFetch<ConnectionStatus>("/api/connect/status"),

  // Dashboard
  getDashboardSummary: () =>
    apiFetch<DashboardSummary>("/api/dashboard/summary"),

  // Transactions
  getTransactions: (params?: {
    status?: string;
    tx_type?: string;
    platform?: "shopify" | "woocommerce";
    page?: number;
    page_size?: number;
  }) => {
    const q = new URLSearchParams(
      Object.entries(params || {})
        .filter(([, v]) => v != null)
        .map(([k, v]) => [k, String(v)])
    );
    return apiFetch<{ transactions: Transaction[]; page: number; page_size: number }>(
      `/api/transactions?${q}`
    );
  },

  getTransaction: (id: string) =>
    apiFetch<Transaction>(`/api/transactions/${id}`),

  // Sync
  getSyncLogs: (page = 1) =>
    apiFetch<{ sync_logs: SyncLog[] }>(`/api/sync-logs?page=${page}`),

  triggerSync: () =>
    apiFetch<{ ok: boolean; message: string }>("/api/sync/trigger", { method: "POST" }),

  // Alerts
  getAlertPrefs: () => apiFetch<Record<string, unknown>>("/api/settings/alerts"),

  updateAlertPrefs: (prefs: Record<string, unknown>) =>
    apiFetch<{ ok: boolean }>("/api/settings/alerts", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),

  // Notifications
  getNotifications: (unreadOnly = false, page = 1) =>
    apiFetch<{ notifications: Notification[] }>(
      `/api/notifications?unread_only=${unreadOnly}&page=${page}`
    ),

  markNotificationRead: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/notifications/${id}/read`, { method: "PATCH" }),

  // Billing
  getGMVHistory: () =>
    apiFetch<{ history: GMVHistory[] }>("/api/billing/gmv"),

  // Exports
  createExport: (format: string, dateFrom: string, dateTo: string) =>
    apiFetch<{ export_id: string; status: string }>("/api/export", {
      method: "POST",
      body: JSON.stringify({ format, date_from: dateFrom, date_to: dateTo }),
    }),

  getExportStatus: (exportId: string) =>
    apiFetch<ExportRecord>(`/api/export/${exportId}`),

  // ITC
  getITCReport: (monthYear?: string) =>
    apiFetch<ITCReport>(
      `/api/itc-report${monthYear ? `?month_year=${monthYear}` : ""}`
    ),
};

// ─── Helpers ─────────────────────────────────────────────────

export function paiseTo(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export const RECON_STATUS_LABELS: Record<string, string> = {
  matched: "Matched",
  ghost_order: "Ghost Order",
  variance: "Variance",
  refund_trap: "Refund Trap",
  unmatched: "Unmatched",
};

export const RECON_STATUS_COLORS: Record<string, string> = {
  matched: "bg-green-100 text-green-800",
  ghost_order: "bg-red-100 text-red-800",
  variance: "bg-yellow-100 text-yellow-800",
  refund_trap: "bg-orange-100 text-orange-800",
  unmatched: "bg-gray-100 text-gray-800",
};
