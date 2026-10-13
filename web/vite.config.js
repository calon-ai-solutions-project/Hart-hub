import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// In development the browser talks only to Vite, which forwards /api and /media to the Django
// backend. One origin means the session cookie and CSRF token work without any CORS set-up.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_URL || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: backend, changeOrigin: false },
        "/media": { target: backend, changeOrigin: false },
      },
    },
  };
});
