import { defineConfig } from '@playwright/test';

const previewHost = '127.0.0.1';
const previewPort = Number.parseInt(process.env.PLAYWRIGHT_PORT ?? '4173', 10);
const previewDirectory = process.env.PLAYWRIGHT_PREVIEW_DIR;
const previewDirectoryArg = previewDirectory ? ` --outDir "${previewDirectory}"` : '';
const previewUrl = `http://${previewHost}:${previewPort}`;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: previewUrl,
    headless: true,
  },
  webServer: {
    command: `npx vite preview --host ${previewHost} --port ${previewPort} --strictPort${previewDirectoryArg}`,
    url: previewUrl,
    reuseExistingServer: false,
  },
});
