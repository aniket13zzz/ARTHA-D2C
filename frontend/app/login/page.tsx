"use client";

import { useState } from "react";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const { error: supabaseError } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/dashboard`,
      },
    });

    if (supabaseError) {
      setError(supabaseError.message);
    } else {
      setSent(true);
    }
    setLoading(false);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-blue-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl p-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600 text-white text-3xl font-bold mb-4">
            ₹
          </div>
          <h1 className="text-3xl font-bold text-slate-900">Artha V2</h1>
          <p className="text-slate-500 text-sm mt-1">Financial Reconciliation Engine</p>
        </div>

        {sent ? (
          <div className="text-center py-8">
            <div className="text-green-600 text-5xl mb-4">✉️</div>
            <h2 className="text-2xl font-semibold text-slate-900 mb-2">Check your email</h2>
            <p className="text-slate-600">
              Magic link sent to <br />
              <strong className="text-slate-900">{email}</strong>
            </p>
            <p className="text-xs text-slate-500 mt-6">
              Didn’t receive it? Check spam folder or try again.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Email address
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full px-4 py-3 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !email}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-3.5 px-4 rounded-xl transition-all duration-200"
            >
              {loading ? "Sending Magic Link..." : "Send Magic Link"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
