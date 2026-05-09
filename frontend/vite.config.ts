import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    allowedHosts: ['host.docker.internal'],
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
