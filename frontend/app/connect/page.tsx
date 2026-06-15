"use client";
export const dynamic = 'force-dynamic';
// artha-v2/frontend/app/connect/page.tsx
// Onboarding wizard: Choose platform → Connect Shopify OR WooCommerce → Connect Razorpay

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Step = "org" | "platform" | "shopify" | "woocommerce" | "razorpay" | "done";
type Platform = "shopify" | "woocommerce";

const STEP_LABELS: Record<Step, string> = {
  org: "Brand",
  platform: "Platform",
  shopify: "Shopify",
  woocommerce: "WooCommerce",
  razorpay: "Razorpay",
  done: "Done",
};

const WIZARD_STEPS_SHOPIFY: Step[] = ["org", "platform", "shopify", "razorpay", "done"];
const WIZARD_STEPS_WOO: Step[]     = ["org", "platform", "woocommerce", "razorpay", "done"];

export default function ConnectPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("org");
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Org
  const [orgName, setOrgName] = useState("");

  // Shopify
  const [shopDomain, setShopDomain] = useState("");
  const [shopToken, setShopToken] = useState("");

  // WooCommerce
  const [wooUrl, setWooUrl] = useState("");
  const [wooKey, setWooKey] = useState("");
  const [wooSecret, setWooSecret] = useState("");

  // Razorpay
  const [rpKeyId, setRpKeyId] = useState("");
  const [rpKeySecret, setRpKeySecret] = useState("");
  const [rpWebhook, setRpWebhook] = useState("");

  const steps = platform === "woocommerce" ? WIZARD_STEPS_WOO : WIZARD_STEPS_SHOPIFY;
  const stepIdx = steps.indexOf(step);

  async function handleOrg(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.createOrg(orgName);
      setStep("platform");
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Failed"); }
    setLoading(false);
  }

  function handlePlatformChoice(p: Platform) {
    setPlatform(p);
    setStep(p);
  }

  async function handleShopify(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const domain = shopDomain.replace(/^https?:\/\//, "").replace(/\/$/, "");
      await api.connectShopify(domain, shopToken);
      setStep("razorpay");
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Shopify connection failed"); }
    setLoading(false);
  }

  async function handleWooCommerce(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.connectWooCommerce(wooUrl, wooKey, wooSecret);
      setStep("razorpay");
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "WooCommerce connection failed"); }
    setLoading(false);
  }

  async function handleRazorpay(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.connectRazorpay(rpKeyId, rpKeySecret, rpWebhook || undefined);
      setStep("done");
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Razorpay connection failed"); }
    setLoading(false);
  }

  const visibleStepLabels = steps.map(s => STEP_LABELS[s]);

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-10 w-full max-w-lg">

        {/* Progress bar */}
        <div className="flex items-center mb-8 overflow-x-auto">
          {visibleStepLabels.map((label, i) => (
            <div key={label} className="flex items-center flex-shrink-0">
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                i < stepIdx ? "bg-blue-600 text-white" :
                i === stepIdx ? "bg-blue-600 text-white ring-4 ring-blue-100" :
                "bg-slate-100 text-slate-400"
              }`}>
                {i < stepIdx ? "✓" : i + 1}
              </div>
              <span className={`ml-1.5 text-xs whitespace-nowrap ${i === stepIdx ? "text-slate-900 font-semibold" : "text-slate-400"}`}>
                {label}
              </span>
              {i < visibleStepLabels.length - 1 && (
                <div className={`w-6 h-0.5 mx-2 flex-shrink-0 ${i < stepIdx ? "bg-blue-600" : "bg-slate-200"}`} />
              )}
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-5 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        {/* Step: Org */}
        {step === "org" && (
          <form onSubmit={handleOrg} className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-slate-900 mb-1">Your Brand</h2>
              <p className="text-slate-500 text-sm">What's your D2C brand called?</p>
            </div>
            <input required value={orgName} onChange={e => setOrgName(e.target.value)}
              placeholder="Mamaearth, boAt, etc."
              className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <button disabled={loading} type="submit"
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50">
              {loading ? "Creating..." : "Continue →"}
            </button>
          </form>
        )}

        {/* Step: Platform picker */}
        {step === "platform" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-slate-900 mb-1">Choose Your Store Platform</h2>
              <p className="text-slate-500 text-sm">We'll connect your store to start reconciling with Razorpay.</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <button
                onClick={() => handlePlatformChoice("shopify")}
                className="border-2 border-slate-200 hover:border-green-500 hover:bg-green-50 rounded-xl p-6 text-center transition-all group"
              >
                <div className="text-4xl mb-3">🛍️</div>
                <div className="font-bold text-slate-900 group-hover:text-green-700">Shopify</div>
                <div className="text-xs text-slate-400 mt-1">Admin API token</div>
              </button>
              <button
                onClick={() => handlePlatformChoice("woocommerce")}
                className="border-2 border-slate-200 hover:border-purple-500 hover:bg-purple-50 rounded-xl p-6 text-center transition-all group"
              >
                <div className="text-4xl mb-3">🔧</div>
                <div className="font-bold text-slate-900 group-hover:text-purple-700">WooCommerce</div>
                <div className="text-xs text-slate-400 mt-1">Consumer key + secret</div>
              </button>
            </div>
            <p className="text-center text-xs text-slate-400">You can connect both platforms later from Settings.</p>
          </div>
        )}

        {/* Step: Shopify */}
        {step === "shopify" && (
          <form onSubmit={handleShopify} className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-slate-900 mb-1">Connect Shopify</h2>
              <p className="text-slate-500 text-sm">Read-only access to orders. No PII stored.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Shop domain</label>
              <input required value={shopDomain} onChange={e => setShopDomain(e.target.value)}
                placeholder="your-store.myshopify.com"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Admin API access token</label>
              <input required type="password" value={shopToken} onChange={e => setShopToken(e.target.value)}
                placeholder="shpat_..."
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <p className="text-xs text-slate-400 mt-1">Fernet-encrypted before storage. Never stored in plaintext.</p>
            </div>
            <button disabled={loading} type="submit"
              className="w-full bg-green-600 hover:bg-green-700 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50">
              {loading ? "Verifying..." : "Connect Shopify →"}
            </button>
            <button type="button" onClick={() => setStep("platform")} className="w-full text-slate-400 text-sm hover:text-slate-600">
              ← Back
            </button>
          </form>
        )}

        {/* Step: WooCommerce */}
        {step === "woocommerce" && (
          <form onSubmit={handleWooCommerce} className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-slate-900 mb-1">Connect WooCommerce</h2>
              <p className="text-slate-500 text-sm">Generate REST API keys in WooCommerce → Settings → Advanced → REST API.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Store URL</label>
              <input required value={wooUrl} onChange={e => setWooUrl(e.target.value)}
                placeholder="https://yourstore.com"
                type="url"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Consumer Key</label>
              <input required value={wooKey} onChange={e => setWooKey(e.target.value)}
                placeholder="ck_xxxxxxxxxxxx"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Consumer Secret</label>
              <input required type="password" value={wooSecret} onChange={e => setWooSecret(e.target.value)}
                placeholder="cs_xxxxxxxxxxxx"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <p className="text-xs text-slate-400 mt-1">Set permissions to <strong>Read</strong> only. Fernet-encrypted before storage.</p>
            </div>
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-xs text-purple-700">
              <strong>Note:</strong> Make sure your WooCommerce store uses Razorpay for Indian payments. The Razorpay WooCommerce plugin must be installed for full reconciliation.
            </div>
            <button disabled={loading} type="submit"
              className="w-full bg-purple-600 hover:bg-purple-700 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50">
              {loading ? "Verifying..." : "Connect WooCommerce →"}
            </button>
            <button type="button" onClick={() => setStep("platform")} className="w-full text-slate-400 text-sm hover:text-slate-600">
              ← Back
            </button>
          </form>
        )}

        {/* Step: Razorpay */}
        {step === "razorpay" && (
          <form onSubmit={handleRazorpay} className="space-y-5">
            <div>
              <h2 className="text-xl font-bold text-slate-900 mb-1">Connect Razorpay</h2>
              <p className="text-slate-500 text-sm">Read-only payment data for reconciliation.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Key ID</label>
              <input required value={rpKeyId} onChange={e => setRpKeyId(e.target.value)}
                placeholder="rzp_live_..."
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Key Secret</label>
              <input required type="password" value={rpKeySecret} onChange={e => setRpKeySecret(e.target.value)}
                placeholder="Key secret"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Webhook Secret <span className="text-slate-400">(optional)</span></label>
              <input type="password" value={rpWebhook} onChange={e => setRpWebhook(e.target.value)}
                placeholder="Webhook secret"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <button disabled={loading} type="submit"
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50">
              {loading ? "Verifying..." : "Connect Razorpay →"}
            </button>
          </form>
        )}

        {/* Step: Done */}
        {step === "done" && (
          <div className="text-center">
            <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <svg className="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-slate-900 mb-2">You're all set!</h2>
            <p className="text-slate-500 mb-2">
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${platform === "woocommerce" ? "bg-purple-100 text-purple-700" : "bg-green-100 text-green-700"}`}>
                {platform === "woocommerce" ? "🔧 WooCommerce" : "🛍️ Shopify"}
              </span>
              {" "}and Razorpay connected.
            </p>
            <p className="text-slate-400 text-sm mb-6">First reconciliation runs tonight at 2 AM IST.</p>
            <button onClick={() => router.push("/dashboard")}
              className="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2.5 px-8 rounded-lg transition-colors">
              Go to Dashboard →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
