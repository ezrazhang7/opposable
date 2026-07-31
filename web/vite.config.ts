import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** The build lands inside the Python package, at opposable/web/, because that
 *  is the only way the assets travel in a wheel — anything beside the package
 *  is dropped by `pip install`, leaving a served UI that only works from a
 *  git clone. The directory is gitignored: it is built output, and CI (or a
 *  local `npm run build`) produces it before packaging.
 *
 *  In dev, Vite serves the SPA and proxies the API (including the SSE stream)
 *  to the Python server, so the frontend never learns a second origin. */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../opposable/web", emptyOutDir: true },
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
