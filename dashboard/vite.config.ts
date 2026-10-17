import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// the dashboard is served by the Countersign server at /dashboard, from the folder it builds into
export default defineConfig({
  base: "/dashboard/",
  plugins: [react()],
  // AG Studio with its grid and charts is one large bundle by nature
  build: { outDir: "../src/countersign/static/dashboard", emptyOutDir: true, chunkSizeWarningLimit: 7000 },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
