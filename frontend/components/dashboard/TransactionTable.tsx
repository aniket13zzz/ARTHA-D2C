"use client";
// artha-v2/frontend/components/dashboard/TransactionTable.tsx

import { useRouter } from "next/navigation";
import {
  paiseTo,
  RECON_STATUS_LABELS,
  RECON_STATUS_COLORS,
  type Transaction,
} from "@/lib/api";

// Extend Transaction type locally with ecom_platform (returned by API, not in base type)
type TransactionWithPlatform = Transaction & {
  ecom_platform?: "shopify" | "woocommerce";
};

interface Props {
  transactions: TransactionWithPlatform[];
}

const PLATFORM_BADGE: Record<string, { label: string; cls: string; icon: string }> = {
  shopify:      { label: "Shopify",      cls: "bg-emerald-100 text-emerald-700", icon: "🛍" },
  woocommerce:  { label: "WooCommerce",  cls: "bg-violet-100 text-violet-700",   icon: "🔧" },
};

const TX_TYPE_LABELS: Record<string, string> = {
  sale:          "Sale",
  refund:        "Refund",
  partial_refund: "Part. Refund",
  chargeback:    "Chargeback",
};

export function TransactionTable({ transactions }: Props) {
  const router = useRouter();

  if (transactions.length === 0) {
    return (
      <div className="px-6 py-12 text-center text-slate-400 text-sm">
        No transactions found.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-400 text-xs uppercase tracking-wide border-b border-slate-100">
            <th className="text-left px-6 py-3">Order ID</th>
            <th className="text-left px-6 py-3">Platform</th>
            <th className="text-left px-6 py-3">Type</th>
            <th className="text-right px-6 py-3">Store Amt</th>
            <th className="text-right px-6 py-3">Razorpay</th>
            <th className="text-right px-6 py-3">Variance</th>
            <th className="text-left px-6 py-3">Status</th>
            <th className="text-left px-6 py-3">Date</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50">
          {transactions.map((t) => {
            const platform = t.ecom_platform ?? "shopify";
            const badge = PLATFORM_BADGE[platform] ?? PLATFORM_BADGE.shopify;
            return (
              <tr
                key={t.id}
                onClick={() => router.push(`/dashboard/transactions/${t.id}`)}
                className="hover:bg-slate-50 cursor-pointer transition-colors"
              >
                {/* Order ID */}
                <td className="px-6 py-3 font-mono text-slate-700 text-xs whitespace-nowrap">
                  #{t.shopify_order_id}
                </td>

                {/* Platform badge — single, clean */}
                <td className="px-6 py-3">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${badge.cls}`}>
                    <span>{badge.icon}</span>
                    {badge.label}
                  </span>
                </td>

                {/* Transaction type */}
                <td className="px-6 py-3 text-slate-500 text-xs capitalize">
                  {TX_TYPE_LABELS[t.transaction_type] ?? t.transaction_type}
                </td>

                {/* Store amount (Shopify or WooCommerce) */}
                <td className="px-6 py-3 text-right text-slate-900 font-medium tabular-nums">
                  {paiseTo(t.shopify_amount_paise)}
                </td>

                {/* Razorpay amount */}
                <td className="px-6 py-3 text-right text-slate-500 tabular-nums">
                  {t.razorpay_amount_paise != null
                    ? paiseTo(t.razorpay_amount_paise)
                    : "—"}
                </td>

                {/* Variance */}
                <td
                  className={`px-6 py-3 text-right font-medium tabular-nums ${
                    t.variance_paise > 0 ? "text-red-600" : "text-slate-300"
                  }`}
                >
                  {t.variance_paise > 0 ? paiseTo(t.variance_paise) : "—"}
                </td>

                {/* Reconciliation status */}
                <td className="px-6 py-3">
                  <span
                    className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                      RECON_STATUS_COLORS[t.recon_status] ?? "bg-gray-100 text-gray-700"
                    }`}
                  >
                    {RECON_STATUS_LABELS[t.recon_status] ?? t.recon_status}
                  </span>
                </td>

                {/* Date */}
                <td className="px-6 py-3 text-slate-400 text-xs whitespace-nowrap">
                  {t.shopify_created_at
                    ? new Date(t.shopify_created_at).toLocaleDateString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
