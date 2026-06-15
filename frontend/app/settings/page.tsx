"use client";
export const dynamic = 'force-dynamic';

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Tab = "alerts" | "integrations" | "billing";

interface ConnStatusPlatform {
  connected: boolean;
  shop_domain?: string | null;
  site_url?: string | null;
  last_verified_at?: string | null;
}

interface ConnStatus {
  shopify: ConnStatusPlatform;
  woocommerce: ConnStatusPlatform;
  razorpay: ConnStatusPlatform;
}

const DEFAULT_CONN: ConnStatus = {
  shopify: { connected: false },
  woocommerce: { connected: false },
  razorpay: { connected: false },
};

export default function SettingsPage() {
  return <div>Settings</div>;
}
