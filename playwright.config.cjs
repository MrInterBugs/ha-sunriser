const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/browser',
  use: { baseURL: 'http://127.0.0.1:8766', browserName: 'chromium' },
  webServer: { command: 'node tests/browser/server.cjs', port: 8766, reuseExistingServer: false },
});
