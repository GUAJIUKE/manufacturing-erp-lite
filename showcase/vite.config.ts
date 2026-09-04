import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  base: './',                 // 允许 /showcase/ 路径下通过相对路径加载资源
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2020',
    cssCodeSplit: true,
    rollupOptions: {
      output: {
        manualChunks: undefined,    // Showcase 体积很小，无需分块
      },
    },
  },
  server: {
    port: 5174,
    strictPort: true,
  },
});