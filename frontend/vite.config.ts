import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE: public path, e.g. "/burdasaxla/" for GitHub Pages project sites.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { "/api": "http://localhost:8000" } },
});
