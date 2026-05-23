import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LoginPage from "./pages/LoginPage";
import ScenarioLibraryPage from "./pages/ScenarioLibraryPage";
import SimulationRoomPage from "./pages/SimulationRoomPage";
import { useAuthStore } from "./store/auth";

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/scenarios" element={<ProtectedRoute><ScenarioLibraryPage /></ProtectedRoute>} />
          <Route path="/session/:sessionId" element={<ProtectedRoute><SimulationRoomPage /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/scenarios" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
