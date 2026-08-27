import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server the task's browser login runs against.
export default defineConfig({
    plugins: [react()],
    server: { host: "0.0.0.0", port: 5173, strictPort: true }
});
