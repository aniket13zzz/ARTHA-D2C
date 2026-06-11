"use client";
// artha-v2/frontend/app/dashboard/page.tsx
// Main reconciliation dashboard

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, paiseTo, type DashboardSummary, type Transaction, type SyncLog } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { TransactionTable } from "@/components/dashboard/TransactionTable";
import { SyncLogsList } from "@/components/dashboard/SyncLogsList";

export default function DashboardPage() {
  const router = useRouter();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [syncLogs, setSyncLogs] = useState<SyncLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [activeTab, setActiveTab] = useState<"all" | "ghost" | "trap" | "variance" | "shopify" | "woocommerce">("all");
  const [error, setError] = useState("");

  useEffect(() => {
    checkAuth();
    loadData();
  }, []);

  async function checkAuth() {
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      router.replace("/login");
    }
  }

  async function loadData() {
    setLoading(true);
    try {
      const [s, t, l] = await Promise.all([
        api.getDashboardSummary(),
        api.getTransactions({ page: 1, page_size: 50 }),
        api.getSyncLogs(),
      ]);
      setSummary(s);
      setTransactions(t.transactions);
      setSyncLogs(l.sync_logs);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    }
    setLoading(false);
  }

  async function handleManualSync() {
    setSyncing(true);
    try {
      await api.triggerSync();
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Sync failed");
    }
    setSyncing(false);
  }

  async function handleSignOut() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  const filteredTxns = transactions.filter((t) => {
    if (activeTab === "ghost")       return t.recon_status === "ghost_order";
    if (activeTab === "trap")        return t.recon_status === "refund_trap";
    if (activeTab === "variance")    return t.recon_status === "variance";
    if (activeTab === "shopify")     return (t as { ecom_platform?: string }).ecom_platform === "shopify";
    if (activeTab === "woocommerce") return (t as { ecom_platform?: string }).ecom_platform === "woocommerce";
    return true;
  });

  const kpiCards = summary ? [
    {
      label: "Monthly GMV",
      value: paiseTo(summary.gmv_paise),
      sub: `${summary.order_count.toLocaleString()} orders`,
      color: "blue",
      icon: "₹",
    },
    {
      label: "Ghost Orders",
      value: summary.ghost_orders.toString(),
      sub: "Missing Razorpay payments",
      color: summary.ghost_orders > 0 ? "red" : "green",
      icon: "👻",
    },
    {
      label: "Refund Traps",
      value: summary.refund_traps.toString(),
      sub: "Shopify refunded, Razorpay didn't",
      color: summary.refund_traps > 0 ? "orange" : "green",
      icon: "🚨",
    },
    {
      label: "Variances",
      value: summary.variances.toString(),
      sub: "Amount mismatches",
      color: summary.variances > 0 ? "yellow" : "green",
      icon: "⚠️",
    },
  ] : [];

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Loading reconciliation data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Navbar */}
      <nav className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center font-bold text-sm">₹</div>
          <span className="font-bold text-slate-900">Artha V2</span>
          <span className="text-slate-300">|</span>
          <span className="text-slate-500 text-sm">{summary?.month_year}</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={handleManualSync}
            disabled={syncing}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            {syncing ? "Syncing..." : "↻ Sync Now"}
          </button>
          <a href="/settings" className="text-slate-500 hover:text-slate-900 text-sm">Settings</a>
          <button onClick={handleSignOut} className="text-slate-400 hover:text-slate-600 text-sm">Sign out</button>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-6 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* KPI Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
          {kpiCards.map(card => (
            <div key={card.label} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-slate-500 text-sm">{card.label}</span>
                <span className="text-2xl">{card.icon}</span>
              </div>
              <div className={`text-2xl font-bold ${
                card.color === "red" ? "text-red-600" :
                card.color === "orange" ? "text-orange-600" :
                card.color === "yellow" ? "text-yellow-600" :
                card.color === "green" ? "text-green-600" :
                "text-slate-900"
              }`}>
                {card.value}
              </div>
              <div className="text-xs text-slate-400 mt-1">{card.sub}</div>
            </div>
          ))}
        </div>

        {/* Transactions */}
        <div className="bg-white rounded-xl border border-slate-200 mb-6">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900">Reconciled Transactions</h2>
            <div className="flex gap-1">
              {([
                { key: "all", label: "All" },
                { key: "ghost", label: "👻 Ghost" },
                { key: "trap", label: "🚨 Traps" },
                { key: "variance", label: "⚠️ Variance" },
              { key: "shopify",  label: "🛍 Shopify" },
              { key: "woocommerce", label: "🔧 WooCommerce" },
              ] as const).map(tab => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                    activeTab === tab.key
                      ? "bg-blue-600 text-white"
                      : "text-slate-500 hover:bg-slate-100"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          <TransactionTable transactions={filteredTxns} />
        </div>

        {/* Sync Logs */}
        <div className="bg-white rounded-xl border border-slate-200">
          <div className="px-6 py-4 border-b border-slate-100">
            <h2 className="font-semibold text-slate-900">Sync History</h2>
          </div>
          <SyncLogsList logs={syncLogs} />
        </div>
      </div>
    </div>
  );
}
