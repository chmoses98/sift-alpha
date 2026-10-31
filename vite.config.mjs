import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Deliberately isolated: does not reuse the public SIFT PWA, routing, live-data or build config.
// Default builds into dist-alpha, which is never deployed by the public Pages workflow.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { target: "es2022", outDir: "dist", emptyOutDir: true }
});
