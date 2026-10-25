import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "apps/web/e2e",
  workers: 1,
  timeout: 40000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    {
      command:
        ".venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001",
      url: "http://127.0.0.1:8001/api/v1/health/ready",
      env: { APP_MODE: "demo" },
      reuseExistingServer: false,
    },
    {
      command:
        "npm exec --workspace @nagarsaathi/web -- vite --host 127.0.0.1 --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      env: { API_PROXY_TARGET: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
    },
  ],
});
