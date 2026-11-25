"use client";

import { useState } from "react";
import { AlertCircle, ArrowRight, FileText, Lock, User } from "lucide-react";
import { login, register, type AuthResponse } from "@/lib/api";

type AuthMode = "login" | "register";

export default function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated: (auth: AuthResponse) => void;
}) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    setBusy(true);
    setError(null);

    try {
      const auth =
        mode === "login"
          ? await login(username.trim(), password)
          : await register(username.trim(), password);
      onAuthenticated(auth);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to continue");
      setBusy(false);
    }
  }

  function changeMode(nextMode: AuthMode) {
    setMode(nextMode);
    setError(null);
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(420px,520px)]">
      <section className="hidden flex-col justify-between border-r border-line bg-raised p-10 lg:flex">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-lg border border-line bg-panel">
            <FileText aria-hidden="true" className="size-4 text-accent" strokeWidth={1.75} />
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Marginal</span>
        </div>

        <div className="max-w-md">
          <p className="text-sm text-secondary">Private PDF workspace</p>
          <h1 className="mt-3 text-4xl font-semibold leading-[1.08] tracking-[-0.035em]">
            Ask a question. Keep the page.
          </h1>
          <p className="mt-5 max-w-sm text-[15px] leading-7 text-secondary">
            Marginal indexes your PDFs and returns answers with the passages and page numbers
            behind them.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" />
          Retrieval stays scoped to your account
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex size-9 items-center justify-center rounded-lg border border-line bg-panel">
              <FileText aria-hidden="true" className="size-4 text-accent" strokeWidth={1.75} />
            </span>
            <span className="text-[15px] font-semibold tracking-[-0.01em]">Marginal</span>
          </div>

          <p className="text-sm text-secondary">Workspace access</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-[-0.025em]">
            {mode === "login" ? "Sign in" : "Create an account"}
          </h2>

          <div className="mt-6 grid grid-cols-2 gap-1 rounded-lg border border-line bg-raised p-1">
            <button
              type="button"
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                mode === "login" ? "bg-panel text-ink" : "text-secondary"
              }`}
              aria-pressed={mode === "login"}
              onClick={() => changeMode("login")}
            >
              Sign in
            </button>
            <button
              type="button"
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                mode === "register" ? "bg-panel text-ink" : "text-secondary"
              }`}
              aria-pressed={mode === "register"}
              onClick={() => changeMode("register")}
            >
              Register
            </button>
          </div>

          <form className="mt-6 grid gap-4" onSubmit={handleSubmit}>
            <div className="grid gap-2">
              <label htmlFor="username" className="text-sm font-medium text-secondary">
                Username
              </label>
              <div className="relative">
                <User
                  aria-hidden="true"
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted"
                  strokeWidth={1.75}
                />
                <input
                  id="username"
                  name="username"
                  className="field pl-9"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  spellCheck={false}
                  required
                />
              </div>
            </div>

            <div className="grid gap-2">
              <label htmlFor="password" className="text-sm font-medium text-secondary">
                Password
              </label>
              <div className="relative">
                <Lock
                  aria-hidden="true"
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted"
                  strokeWidth={1.75}
                />
                <input
                  id="password"
                  name="password"
                  type="password"
                  className="field pl-9"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                />
              </div>
            </div>

            <div aria-live="polite" aria-atomic="true" className="min-h-5 text-sm">
              {error ? (
                <span className="flex items-start gap-2 text-negative">
                  <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
                  {error}
                </span>
              ) : null}
            </div>

            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Connecting…" : mode === "login" ? "Sign in" : "Create account"}
              <ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.75} />
            </button>
          </form>

          <p className="mt-6 text-xs leading-5 text-muted">
            Your access token is stored in this browser only.
          </p>
        </div>
      </section>
    </div>
  );
}
