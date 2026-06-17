import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuthStore } from "../store/auth";
import { API_BASE } from "../lib/config";

export default function AuthCallbackPage() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");

    if (accessToken && refreshToken) {
      setTokens(accessToken, refreshToken);
      // Fetch the user profile so the store is fully populated
      axios
        .get(`${API_BASE}/auth/me`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        })
        .then(({ data }) => {
          localStorage.setItem("br_user", JSON.stringify(data));
          useAuthStore.setState({ user: data });
          navigate("/scenarios", { replace: true });
        })
        .catch(() => {
          // Tokens are stored — navigate anyway; startup sync will fix profile
          navigate("/scenarios", { replace: true });
        });
    } else {
      navigate("/login?error=oauth_failed", { replace: true });
    }
  }, [navigate, setTokens]);

  return (
    <div className="min-h-screen bg-[#0a0b0d] flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
