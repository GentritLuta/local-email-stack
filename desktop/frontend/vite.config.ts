import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: "esnext",
    minify: !process.env.TAURI_ENV_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    rollupOptions: {
      // The Tauri notification plugin is bundled by the Tauri runtime, not
      // npm. The IN_TAURI guard in notify.ts means the dynamic imports are
      // never reached in browser dev — but Rollup statically resolves them
      // anyway and fails the build. Mark as external so the prod build
      // succeeds outside Tauri.
      external: ["@tauri-apps/plugin-notification"],
    },
  },
});
