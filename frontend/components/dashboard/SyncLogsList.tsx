"use client";
// artha-v2/frontend/components/dashboard/SyncLogsList.tsx

import type { SyncLog } from "@/lib/api";

interface Props {
  logs: SyncLog[];
}

const STATUS_STYLES: Record<string, string> = {
  success: "bg-green-100 text-green-700",
  failed:  "bg-red-100 text-red-700",
  running: "bg-blue-100 text-blue-700",
  pending: "bg-yellow-100 text-yellow-700",
  dead:    "bg-gray-100 text-gray-700",
};

export function SyncLogsList({ logs }: Props) {
  if (logs.length === 0) {
    return (
      <div className="px-6 py-10 text-center text-slate-400 text-sm">
        No syncs yet. First sync runs tonight at 2 AM IST.
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-50">
      {logs.map(log => (
        <div key={log.id} className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${STATUS_STYLES[log.status] || "bg-gray-100 text-gray-600"}`}>
              {log.status}
            </span>
            <div>
              <div className="text-sm font-medium text-slate-900 capitalize">
                {log.sync_type.replace(/_/g, " ")}
              </div>
              {log.error_message && (
                <div className="text-xs text-red-500 mt-0.5 truncate max-w-xs">
                  {log.error_message}
                </div>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">
              {log.records_matched} matched / {log.records_fetched} fetched
              {log.records_failed > 0 && (
                <span className="text-red-500 ml-1">• {log.records_failed} failed</span>
              )}
            </div>
            <div className="text-xs text-slate-400 mt-0.5">
              {new Date(log.started_at).toLocaleString("en-IN")}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
