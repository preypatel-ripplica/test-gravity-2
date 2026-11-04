import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { lazyRetry } from "./lib/lazy";
import { useStore } from "./store";
import { Icon } from "./lib/ui";
import SelectionBar from "./components/SelectionBar";
import SettingsModal from "./components/SettingsModal";
const SendTemplateModal = lazyRetry(() => import("./components/SendTemplateModal"));
import Toast from "./components/Toast";
import Login from "./pages/Login";
import wordmark from "./assets/ripplica-wordmark-white.png";
import type { Feature } from "./features";

// The inbox is the product and is always present; everything else is gated by a
// feature flag so a client only sees what we have chosen to expose.
const NAV: { to: string; label: string; icon: "inbox" | "table" | "megaphone" | "doc" | "users" | "phone"; feature?: Feature }[] = [
  { to: "/bot/inbox", label: "Inbox", icon: "inbox" },
  { to: "/bot/leads", label: "Leads", icon: "table", feature: "leads" },
  { to: "/bot/templates", label: "Templates", icon: "doc", feature: "templates" },
  { to: "/bot/broadcasts", label: "Broadcasts", icon: "megaphone", feature: "campaigns" },
  { to: "/bot/contacts", label: "Contacts", icon: "users", feature: "contacts" },
  { to: "/bot/calls", label: "Calls", icon: "phone", feature: "calls" },
];

