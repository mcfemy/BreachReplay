import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import LandingPage from "./pages/LandingPage";
import ScenarioLibraryPage from "./pages/ScenarioLibraryPage";
import SimulationRoomPage from "./pages/SimulationRoomPage";
import SessionMultiplayerLobbyPage from "./pages/SessionMultiplayerLobbyPage";
import SessionDebriefPage from "./pages/SessionDebriefPage";
import AdminDashboardPage from "./pages/AdminDashboardPage";
import ScenarioCinematicIntroPage from "./pages/ScenarioCinematicIntroPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import UserProfilePage from "./pages/UserProfilePage";
import PricingPage from "./pages/PricingPage";
import DailyBreachPage from "./pages/DailyBreachPage";
import RedTeamPage from "./pages/RedTeamPage";
import LeaderboardPage from "./pages/LeaderboardPage";
import CertificatePage from "./pages/CertificatePage";
import OrgUploadPage from "./pages/OrgUploadPage";
import TeamsPage from "./pages/TeamsPage";
import NotFoundPage from "./pages/NotFoundPage";
import AppShell from "./components/AppShell";
import { useAuthStore } from "./store/auth";

const queryClient = new QueryClient();

function AdminProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  if (user?.role !== "admin" && user?.role !== "ciso") return <Navigate to="/scenarios" replace />;
  return <>{children}</>;
}

function AuthenticatedShell() {
  const { token } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  return <AppShell />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/cert/:token" element={<CertificatePage />} />

          {/* Authenticated routes — all get the sidebar via AppShell */}
          <Route element={<AuthenticatedShell />}>
            <Route path="/scenarios" element={<ScenarioLibraryPage />} />
            <Route path="/daily" element={<DailyBreachPage />} />
            <Route path="/redteam" element={<RedTeamPage />} />
            <Route path="/leaderboard" element={<LeaderboardPage />} />
            <Route path="/settings" element={<UserProfilePage />} />
            <Route path="/org-upload" element={<OrgUploadPage />} />
            <Route path="/teams" element={<TeamsPage />} />
            <Route path="/session/:sessionId/intro" element={<ScenarioCinematicIntroPage />} />
            <Route path="/session/:sessionId" element={<SimulationRoomPage />} />
            <Route path="/session/:sessionId/lobby" element={<SessionMultiplayerLobbyPage />} />
            <Route path="/session/:sessionId/debrief" element={<SessionDebriefPage />} />
            <Route
              path="/admin"
              element={
                <AdminProtectedRoute>
                  <AdminDashboardPage />
                </AdminProtectedRoute>
              }
            />
          </Route>

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
