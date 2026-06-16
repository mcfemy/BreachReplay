import { NavLink, useNavigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/auth";
import OnboardingModal from "./OnboardingModal";

const NAV = [
  { to: "/scenarios", label: "Scenarios", icon: "⚡", desc: "Library" },
  { to: "/daily", label: "Daily Breach", icon: "🔐", desc: "One shot daily" },
  { to: "/redteam", label: "Red Team", icon: "🔴", desc: "Play attacker" },
  { to: "/leaderboard", label: "Leaderboard", icon: "🏆", desc: "Global XP ranking" },
  { to: "/teams", label: "Teams", icon: "👥", desc: "Org team mode" },
  { to: "/org-upload", label: "Org Upload", icon: "🏢", desc: "Private scenarios" },
  { to: "/settings", label: "My Certs", icon: "🎓", desc: "Credentials & profile" },
];

const BOTTOM_NAV = [
  { to: "/settings", label: "Profile", icon: "👤" },
  { to: "/pricing", label: "Pricing", icon: "💳" },
];

export default function AppShell() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="flex min-h-screen bg-breach-bg">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 flex flex-col border-r border-breach-border bg-breach-surface">
        {/* Brand */}
        <div className="px-4 py-5 border-b border-breach-border">
          <div className="flex items-center gap-2">
            <span className="text-breach-accent text-lg font-black tracking-tight">BREACH</span>
            <span className="text-breach-text text-lg font-black tracking-tight">REPLAY</span>
          </div>
          <div className="text-[9px] text-breach-muted uppercase tracking-widest mt-0.5">Cyber Training Platform</div>
        </div>

        {/* Main nav */}
        <nav className="flex-1 py-4 px-2 space-y-0.5">
          <div className="px-2 pb-2 text-[9px] text-breach-muted uppercase tracking-widest">Training</div>
          {NAV.map(({ to, label, icon, desc }) => (
            <NavLink
              key={to}
              to={to}
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

      {/* Page content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>

      <OnboardingModal />
    </div>
  );
}
