import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import wasm from "vite-plugin-wasm";
import path from "node:path";
const root = import.meta.dirname;
export default defineConfig({
  base: "/opencut/",
  plugins: [react(), tailwindcss(), wasm()],
  publicDir: "upstream/apps/web/public",
  resolve: {
    alias: [
      {
        find: "next/navigation",
        replacement: path.join(root, "integration/navigation.ts"),
      },
      {
        find: "next/link",
        replacement: path.join(root, "integration/link.tsx"),
      },
      {
        find: "next/image",
        replacement: path.join(root, "integration/image.tsx"),
      },
      {
        find: "@/sounds/components/assets-view",
        replacement: path.join(root, "integration/sounds.tsx"),
      },
      { find: "@/env/web", replacement: path.join(root, "integration/env.ts") },
      {
        find: "@/changelog/components/changelog-notification",
        replacement: path.join(root, "integration/optional.tsx"),
      },
      {
        find: "@/feedback/components/feedback-popover",
        replacement: path.join(root, "integration/optional.tsx"),
      },
      { find: "@", replacement: path.join(root, "upstream/apps/web/src") },
    ],
  },
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: { target: "esnext", chunkSizeWarningLimit: 2500 },
});
