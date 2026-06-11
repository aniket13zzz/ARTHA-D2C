"use client";
// artha-v2/frontend/app/settings/billing/page.tsx
// Billing: GMV history, plan, exports, ITC report

import { useEffect, useState } from "react";
import { api, paiseTo, type GMVHistory, type ITCReport, type ExportRecord } from "@/lib/api";

export default function BillingPage() {
  const [gmvHistory, setGmvHistory] = useState<GMVHistory[]>([]);
  const [itc, setItc] = useState<ITCReport | null>(null);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [loading, setLoading] = useState(true);

  // Export form
  const [exportFmt, setExportFmt] = useState("tally");
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d.toISOString().slice(0, 10);
  });
  const [dateTo, setDateTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [exporting, setExporting] = useState(false);
  const [exportMsg, setExportMsg] = useState("");

  useEffect(() => {
    Promise.all([
      api.getGMVHistory(),
      api.getITCReport(),
    ]).then(([g, i]) => {
      setGmvHistory(g.history);
      setItc(i);
    }).finally(() => setLoading(false));
  }, []);

  async function handleExport(e: React.FormEvent) {
    e.preventDefault();
    setExporting(true);
    setExportMsg("");
    try {
      const { export_id } = await api.createExport(exportFmt, dateFrom, dateTo);
      setExportMsg(`Export queued (ID: ${export_id}). Ready in ~30 seconds.`);
      // Poll for ready
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        const status = await api.getExportStatus(export_id);
        if (status.status === "ready" && status.signed_url) {
          clearInterval(poll);
          setExports(prev => [status, ...prev]);
          setExportMsg("Export ready!");
        } else if (status.status === "failed" || attempts > 20) {
          clearInterval(poll);
          setExportMsg(status.error_message || "Export failed");
        }
      }, 3000);
    } catch (err: unknown) {
      setExportMsg(err instanceof Error ? err.message : "Export failed");
    }
    setExporting(false);
  }

  if (loading) return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center">
      <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="bg-white border-b border-slate-200 px-6 py-4 flex items-center gap-3">
        <a href="/settings" className="text-slate-400 hover:text-slate-700 text-sm">← Settings</a>
        <span className="text-slate-300">|</span>
        <span className="font-semibold text-slate-900">Billing & Usage</span>
      </nav>

      <div className="max-w-4xl mx-auto px-6 py-8 space-y-8">

        {/* ITC Recovery Card */}
        {itc && (
          <div className="bg-gradient-to-r from-blue-600 to-blue-700 rounded-xl p-6 text-white">
            <div className="text-sm opacity-80 mb-1">ITC Recovery This Month ({itc.month_year})</div>
            <div className="text-3xl font-bold mb-1">{paiseTo(itc.recoverable_itc_paise)}</div>
            <div className="text-sm opacity-70">
              GST on Razorpay fees across {itc.transaction_count} transactions •
              Total fees: {paiseTo(itc.total_fee_paise)}
            </div>
          </div>
        )}

        {/* GMV History */}
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h3 className="font-semibold text-slate-900 mb-4">Monthly GMV History</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-xs uppercase tracking-wide border-b border-slate-100">
                  <th className="text-left pb-3">Month</th>
                  <th className="text-right pb-3">GMV</th>
                  <th className="text-right pb-3">Orders</th>
                  <th className="text-right pb-3">Plan</th>
                  <th className="text-right pb-3">Billing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {gmvHistory.map(row => (
                  <tr key={row.month_year} className="hover:bg-slate-50">
                    <td className="py-3 font-medium text-slate-900">{row.month_year}</td>
                    <td className="py-3 text-right text-slate-700">{paiseTo(row.total_gmv_paise)}</td>
                    <td className="py-3 text-right text-slate-500">{row.order_count.toLocaleString()}</td>
                    <td className="py-3 text-right">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        row.plan_at_month === "growth" ? "bg-blue-100 text-blue-700" :
                        row.plan_at_month === "enterprise" ? "bg-purple-100 text-purple-700" :
                        "bg-slate-100 text-slate-600"
                      }`}>
                        {row.plan_at_month}
                      </span>
                    </td>
                    <td className="py-3 text-right text-slate-700">{row.billing_amount_paise ? paiseTo(row.billing_amount_paise) : "—"}</td>
                  </tr>
                ))}
                {gmvHistory.length === 0 && (
                  <tr><td colSpan={5} className="py-6 text-center text-slate-400">No billing history yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Export Engine */}
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <h3 className="font-semibold text-slate-900 mb-4">Generate Accounting Export</h3>
          <form onSubmit={handleExport} className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Format</label>
                <select
                  value={exportFmt}
                  onChange={e => setExportFmt(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="tally">Tally ERP 9</option>
                  <option value="zoho">Zoho Books</option>
                  <option value="quickbooks">QuickBooks</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">From</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={e => setDateFrom(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">To</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={e => setDateTo(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            {exportMsg && (
              <div className={`text-sm px-4 py-2 rounded-lg ${exportMsg.includes("failed") || exportMsg.includes("Failed") ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-700"}`}>
                {exportMsg}
              </div>
            )}

            <button
              type="submit"
              disabled={exporting}
              className="bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              {exporting ? "Queuing..." : "Generate Export"}
            </button>
          </form>

          {/* Recent exports */}
          {exports.length > 0 && (
            <div className="mt-6 space-y-2">
              <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">Recent Exports</div>
              {exports.map(exp => (
                <div key={exp.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg text-sm">
                  <div>
                    <span className="font-medium text-slate-900">{exp.format.toUpperCase()}</span>
                    <span className="text-slate-400 ml-2">• {exp.record_count} records</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      exp.status === "ready" ? "bg-green-100 text-green-700" :
                      exp.status === "failed" ? "bg-red-100 text-red-700" :
                      "bg-yellow-100 text-yellow-700"
                    }`}>{exp.status}</span>
                    {exp.signed_url && (
                      <a
                        href={exp.signed_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline font-medium"
                      >
                        Download ↓
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
