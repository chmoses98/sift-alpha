import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Independent Alpha app; intentionally does not import the consumer SIFT routing, PWA or live-feed infrastructure.
// Builds to dist/ and is not deployed by the CI workflow.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { target: "es2022", outDir: "dist", emptyOutDir: true }
});
