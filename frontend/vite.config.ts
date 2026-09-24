import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(
    mode,
    fileURLToPath(new URL('.', import.meta.url)),
    'DEV_',
  )
  return {
    plugins: [vue()],
    server: {
      host: env.DEV_HOST || '127.0.0.1',
      port: Number(env.DEV_PORT || 5173),
      strictPort: true,
      proxy: {
        '/api': { target: env.DEV_API_TARGET || 'http://127.0.0.1:8080' },
      },
    },
  }
})
