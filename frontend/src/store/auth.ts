import axios from "axios";
import { create } from "zustand";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  organization_id: string | null;
}

interface AuthState {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  setAuth: (token: string, refreshToken: string, user: User) => void;
  setToken: (token: string, refreshToken: string) => void;
  logout: () => Promise<void>;
}

function loadUser(): User | null {
  try {
    const raw = localStorage.getItem("br_user");
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: loadUser(),
  token: localStorage.getItem("br_token"),
  refreshToken: localStorage.getItem("br_refresh_token"),

  setAuth: (token, refreshToken, user) => {
    localStorage.setItem("br_token", token);
    localStorage.setItem("br_refresh_token", refreshToken);
    localStorage.setItem("br_user", JSON.stringify(user));
    set({ token, refreshToken, user });
  },

  setToken: (token, refreshToken) => {
    localStorage.setItem("br_token", token);
    localStorage.setItem("br_refresh_token", refreshToken);
    set({ token, refreshToken });
  },

  logout: async () => {
    const refreshToken = get().refreshToken;
    if (refreshToken) {
      try {
        await axios.post(`${API_BASE}/auth/logout`, { refresh_token: refreshToken });
      } catch {
        // Best-effort — clear local state regardless of network failure
      }
    }
    localStorage.removeItem("br_token");
    localStorage.removeItem("br_refresh_token");
    localStorage.removeItem("br_user");
    set({ token: null, refreshToken: null, user: null });
  },
}));
