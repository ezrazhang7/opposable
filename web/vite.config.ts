import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** The Python server owns :8734 and serves the built bundle out of web/dist.
 *  In dev, Vite serves the SPA and proxies the API (including the SSE stream)
 *  to that server, so the frontend never learns a second origin. */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8734",
        changeOrigin: true,
      },
    },
  },
});
