import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import ui from "@nuxt/ui/vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [
    vue(),
    ui({
      colorMode: true,
      ui: {
        colors: {
          primary: "blue",
          neutral: "slate",
        },
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/ws": { target: "ws://127.0.0.1:8080", ws: true },
    },
  },
  build: {
    outDir: resolve(__dirname, "../sl651/static"),
    emptyOutDir: true,
    assetsDir: "assets",
  },
});
