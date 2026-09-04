import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/spa/",
  build: {
    outDir: "../static/spa",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: (assetInfo) =>
          assetInfo.names && assetInfo.names.some((n) => n.endsWith(".css"))
            ? "assets/app.css"
            : "assets/[name][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/agents": "http://127.0.0.1:8080",
      "/dashboard": "http://127.0.0.1:8080",
      "/cpq": "http://127.0.0.1:8080",
      "/static": "http://127.0.0.1:8080",
      "/login": "http://127.0.0.1:8080",
      "/logout": "http://127.0.0.1:8080",
    },
  },
});
