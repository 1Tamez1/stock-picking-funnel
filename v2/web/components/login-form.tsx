"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { ApiError, loginSession } from "../lib/api";

export function LoginForm() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/dashboard";
  const expired = searchParams.get("expired") === "1";
  const reason = searchParams.get("reason") || "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await loginSession({ email, password });
      window.location.assign(next);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel login-card">
      <p className="eyebrow">Owner Access</p>
      <h1>Sign in</h1>
      <p className="muted">
        This hosted app uses a single owner account. Sign in with the bootstrapped owner credentials to access the routed
        workspace.
      </p>
      {expired ? <p className="status-banner">Your session expired or was revoked. Sign in again to continue.</p> : null}
      {!expired && reason === "auth" ? (
        <p className="status-banner">Sign in to continue into the protected hosted workspace.</p>
      ) : null}
      <form className="stacked-form" onSubmit={handleSubmit}>
        <label>
          Email
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error ? <p className="error-banner">{error}</p> : null}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </section>
  );
}
