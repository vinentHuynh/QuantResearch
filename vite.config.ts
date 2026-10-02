import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    watch: {
      usePolling: true,
      interval: 500,
      ignored: [
        "**/.venv/**",
        "**/__pycache__/**",
        "**/data/**",
        "**/artifacts/**",
        "**/reports/**",
        "**/tmp/**",
      ],
    },
    proxy: {
      "/api/workbench": "http://127.0.0.1:8001",
    },
  },
});
