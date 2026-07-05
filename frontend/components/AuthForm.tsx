"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, authApi } from "@/lib/api";

/**
 * Shared email/password form for login and signup. On success it navigates to
 * the app root; the httpOnly session cookie is set by the backend.
 */
export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (isSignup) await authApi.signup(email, password, name);
      else await authApi.login(email, password);
      // Hard navigation (not router.push) so the middleware re-runs with the
      // freshly-set session cookie and the app shell loads cleanly.
      window.location.assign("/");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <h1 className="text-2xl font-semibold text-ink">
        {isSignup ? "Create your account" : "Welcome back"}
      </h1>
      <p className="mt-1 text-sm text-ink-dim">
        {isSignup
          ? "Upload your data and start asking questions in plain language."
          : "Sign in to your analytics workspace."}
      </p>

      <form onSubmit={submit} className="mt-6 space-y-3">
        {isSignup && (
          <input
            className="w-full rounded-[var(--radius-card)] border border-hairline bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-hairline-strong"
            placeholder="Name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
          />
        )}
        <input
          className="w-full rounded-[var(--radius-card)] border border-hairline bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-hairline-strong"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
        <input
          className="w-full rounded-[var(--radius-card)] border border-hairline bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-hairline-strong"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={isSignup ? "new-password" : "current-password"}
          minLength={8}
          required
        />

        {error && <p className="text-sm text-[var(--color-err)]">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-[var(--radius-card)] bg-electric px-3 py-2 text-sm font-medium text-bg disabled:opacity-60"
        >
          {busy ? "…" : isSignup ? "Create account" : "Sign in"}
        </button>
      </form>

      <p className="mt-4 text-sm text-ink-dim">
        {isSignup ? "Already have an account? " : "New here? "}
        <Link
          href={isSignup ? "/login" : "/signup"}
          className="text-ink underline underline-offset-2"
        >
          {isSignup ? "Sign in" : "Create an account"}
        </Link>
      </p>
    </div>
  );
}
