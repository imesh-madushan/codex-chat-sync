import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" lets the built page load from a local file inside pywebview.
export default defineConfig({ base: "./", plugins: [react()], server: { port: 5173, strictPort: true } });
