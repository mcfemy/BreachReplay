import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AppShell from "./components/AppShell";
import { useAuthStore } from "./store/auth";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const LandingPage = lazy(() => import("./pages/LandingPage"));
const ScenarioLibraryPage = lazy(() => import("./pages/ScenarioLibraryPage"));
const SimulationRoomPage = lazy(() => import("./pages/SimulationRoomPage"));
const SessionMultiplayerLobbyPage = lazy(() => import("./pages/SessionMultiplayerLobbyPage"));
const SessionDebriefPage = lazy(() => import("./pages/SessionDebriefPage"));
const AdminDashboardPage = lazy(() => import("./pages/AdminDashboardPage"));
const ScenarioCinematicIntroPage = lazy(() => import("./pages/ScenarioCinematicIntroPage"));
const ResetPasswordPage = lazy(() => import("./pages/ResetPasswordPage"));
const UserProfilePage = lazy(() => import("./pages/UserProfilePage"));
const PricingPage = lazy(() => import("./pages/PricingPage"));
const DailyBreachPage = lazy(() => import("./pages/DailyBreachPage"));
const RedTeamPage = lazy(() => import("./pages/RedTeamPage"));
const LeaderboardPage = lazy(() => import("./pages/LeaderboardPage"));
const CertificatePage = lazy(() => import("./pages/CertificatePage"));
const OrgUploadPage = lazy(() => import("./pages/OrgUploadPage"));
const TeamsPage = lazy(() => import("./pages/TeamsPage"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));
const AuthCallbackPage = lazy(() => import("./pages/AuthCallbackPage"));

const queryClient = new QueryClient();

const PageLoader = (
  <div className="min-h-screen bg-[#0a0b0d] flex items-center justify-center">
    <div className="w-8 h-8 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
  </div>
);

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
        <Suspense fallback={PageLoader}>
          <Routes>
            {/* Public routes */}
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/pricing" element={<PricingPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/cert/:token" element={<CertificatePage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />

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
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
