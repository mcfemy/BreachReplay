import axios from "axios";
import { useAuthStore } from "../store/auth";
import { API_BASE } from "./config";

export { API_BASE };

export const axiosInstance = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
  },
});

// Interceptor to add Authorization Header dynamically
axiosInstance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("br_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Flag to track token refreshing status and request retry queue
let isRefreshing = false;
let failedQueue: any[] = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// Response Interceptor for 401 token rotation
axiosInstance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Check if error status is 401 and request has not been retried yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      // Avoid infinite loop if refreshing fails
      if (originalRequest.url === "/auth/refresh" || originalRequest.url === "/auth/login") {
        return Promise.reject(error);
      }

      originalRequest._retry = true;

      if (isRefreshing) {
        // Queue the request while refresh is in progress
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return axiosInstance(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      isRefreshing = true;
      const refreshToken = localStorage.getItem("br_refresh_token");

      if (!refreshToken) {
        isRefreshing = false;
        await useAuthStore.getState().logout();
        window.location.href = "/login";
        return Promise.reject(error);
      }

      try {
        // Direct axios call bypasses the interceptor — avoids recursive 401 loops
        const { data } = await axios.post<{ access_token: string; refresh_token: string; user: any }>(
          `${API_BASE}/auth/refresh`,
          { refresh_token: refreshToken }
        );

        useAuthStore.getState().setToken(data.access_token, data.refresh_token);
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        processQueue(null, data.access_token);
        isRefreshing = false;

        return axiosInstance(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        isRefreshing = false;
        // logout() calls the backend to revoke the refresh token before clearing state
        await useAuthStore.getState().logout();
        window.location.href = "/login";
        return Promise.reject(refreshError);
      }
    }

    // Wrap error messages consistently for the app
    const message = error.response?.data?.detail || error.message || "Request failed";
    return Promise.reject(new Error(message));
  }
);

// Unified API Wrapper matching the old interface exactly
export const api = {
  post: async <T>(path: string, body: unknown): Promise<T> => {
    const response = await axiosInstance.post<T>(path, body);
    return response.data;
  },
  get: async <T>(path: string): Promise<T> => {
    const response = await axiosInstance.get<T>(path);
    return response.data;
  },
  patch: async <T>(path: string, body?: unknown): Promise<T> => {
    const response = await axiosInstance.patch<T>(path, body);
    return response.data;
  },
};
