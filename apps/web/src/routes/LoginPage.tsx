import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { ApiError } from "@/api/client";

export function LoginPage() {
  const { user, loading, login } = useAuth();
  const [email, setEmail] = useState("publisher@demo.example.com");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center px-4">
      <div className="mh-panel animate-rise p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Local development</p>
        <h1 className="mt-2 font-display text-4xl font-semibold text-ink-950">MaintenanceHub</h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-600">
          Sign in to see planned maintenance, confirmed windows, and manually reported outages.
          This is not a monitoring console.
        </p>
        <form className="mt-8 space-y-4" onSubmit={onSubmit}>
          <div>
            <label className="mh-label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              className="mh-input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mh-label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              className="mh-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && (
            <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          <button className="mh-btn w-full" type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="mt-6 rounded-lg border border-dashed border-ink-200 bg-ink-50/70 p-3 text-xs text-ink-600">
          <p className="font-semibold text-ink-800">[DEMO] seeded users</p>
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            <li>viewer@demo.example.com / password123</li>
            <li>publisher@demo.example.com / password123</li>
            <li>admin@demo.example.com / password123</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
