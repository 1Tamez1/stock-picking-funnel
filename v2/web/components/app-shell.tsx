"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { logoutSession } from "../lib/api";
import type { CutoverState } from "../lib/runtime-state";
import type { WriteFreezeState } from "../lib/runtime-state";

const PRIMARY_NAV = [
  ["/dashboard", "dashboard", "Dashboard"],
  ["/pool", "pool", "All Companies"],
  ["/funnel", "funnel", "Funnel"],
  ["/reports", "reports", "Reports"],
  ["/monitoring", "monitoring", "Monitoring"],
  ["/watchlist", "watchlist", "Watchlist"],
  ["/archive", "archive", "Archive"],
] as const;

function resolveViewMeta(pathname: string): { eyebrow: string; title: string } {
  if (pathname === "/dashboard" || pathname.startsWith("/__legacy/dashboard")) {
    return { eyebrow: "Research Control", title: "Dashboard" };
  }
  if (pathname === "/pool" || pathname.startsWith("/__legacy/pool")) {
    return { eyebrow: "Research Universe", title: "All Companies" };
  }
  if (pathname === "/funnel" || pathname.startsWith("/__legacy/funnel")) {
    return { eyebrow: "Active Research", title: "Funnel" };
  }
  if (pathname === "/reports" || pathname.startsWith("/__legacy/reports")) {
    return { eyebrow: "Cross-Company Research", title: "Reports" };
  }
  if (pathname.startsWith("/reports/") || pathname.startsWith("/__legacy/reports/")) {
    return { eyebrow: "Report Workspace", title: "Report Workspace" };
  }
  if (pathname === "/monitoring" || pathname.startsWith("/__legacy/monitoring")) {
    return { eyebrow: "Rules and Alerts", title: "Monitoring" };
  }
  if (pathname === "/watchlist" || pathname.startsWith("/__legacy/watchlist")) {
    return { eyebrow: "Deferred Candidates", title: "Watchlist" };
  }
  if (pathname === "/archive" || pathname.startsWith("/__legacy/archive")) {
    return { eyebrow: "Rejected or Paused", title: "Archive" };
  }
  if (pathname === "/templates" || pathname.startsWith("/__legacy/templates")) {
    return { eyebrow: "Editable Research Forms", title: "Templates" };
  }
  if (pathname === "/companies") {
    return { eyebrow: "Research Universe", title: "Companies" };
  }
  if (pathname.startsWith("/companies/") || pathname.startsWith("/__legacy/companies/")) {
    return { eyebrow: "Company Page", title: "Company Page" };
  }
  return { eyebrow: "Research Control", title: "Dashboard" };
}

