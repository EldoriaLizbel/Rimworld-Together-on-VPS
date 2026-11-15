"use client";

import { useState } from "react";
import { Eye, EyeOff, Loader2, Moon, Sun } from "lucide-react";
import { t as c, BRAND } from "../theme";

export default function LoginPage({ isDark, setIsDark, onEnter }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!username.trim() || !password) { setError("Please enter your username and password."); return; }
    setBusy(true); setError("");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { setError(data.error || "Sign-in failed."); setPassword(""); return; }
      onEnter(data.user);
    } catch {
      setError("Can't reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-theme={isDark ? "dark" : "light"} className="rt-shell flex min-h-svh flex-col">
      <a href="#main-content" className="rt-skip">Skip to content</a>
      <header className={`border-b ${c.header}`}>
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-5 py-4 sm:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <img src="/rimworld-icon.png" alt="" width="34" height="34" className="shrink-0 rounded-md" />
            <span className={`text-sm font-semibold ${c.headerTitle}`}>{BRAND.name}</span>
          </div>
          <button type="button" onClick={() => setIsDark(!isDark)}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            className="rt-icon-button">
            {isDark ? <Sun size={19} aria-hidden="true" /> : <Moon size={19} aria-hidden="true" />}
          </button>
        </div>
      </header>

      <main id="main-content" tabIndex={-1} className="mx-auto grid w-full max-w-7xl flex-1 items-center gap-6 p-4 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] md:gap-10 md:p-8">
        <figure className="order-2 md:order-1">
          <div className="rt-login-art">
            <img src="/rimworld-together.png" width={1920} height={1080} loading="lazy" decoding="async"
              className="h-auto w-full" alt="RimWorld Together artwork above a planet" />
          </div>
          <figcaption className={`mt-2 text-xs ${c.muted}`}>
            Artwork by{" "}
            <a className="underline underline-offset-2" href="https://github.com/RimWorld-Together/Rimworld-Together">RimWorld Together contributors</a>
            {" · "}
            <a className="underline underline-offset-2" href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</a>
          </figcaption>
        </figure>

        <section className={`order-1 w-full rounded-xl p-5 sm:p-8 md:order-2 ${c.card}`} aria-labelledby="sign-in-title">
          <h1 id="sign-in-title" className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Server sign-in
          </h1>
          <p className={`mt-2 text-sm ${c.label}`}>Use your server dashboard account.</p>

          <form onSubmit={submit} noValidate aria-busy={busy} className="mt-6 flex flex-col gap-4">
            <label className={`flex flex-col gap-1.5 text-sm font-medium ${c.label}`}>
              Username
              <input name="username" autoComplete="username" required aria-describedby={error ? "login-error" : undefined}
                value={username} onChange={(e) => setUsername(e.target.value)}
                className={`h-11 rounded-lg px-3 text-base ${c.input}`} />
            </label>
            <div>
              <label htmlFor="password" className={`mb-1.5 block text-sm font-medium ${c.label}`}>Password</label>
              <div className="flex gap-2">
                <input id="password" name="password" type={showPassword ? "text" : "password"} autoComplete="current-password" required
                  aria-describedby={error ? "login-error" : undefined}
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  className={`h-11 min-w-0 flex-1 rounded-lg px-3 text-base ${c.input}`} />
                <button type="button" className="rt-icon-button" aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword(!showPassword)}>
                  {showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
                </button>
              </div>
            </div>
            {error && <p id="login-error" role="alert" className={`rounded-lg px-3 py-2 text-sm ${c.error}`}>{error}</p>}
            <button type="submit" disabled={busy} className="rt-button mt-1">
              {busy && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
