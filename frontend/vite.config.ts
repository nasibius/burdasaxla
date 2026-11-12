import { execSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function commit() {
  if (process.env.GITHUB_SHA) return process.env.GITHUB_SHA.slice(0, 7);
  try { return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim(); } catch { return "local"; }
}

// VITE_BASE: public path, e.g. "/burdasaxla/" for GitHub Pages project sites.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  define: { __BUILD_INFO__: JSON.stringify({ commit: commit(), time: new Date().toISOString() }) },
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { "/api": "http://localhost:8000" } },
});
