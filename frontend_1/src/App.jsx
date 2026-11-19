"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, Database, Loader2, LogOut, Moon, RadioTower, Settings2, Sun, Users } from "lucide-react";
import ServerData from "./views/ServerData";
import LoginPage from "./views/LoginPage";
import ConfigurePage from "./views/ConfigurePage";
import { ServerOverview, WorkerDashboard, GameConfig } from "./views/GamePage";
import { t } from "./theme";

const pages = [
  { id: "overview", label: "Server overview", short: "Overview", Icon: RadioTower },
  { id: "worker", label: "Worker", short: "Worker", Icon: Activity, admin: true },
  { id: "accounts", label: "Player accounts", short: "Accounts", Icon: Users, admin: true },
  { id: "config", label: "Config server", short: "Config", Icon: Settings2, admin: true },
  { id: "data", label: "Server data", short: "Data", Icon: Database, admin: true },
];

function currentView() {
  return new URLSearchParams(window.location.search).get("view") || "overview";
}

export default function App() {
  const [dark, setDark] = useState(true);
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [view, setView] = useState("overview");
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");
  const heading = useRef(null);
  const focusHeading = useRef(false);
  const admin = user?.role === "superuser";
  const available = pages.filter((page) => !page.admin || admin);
  const active = available.find((page) => page.id === view) || pages[0];
  const c = t;
  const mode = dark ? "dark" : "light";

  async function refreshMe() {
    try {
      const response = await fetch("/api/auth/me", { cache: "no-store" });
      setUser(response.ok ? (await response.json()).user : null);
    } catch {
      setUser(null);
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    refreshMe();
    const sync = () => setView(currentView());
    sync();
    window.addEventListener("popstate", sync);
    try {
      const saved = localStorage.getItem("rwt-theme");
      if (saved === "light" || saved === "dark") setDark(saved === "dark");
    } catch {}
    return () => window.removeEventListener("popstate", sync);
  }, []);

  useEffect(() => {
    if (focusHeading.current) {
      heading.current?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
      focusHeading.current = false;
    }
  }, [active.id]);

  function changeTheme(next) {
    setDark(next);
    try { localStorage.setItem("rwt-theme", next ? "dark" : "light"); } catch {}
  }

  function navigate(event, page) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    if (page.id === active.id) return;
    focusHeading.current = true;
    window.history.pushState(null, "", event.currentTarget.href);
    setView(page.id);
  }

  async function signOut() {
    setSigningOut(true);
    setError("");
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error();
      setUser(null);
    } catch {
      setError("Could not sign out. Please try again.");
    } finally {
      setSigningOut(false);
    }
  }

  if (checking) {
    return (
      <div data-theme={mode} className="rt-shell grid min-h-svh place-items-center">
        <p role="status" className="flex items-center gap-2 text-sm">
          <Loader2 size={18} aria-hidden="true" className="animate-spin" /> Checking session…
        </p>
      </div>
    );
  }

  if (!user) {
    return <LoginPage isDark={dark} setIsDark={changeTheme} onEnter={setUser} />;
  }

  return (
    <div className="rt-shell min-h-svh" data-theme={mode}>
      <a href="#main-content" className="rt-skip">Skip to content</a>
      <div className="rt-layout">
        <aside className="rt-sidebar">
          <div className="rt-brand">
            <img src="/rimworld-icon.png" alt="" width="32" height="32" />
            <span>RimWorld Together<br /><small>Server dashboard</small></span>
          </div>
          <nav aria-label="Main navigation" className="rt-navigation">
            {available.map((page) => (
              <a key={page.id} href={page.id === "overview" ? "/" : `/?view=${page.id}`}
                onClick={(event) => navigate(event, page)}
                aria-current={active.id === page.id ? "page" : undefined}
                aria-label={page.label}>
                <page.Icon size={18} strokeWidth={1.8} aria-hidden="true" />
                <span className="lg:hidden">{page.short}</span>
                <span className="hidden lg:inline">{page.label}</span>
              </a>
            ))}
          </nav>
        </aside>
        <main id="main-content" className="rt-main" tabIndex={-1}>
          <header className={`rt-page-header${active.id === "worker" ? " rt-worker-header" : ""}`}>
            <h1 ref={heading} tabIndex={-1}>{active.label}</h1>
            <div className="rt-session">
              <span className="hidden min-w-0 text-right sm:block">
                <strong className="block break-all text-sm">{user.nickname || user.username}</strong>
                <span className={`text-xs ${c.label}`}>{admin ? "Super-user" : "Player"}</span>
              </span>
              <button type="button" className="rt-icon-button" onClick={() => changeTheme(!dark)}
                aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
                {dark ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
              </button>
              <button type="button" className="rt-icon-button" onClick={signOut} disabled={signingOut} aria-label="Sign out">
                <LogOut size={18} aria-hidden="true" />
              </button>
            </div>
          </header>
          {error && <p role="alert" className={`mb-4 rounded-md px-3 py-2 text-sm ${c.error}`}>{error}</p>}
          {active.id === "overview" && <ServerOverview c={c} isAdmin={admin} />}
          {active.id === "worker" && <WorkerDashboard c={c} />}
          {active.id === "config" && <GameConfig c={c} />}
          {active.id === "data" && <ServerData c={c} />}
          {active.id === "accounts" && <ConfigurePage c={c} me={user} onSelfChanged={refreshMe} />}
        </main>
      </div>
    </div>
  );
}
