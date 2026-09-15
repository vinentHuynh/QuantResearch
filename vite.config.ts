import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    watch: { ignored: ["**/data/**", "**/reports/**"] },
    proxy: {
      "/api/workbench": "http://127.0.0.1:8001",
      "/api": "http://127.0.0.1:8000",
    },
  },
});
