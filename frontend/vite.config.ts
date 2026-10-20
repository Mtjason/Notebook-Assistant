import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development `npm run dev` serves the app and forwards /api to `notebook-assistant serve`
// (port 8765 unless config.yaml says otherwise; NA_PORT overrides it here).
const servicePort = process.env.NA_PORT ?? "8765";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": `http://127.0.0.1:${servicePort}` } },
  // The build goes inside the Python package, so a checkout, an editable install and the
  // release wheel all serve it from one place. KaTeX makes one large chunk; it's served locally.
  build: { outDir: "../src/notebook_assistant/web", emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  test: { environment: "jsdom", globals: true },
});
