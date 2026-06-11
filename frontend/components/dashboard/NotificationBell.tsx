"use client";
// artha-v2/frontend/components/dashboard/NotificationBell.tsx

import { useEffect, useState, useRef } from "react";
import { api, type Notification } from "@/lib/api";

const SEVERITY_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high:     "bg-orange-500",
  medium:   "bg-yellow-500",
  low:      "bg-blue-500",
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadNotifications();
    // Poll every 60s
    const interval = setInterval(loadNotifications, 60_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function loadNotifications() {
    try {
      const { notifications: n } = await api.getNotifications(false, 1);
      setNotifications(n.slice(0, 10));
      setUnread(n.filter(x => !x.is_read).length);
    } catch { /* silent */ }
  }

  async function handleMarkRead(id: string) {
    await api.markNotificationRead(id);
    setNotifications(prev =>
      prev.map(n => n.id === id ? { ...n, is_read: true } : n)
    );
    setUnread(prev => Math.max(0, prev - 1));
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 rounded-lg hover:bg-slate-100 transition-colors"
        aria-label="Notifications"
      >
        <svg className="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unread > 0 && (
          <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-bold">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-12 w-96 bg-white rounded-xl shadow-xl border border-slate-200 z-50">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <span className="font-semibold text-slate-900 text-sm">Notifications</span>
            {unread > 0 && (
              <span className="text-xs text-slate-400">{unread} unread</span>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto divide-y divide-slate-50">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-slate-400 text-sm">No notifications</div>
            ) : (
              notifications.map(n => (
                <div
                  key={n.id}
                  className={`px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors ${!n.is_read ? "bg-blue-50/40" : ""}`}
                  onClick={() => !n.is_read && handleMarkRead(n.id)}
                >
                  <div className="flex items-start gap-2">
                    <span className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${SEVERITY_DOT[n.severity] || "bg-gray-400"}`} />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-900 truncate">{n.title}</div>
                      <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">{n.body}</div>
                      <div className="text-xs text-slate-400 mt-1">
                        {new Date(n.created_at).toLocaleString("en-IN")}
                      </div>
                    </div>
                    {!n.is_read && (
                      <span className="flex-shrink-0 w-2 h-2 bg-blue-500 rounded-full mt-2" />
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
