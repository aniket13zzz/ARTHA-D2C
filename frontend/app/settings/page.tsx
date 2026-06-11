"use client";
// artha-v2/frontend/app/settings/page.tsx
// Settings: alerts, integrations, CA portal

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Tab = "alerts" | "integrations" | "billing";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("alerts");
  const [alertPrefs, setAlertPrefs] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const [connStatus, setConnStatus] = useState<Record<string, Record<string, unknown>>>({});

  useEffect(() => {
    api.getAlertPrefs().then(setAlertPrefs).catch(console.error);
    api.getConnectionStatus().then((s: unknown) => setConnStatus(s as Record<string, Record<string, unknown>>)).catch(console.error);
  }, []);

  async function saveAlerts(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.updateAlertPrefs(alertPrefs);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
    setSaving(false);
  }

  function updatePref(key: string, value: unknown) {
    setAlertPrefs(prev => ({ ...prev, [key]: value }));
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "alerts", label: "Alert Preferences" },
    { key: "integrations", label: "Integrations" },
    { key: "billing", label: "Billing" },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="bg-white border-b border-slate-200 px-6 py-4 flex items-center gap-3">
        <a href="/dashboard" className="text-slate-400 hover:text-slate-700 text-sm">← Dashboard</a>
        <span className="text-slate-300">|</span>
        <span className="font-semibold text-slate-900">Settings</span>
      </nav>

      <div className="max-w-3xl mx-auto px-6 py-8">
        {/* Tabs */}
        <div className="flex gap-1 bg-slate-100 p-1 rounded-lg mb-8 w-fit">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                tab === t.key ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-6 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
        )}
        {saved && (
          <div className="mb-6 bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">✓ Saved successfully</div>
        )}

        {/* Alerts Tab */}
        {tab === "alerts" && (
          <form onSubmit={saveAlerts} className="space-y-6">
            <div className="bg-white rounded-xl border border-slate-200 p-6">
              <h3 className="font-semibold text-slate-900 mb-4">Notification Channels</h3>
              <div className="space-y-4">
                {/* Email */}
                <label className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-slate-900 text-sm">Email</div>
                    <div className="text-xs text-slate-400">Sent to account owner email via Resend</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={!!alertPrefs.email_enabled}
                    onChange={e => updatePref("email_enabled", e.target.checked)}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600"
                  />
                </label>

                {/* Slack */}
                <label className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-slate-900 text-sm">Slack</div>
                    <div className="text-xs text-slate-400">Webhook URL (encrypted)</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={!!alertPrefs.slack_enabled}
                    onChange={e => updatePref("slack_enabled", e.target.checked)}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600"
                  />
                </label>
                {alertPrefs.slack_enabled && (
                  <input
                    type="password"
                    placeholder="https://hooks.slack.com/..."
                    value={(alertPrefs.slack_webhook as string) || ""}
                    onChange={e => updatePref("slack_webhook", e.target.value)}
                    className="w-full px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                )}

                {/* WhatsApp */}
                <label className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-slate-900 text-sm">WhatsApp</div>
                    <div className="text-xs text-slate-400">Interakt API (Growth plan only)</div>
                  </div>
                  <input
                    type="checkbox"
                    checked={!!alertPrefs.whatsapp_enabled}
                    onChange={e => updatePref("whatsapp_enabled", e.target.checked)}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600"
                  />
                </label>
                {alertPrefs.whatsapp_enabled && (
                  <div className="space-y-2">
                    <input
                      type="password"
                      placeholder="Interakt API token"
                      value={(alertPrefs.whatsapp_token as string) || ""}
                      onChange={e => updatePref("whatsapp_token", e.target.value)}
                      className="w-full px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                    <input
                      type="tel"
                      placeholder="9876543210"
                      value={(alertPrefs.whatsapp_phone as string) || ""}
                      onChange={e => updatePref("whatsapp_phone", e.target.value)}
                      className="w-full px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                )}
              </div>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 p-6">
              <h3 className="font-semibold text-slate-900 mb-4">Alert Thresholds</h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Ghost Order threshold (₹)</label>
                  <input
                    type="number"
                    min={0}
                    value={Math.round(((alertPrefs.ghost_order_threshold_paise as number) || 100000) / 100)}
                    onChange={e => updatePref("ghost_order_threshold_paise", parseInt(e.target.value) * 100)}
                    className="w-full px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Variance threshold (₹)</label>
                  <input
                    type="number"
                    min={0}
                    value={Math.round(((alertPrefs.variance_threshold_paise as number) || 50000) / 100)}
                    onChange={e => updatePref("variance_threshold_paise", parseInt(e.target.value) * 100)}
                    className="w-full px-4 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={saving}
              className="bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Alert Settings"}
            </button>
          </form>
        )}

        {/* Integrations Tab */}
        {tab === "integrations" && (
          <div className="space-y-4">
            {/* Shopify */}
            <div className="bg-white rounded-xl border border-slate-200 p-6">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center text-xl">🛍️</div>
                  <div>
                    <div className="font-semibold text-slate-900">Shopify</div>
                    <div className="text-sm text-slate-500">
                      {connStatus.shopify?.shop_domain ? String(connStatus.shopify.shop_domain) : "Orders & Refunds"}
                    </div>
                  </div>
                </div>
                {connStatus.shopify?.connected ? (
                  <span className="px-3 py-1 bg-green-100 text-green-700 text-xs font-semibold rounded-full">Connected</span>
                ) : (
                  <span className="px-3 py-1 bg-slate-100 text-slate-500 text-xs font-semibold rounded-full">Not connected</span>
                )}
              </div>
              {connStatus.shopify?.connected ? (
                <button onClick={() => api.disconnectShopify().then(() => location.reload())}
                  className="text-sm text-red-500 hover:text-red-700">Disconnect</button>
              ) : (
                <a href="/connect" className="text-sm text-blue-600 hover:text-blue-800">Connect Shopify →</a>
              )}
            </div>

            {/* WooCommerce */}
            <div className="bg-white rounded-xl border border-slate-200 p-6">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center text-xl">🔧</div>
                  <div>
                    <div className="font-semibold text-slate-900">WooCommerce</div>
                    <div className="text-sm text-slate-500">
                      {connStatus.woocommerce?.site_url ? String(connStatus.woocommerce.site_url) : "WordPress / WooCommerce store"}
                    </div>
                  </div>
                </div>
                {connStatus.woocommerce?.connected ? (
                  <span className="px-3 py-1 bg-green-100 text-green-700 text-xs font-semibold rounded-full">Connected</span>
                ) : (
                  <span className="px-3 py-1 bg-slate-100 text-slate-500 text-xs font-semibold rounded-full">Not connected</span>
                )}
              </div>
              {connStatus.woocommerce?.connected ? (
                <button onClick={() => api.disconnectWooCommerce().then(() => location.reload())}
                  className="text-sm text-red-500 hover:text-red-700">Disconnect</button>
              ) : (
                <a href="/connect" className="text-sm text-blue-600 hover:text-blue-800">Connect WooCommerce →</a>
              )}
            </div>

            {/* Razorpay */}
            <div className="bg-white rounded-xl border border-slate-200 p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center text-xl">💳</div>
                  <div>
                    <div className="font-semibold text-slate-900">Razorpay</div>
                    <div className="text-sm text-slate-500">Payments & Settlements</div>
                  </div>
                </div>
                {connStatus.razorpay?.connected ? (
                  <span className="px-3 py-1 bg-green-100 text-green-700 text-xs font-semibold rounded-full">Connected</span>
                ) : (
                  <span className="px-3 py-1 bg-slate-100 text-slate-500 text-xs font-semibold rounded-full">Not connected</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Billing Tab */}
        {tab === "billing" && (
          <div>
            <a href="/settings/billing" className="block">
              <div className="bg-white rounded-xl border border-slate-200 p-6 hover:border-blue-300 transition-colors cursor-pointer">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-slate-900">Billing & Usage</div>
                    <div className="text-sm text-slate-500 mt-1">GMV history, plan details, invoices</div>
                  </div>
                  <span className="text-slate-400">→</span>
                </div>
              </div>
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
