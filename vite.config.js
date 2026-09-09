import { defineConfig } from 'vite';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = fileURLToPath(new URL('.', import.meta.url));

const port = parseInt(process.env.PORT || '5173', 10);
export default defineConfig({
  // GitHub Pages project site lives under /earth-chronicle/; set VITE_BASE=/ when deploying to a domain root
  base: process.env.VITE_BASE || '/earth-chronicle/',
  server: { host: '127.0.0.1', port, strictPort: false, open: false },
  build: {
    target: 'es2020',
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 3000,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        sources: resolve(__dirname, 'sources/index.html'),
      },
    },
  },
});
