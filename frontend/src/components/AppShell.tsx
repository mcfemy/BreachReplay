import { useState } from "react";
import { NavLink, useNavigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/auth";
import OnboardingModal from "./OnboardingModal";

const NAV = [
  { to: "/scenarios", label: "Scenarios", icon: "⚡", desc: "Library" },
  { to: "/daily", label: "Daily Breach", icon: "🔐", desc: "One shot daily" },
  { to: "/redteam", label: "Red Team", icon: "🔴", desc: "Play attacker" },
  { to: "/arena", label: "Arena", icon: "⚔️", desc: "Live PvP / vs AI" },
  { to: "/leaderboard", label: "Leaderboard", icon: "🏆", desc: "Global XP ranking" },
  { to: "/teams", label: "Teams", icon: "👥", desc: "Org team mode" },
  { to: "/org-upload", label: "Org Upload", icon: "🏢", desc: "Private scenarios" },
  { to: "/settings", label: "My Certs", icon: "🎓", desc: "Credentials & profile" },
];

const BOTTOM_NAV = [
  { to: "/settings", label: "Profile", icon: "👤" },
  { to: "/pricing", label: "Pricing", icon: "💳" },
];

// This is the first responsive breakpoint pattern in the codebase — no
// existing collapsible-sidebar/bottom-sheet convention to match (confirmed
// while scoping Item 5's mobile action console; see docs/BACKLOG.md). The
// sidebar stays exactly as-is at md: and up (unchanged desktop behavior);
// below md: it becomes a slide-in drawer behind a hamburger button, so it
// stops permanently eating ~half of a phone-width viewport — this was
// blocking Phase 2's "phone-with-one-thumb playability" acceptance
// criterion for every authenticated page, not just the new action console.
export default function AppShell() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  const closeMobileNav = () => setMobileNavOpen(false);

  return (
    <div className="flex min-h-screen bg-breach-bg">
      {/* Mobile top bar — hamburger + brand, hidden at md: and up where the
          sidebar is always visible instead. Fixed so it stays reachable
          one-thumb while scrolling page content underneath. */}
      <div className="md:hidden fixed top-0 inset-x-0 z-30 flex items-center justify-between px-4 py-3 border-b border-breach-border bg-breach-surface">
        <button
          onClick={() => setMobileNavOpen(true)}
          aria-label="Open menu"
          className="text-breach-text text-xl leading-none px-1 active:scale-95"
        >
          ☰
        </button>
        <div className="flex items-center gap-1.5">
          <span className="text-breach-accent text-sm font-black tracking-tight">BREACH</span>
          <span className="text-breach-text text-sm font-black tracking-tight">REPLAY</span>
        </div>
        <div className="w-6" aria-hidden="true" />
      </div>

      {/* Backdrop — mobile only, dismisses the drawer on tap outside it */}
      {mobileNavOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/60 z-40"
          onClick={closeMobileNav}
          aria-hidden="true"
        />
      )}

      {/* Sidebar — unchanged, always-visible layout at md:+; below that,
          a fixed slide-in drawer toggled by mobileNavOpen. */}
      <aside
        className={`w-64 md:w-52 shrink-0 flex flex-col border-r border-breach-border bg-breach-surface
          fixed md:static inset-y-0 left-0 z-50 md:z-auto
          transition-transform duration-200 md:transition-none
          ${mobileNavOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
      >
        {/* Brand */}
        <div className="px-4 py-5 border-b border-breach-border flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-breach-accent text-lg font-black tracking-tight">BREACH</span>
              <span className="text-breach-text text-lg font-black tracking-tight">REPLAY</span>
            </div>
            <div className="text-[9px] text-breach-muted uppercase tracking-widest mt-0.5">Cyber Training Platform</div>
          </div>
          <button
            onClick={closeMobileNav}
            aria-label="Close menu"
            className="md:hidden text-breach-muted hover:text-breach-text text-xl leading-none px-1 active:scale-95"
          >
            ✕
          </button>
        </div>

        {/* Main nav */}
        <nav className="flex-1 py-4 px-2 space-y-0.5 overflow-y-auto">
          <div className="px-2 pb-2 text-[9px] text-breach-muted uppercase tracking-widest">Training</div>
          {NAV.map(({ to, label, icon, desc }) => (
            <NavLink
              key={to}
              to={to}
              onClick={closeMobileNav}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2.5 rounded text-xs transition-all group ${
                  isActive
                    ? "bg-breach-accent/10 text-breach-accent border border-breach-accent/20"
                    : "text-breach-muted hover:text-breach-text hover:bg-breach-bg"
                }`
              }
            >
              <span className="text-base leading-none">{icon}</span>
              <div>
                <div className="font-semibold leading-tight">{label}</div>
                <div className="text-[9px] opacity-60 leading-tight">{desc}</div>
              </div>
            </NavLink>
          ))}

          {/* Admin — visible to admins and CISOs */}
          {(user?.role === "admin" || user?.role === "ciso") && (
            <>
              <div className="px-2 pt-4 pb-2 text-[9px] text-breach-muted uppercase tracking-widest">Admin</div>
              <NavLink
                to="/admin"
                onClick={closeMobileNav}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2.5 rounded text-xs transition-all ${
                    isActive
                      ? "bg-purple-500/10 text-purple-400 border border-purple-500/20"
                      : "text-breach-muted hover:text-breach-text hover:bg-breach-bg"
                  }`
                }
              >
                <span className="text-base leading-none">🛡️</span>
                <div>
                  <div className="font-semibold leading-tight">Admin</div>
                  <div className="text-[9px] opacity-60 leading-tight">Dashboard</div>
                </div>
              </NavLink>
            </>
          )}
        </nav>

        {/* Bottom nav */}
        <div className="border-t border-breach-border px-2 py-3 space-y-0.5">
          {BOTTOM_NAV.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={closeMobileNav}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded text-xs transition-all ${
                  isActive
                    ? "bg-breach-accent/10 text-breach-accent"
                    : "text-breach-muted hover:text-breach-text hover:bg-breach-bg"
                }`
              }
            >
              <span>{icon}</span>
              <span className="font-medium">{label}</span>
            </NavLink>
          ))}

          {/* User info + logout */}
          <NavLink
            to="/settings"
            onClick={closeMobileNav}
            className="px-3 pt-3 pb-1 block hover:bg-breach-bg rounded transition-colors"
          >
            <div className="text-[10px] text-breach-text font-medium truncate">{user?.full_name || user?.email}</div>
            <div className="text-[9px] text-breach-muted truncate">{user?.email}</div>
            {user?.role === "admin" && (
              <span className="inline-block mt-1 mr-1 text-[8px] bg-purple-500/20 text-purple-400 border border-purple-500/30 px-1.5 py-0.5 rounded uppercase tracking-wider">
                Admin
              </span>
            )}
            <span className="inline-block mt-1 text-[8px] bg-yellow-500/10 text-yellow-500 border border-yellow-500/20 px-1.5 py-0.5 rounded uppercase tracking-wider">
              View Profile
            </span>
          </NavLink>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded text-xs text-breach-muted hover:text-breach-accent hover:bg-breach-bg transition-all"
          >
            <span>↩</span>
            <span>Logout</span>
          </button>
        </div>
      </aside>

      {/* Page content — top-padded on mobile to clear the fixed hamburger
          bar; no padding needed at md:+ where that bar doesn't render. */}
      <main className="flex-1 overflow-auto pt-14 md:pt-0">
        <Outlet />
      </main>

      <OnboardingModal />
    </div>
  );
}