export function AppShell({
  children,
  writeFreeze,
  cutoverState,
}: {
  children: ReactNode;
  writeFreeze: WriteFreezeState;
  cutoverState: CutoverState;
}) {
  const pathname = usePathname();
  const drawerAnchorRef = useRef<HTMLButtonElement | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const viewMeta = useMemo(() => resolveViewMeta(pathname), [pathname]);
  const banner = useMemo(() => {
    if (writeFreeze.writeFrozen && writeFreeze.message) return writeFreeze.message;
    if (writeFreeze.writeFrozen) return "Writes are temporarily frozen while hosted maintenance runs.";
    if (cutoverState.cutbackRequired && cutoverState.message) return cutoverState.message;
    if (cutoverState.phase !== "idle" && cutoverState.message) return cutoverState.message;
    return "";
  }, [cutoverState, writeFreeze]);
  const sidebarOpen = !sidebarCollapsed;

  useEffect(() => {
    if (pathname === "/login") return;
    const stored = window.localStorage.getItem("sidebar-collapsed");
    setSidebarCollapsed(stored === null ? true : stored === "1");
  }, [pathname]);

  useEffect(() => {
    if (pathname === "/login") return;
    document.body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
    document.body.classList.toggle("sidebar-open", !sidebarCollapsed);
    return () => {
      document.body.classList.remove("sidebar-collapsed", "sidebar-open");
    };
  }, [pathname, sidebarCollapsed]);

  useEffect(() => {
    if (pathname === "/login") return;

    const syncSidebarToggleAlignment = () => {
      document.body.classList.toggle("page-at-top", window.scrollY <= 4);
      const node = drawerAnchorRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      document.documentElement.style.setProperty("--drawer-toggle-anchor-top", `${Math.round(rect.top)}px`);
      document.documentElement.style.setProperty("--drawer-toggle-anchor-left", `${Math.round(rect.left)}px`);
      document.documentElement.style.setProperty("--drawer-toggle-anchor-width", `${Math.round(rect.width)}px`);
      document.documentElement.style.setProperty("--drawer-toggle-anchor-height", `${Math.round(rect.height)}px`);
    };

    syncSidebarToggleAlignment();
    window.addEventListener("scroll", syncSidebarToggleAlignment, { passive: true });
    window.addEventListener("resize", syncSidebarToggleAlignment);
    return () => {
      window.removeEventListener("scroll", syncSidebarToggleAlignment);
      window.removeEventListener("resize", syncSidebarToggleAlignment);
    };
  }, [pathname, sidebarCollapsed]);

  useEffect(() => {
    setSettingsOpen(false);
  }, [pathname]);

  if (pathname === "/login") {
    return (
      <main className="login-shell">
        {banner ? <section className="panel maintenance-banner">{banner}</section> : null}
        {children}
      </main>
    );
  }

  async function handleLogout() {
    try {
      await logoutSession();
    } finally {
      window.location.assign("/login");
    }
  }

  function toggleSidebar() {
    setSidebarCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("sidebar-collapsed", next ? "1" : "0");
      return next;
    });
  }

  function closeSidebar() {
    if (sidebarCollapsed) return;
    setSidebarCollapsed(true);
    window.localStorage.setItem("sidebar-collapsed", "1");
  }

  return (
    <>
      <div className="sidebar-backdrop" id="sidebar-backdrop" aria-hidden={sidebarOpen ? "false" : "true"} onClick={closeSidebar} />
      <div className="app-shell">
        <aside className="sidebar" id="app-sidebar">
          <div className="brand">
            <div className="brand-copy">
              <p className="eyebrow">Value Research</p>
              <h1>Stock Picking Funnel</h1>
            </div>
            <button
              className="icon-button drawer-toggle"
              id="drawer-sidebar-toggle"
              aria-label="Close navigation"
              aria-controls="app-sidebar"
              aria-expanded={sidebarOpen ? "true" : "false"}
              type="button"
              onClick={toggleSidebar}
            >
              ☰
            </button>
          </div>

          <nav className="nav" aria-label="Primary navigation">
            {PRIMARY_NAV.map(([href, viewKey, label]) => {
              const active = pathname === href || pathname.startsWith(`${href}/`) || pathname.startsWith(`/__legacy/${viewKey}`);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`nav-button ${active ? "active" : ""}`}
                  onClick={closeSidebar}
                >
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="sidebar-footer">
            <div className="sidebar-note">
              <strong>Hosted V2</strong>
              <span>Preserved backend logic with routed web access, legacy fallbacks, and authenticated owner workflows.</span>
            </div>
            <button className="nav-button settings-button" id="settings-button" type="button" onClick={() => setSettingsOpen(true)}>
              Settings
            </button>
            <button className="nav-button settings-button" type="button" onClick={() => void handleLogout()}>
              Log Out
            </button>
          </div>
        </aside>

        <main className="workspace">
          <header className="topbar">
            <div>
              <p className="eyebrow" id="view-eyebrow">
                {viewMeta.eyebrow}
              </p>
              <h2 id="view-title">{viewMeta.title}</h2>
            </div>
            <div className="topbar-actions">
              <button
                ref={drawerAnchorRef}
                className="secondary icon-button"
                id="main-sidebar-toggle"
                aria-label="Toggle navigation"
                aria-controls="app-sidebar"
                aria-expanded={sidebarOpen ? "true" : "false"}
                type="button"
                onClick={toggleSidebar}
              >
                ☰
              </button>
            </div>
          </header>

          <section id="status" className={`status ${banner ? "status-visible" : ""}`} aria-live="polite">
            {banner ? <div className="status-banner status-inline-banner">{banner}</div> : null}
          </section>
          <section id="content" className="content">
            {children}
          </section>
        </main>
      </div>

      <dialog id="settings-dialog" className="modal" open={settingsOpen}>
        <div className="modal-box settings-box">
          <div className="modal-header">
            <div>
              <p className="eyebrow">Workspace Settings</p>
              <h3>Settings</h3>
            </div>
            <button className="icon-button" type="button" data-close-settings aria-label="Close" onClick={() => setSettingsOpen(false)}>
              ×
            </button>
          </div>
          <section id="settings-panel" className="settings-panel">
            <section className="metric-grid settings-summary-grid">
              <article className="metric-card">
                <span className="muted">Routed Surface</span>
                <strong>V2</strong>
              </article>
              <article className="metric-card">
                <span className="muted">Fallbacks</span>
                <strong>On</strong>
              </article>
              <article className="metric-card">
                <span className="muted">Auth</span>
                <strong>Owner</strong>
              </article>
            </section>
            <div className="button-row settings-actions">
              <Link href="/templates" className="secondary" onClick={() => setSettingsOpen(false)}>
                Open Templates
              </Link>
              <Link href="/companies" className="secondary" onClick={() => setSettingsOpen(false)}>
                Open Companies
              </Link>
            </div>
          </section>
        </div>
      </dialog>
    </>
  );
}
