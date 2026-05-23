import { create } from "zustand";

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
  setAuth: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: localStorage.getItem("br_token"),
  setAuth: (token, user) => {
    localStorage.setItem("br_token", token);
    set({ token, user });
  },
  logout: () => {
    localStorage.removeItem("br_token");
    set({ token: null, user: null });
  },
}));