export default function App() {
  const { client, conversations, theme, toggleTheme, sound, toggleSound, remote, authed, loading, apiDown, features, sidebarCollapsed, toggleSidebar, templateTarget } = useStore();
  const [settings, setSettings] = useState(false);
  const needsLogin = remote && !authed;
  const clientName = client.name;
  const unread = conversations.reduce((n, c) => n + c.unread_count, 0);
  const nav = NAV.filter((n) => !n.feature || features[n.feature]);
  // The inbox has its own search in the conversation list, so the global one is
  // redundant there. With it gone the desktop header holds nothing at all.
  const { pathname } = useLocation();
  // An open chat owns the whole screen on a phone, like any messaging app: its
  // own header carries back, the contact and the menu.
  const chatOpen = /^\/bot\/inbox\/[^/]+/.test(pathname);

  // Unread count in the browser tab title (the current inbox lacks this).
  useEffect(() => { document.title = unread > 0 ? `(${unread}) ${clientName} · Ripplica` : `${clientName} · Ripplica`; }, [unread, clientName]);

  // Installed on a phone the status bar is painted from this meta, so keep it on
  // the active theme instead of frozen at whatever the manifest declared.
  useEffect(() => {
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", theme === "dark" ? "#0b0e14" : "#f6f7f9"));
  }, [theme]);

  // Desktop only: a phone shows just the inbox, with no nav at all.
  const navItem = (n: (typeof NAV)[number]) => (
    <NavLink key={n.to} to={n.to} title={sidebarCollapsed ? n.label : undefined} className={({ isActive }) =>
      `relative flex items-center rounded-md py-2 text-[13.5px] transition-colors ${sidebarCollapsed ? "justify-center px-0" : "gap-2.5 px-2.5"} ${isActive ? "bg-accent/15 text-ink" : "text-muted hover:bg-panel2 hover:text-ink"}`}>
      {({ isActive }) => (<>
        <Icon name={n.icon} size={20} className={isActive ? "text-accent" : ""} />
        {!sidebarCollapsed && n.label}
        {n.to === "/bot/inbox" && unread > 0 && (sidebarCollapsed
          ? <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-emerald-500" />
          : <span className="ml-auto rounded-full bg-emerald-500 px-1.5 text-[10px] font-semibold text-white tabular-nums">{unread}</span>)}
      </>)}
    </NavLink>
  );

  if (needsLogin) return <Login />;

  return (
    <div className="flex h-dvh w-screen overflow-hidden bg-bg text-ink">
      {loading && <div className="pointer-events-none fixed inset-x-0 top-0 z-[90] h-0.5 overflow-hidden bg-accent/20"><div className="h-full w-1/3 animate-[loadbar_1.2s_ease-in-out_infinite] bg-accent" /></div>}
      {apiDown && !loading && <div className="fixed inset-x-0 top-0 z-[90] bg-amber-500 px-3 py-1 text-center text-[11.5px] font-medium text-black">Connection lost — reconnecting…</div>}
      {/* Sidebar (desktop) */}
      <aside className={`hidden shrink-0 flex-col overflow-hidden border-r border-line bg-panel py-3 transition-[width] duration-150 md:flex ${sidebarCollapsed ? "w-14 px-2" : "w-56 px-3"}`}>
        <div className={`mb-4 flex items-center py-1 ${sidebarCollapsed ? "justify-center" : "px-1.5"}`}>
          {sidebarCollapsed
            ? <span className="block h-7 w-7 overflow-hidden" title="Ripplica"><img src={wordmark} alt="Ripplica" className="brand-mark h-7 max-w-none" /></span>
            : <img src={wordmark} alt="Ripplica" className="brand-mark h-6" />}
        </div>
        {!sidebarCollapsed && <div className="mb-1 px-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">Workspace</div>}
        <nav className="flex flex-col gap-0.5">{nav.map((n) => navItem(n))}</nav>
        <div className={`mt-auto flex items-center gap-1 pb-2 ${sidebarCollapsed ? "flex-col" : ""}`}>
          <button onClick={toggleSound} title={sound ? "Notification sound on" : "Notification sound off"} className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name={sound ? "bell" : "bellOff"} size={16} /></button>
          <button onClick={toggleTheme} title="Toggle theme" className="grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name={theme === "dark" ? "sun" : "moon"} size={16} /></button>
          <button onClick={toggleSidebar} title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} className={`grid h-8 w-8 place-items-center rounded-lg border border-line text-muted hover:text-ink ${sidebarCollapsed ? "" : "ml-auto"}`}>
            <Icon name="chevron" size={16} className={`transition-transform ${sidebarCollapsed ? "" : "rotate-180"}`} />
          </button>
        </div>
        <button onClick={() => setSettings(true)} className={`flex items-center rounded-lg border border-line bg-panel2 text-left hover:border-accent/40 ${sidebarCollapsed ? "justify-center px-0 py-2" : "gap-2 px-2.5 py-2"}`} title={sidebarCollapsed ? `${clientName} · Settings` : "Client settings"}>
          <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent/15 text-[11px] font-semibold text-accent">{clientName.split(" ").map((w) => w[0]).slice(0, 2).join("")}</div>
          {!sidebarCollapsed && (<>
            <div className="min-w-0 flex-1"><div className="truncate text-[12.5px] font-medium text-ink">{clientName}</div><div className="text-[10.5px] text-muted">Settings</div></div>
            <Icon name="chevron" size={14} className="shrink-0 text-muted" />
          </>)}
        </button>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className={`h-14 shrink-0 items-center gap-2 border-b border-line bg-panel px-3 ${chatOpen ? "hidden" : "flex md:hidden"}`}>
          <button onClick={() => setSettings(true)} className="flex shrink-0 items-center gap-1.5 rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-[12.5px] font-medium md:hidden" title="Client settings">{clientName}<Icon name="chevron" size={13} className="text-muted" /></button>
          {/* Phone only: the sidebar that normally carries these is desktop-only. */}
          <div className="ml-auto flex items-center gap-1.5 md:hidden">
            <button onClick={toggleSound} title={sound ? "Notification sound on" : "Notification sound off"} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name={sound ? "bell" : "bellOff"} size={16} /></button>
            <button onClick={toggleTheme} title="Toggle theme" className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-line text-muted hover:text-ink"><Icon name={theme === "dark" ? "sun" : "moon"} size={16} /></button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden"><Outlet /></main>

        {/* Phone: Inbox / Leads tabs (an open chat owns the whole screen). */}
        {features.leads && (
          <nav className={`${chatOpen ? "hidden" : "flex"} shrink-0 border-t border-line bg-panel pb-[env(safe-area-inset-bottom)] md:hidden`}>
            {nav.filter((n) => n.to === "/bot/inbox" || n.to === "/bot/leads").map((n) => (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => `relative flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium ${isActive ? "text-accent" : "text-muted"}`}>
                <Icon name={n.icon} size={20} />{n.label}
                {n.to === "/bot/inbox" && unread > 0 && <span className="absolute right-[calc(50%-1.75rem)] top-2 rounded-full bg-emerald-500 px-1.5 text-[10px] font-semibold text-white tabular-nums">{unread}</span>}
              </NavLink>
            ))}
          </nav>
        )}

      </div>

      <SettingsModal open={settings} onClose={() => setSettings(false)} />
      {templateTarget && <Suspense fallback={null}><SendTemplateModal /></Suspense>}
      <SelectionBar />
      <Toast />
    </div>
  );
}
