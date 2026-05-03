import { test, expect } from '@playwright/test';

test.describe('Book panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.npc-row');
  });

  test('Read Books opens modal and shows book list entries', async ({ page }) => {
    await page.locator('.btn-filter', { hasText: 'Objects' }).click();
    await page.locator('.npc-row', { hasText: 'BASEBOOK' }).click();

    await page.locator('button', { hasText: 'Read Books' }).click();

    const bookDialog = page.locator('.book-dialog[open]');
    await expect(bookDialog).toBeVisible();

    await page.waitForSelector('.book-list-item', { timeout: 10000 });
    const bookItems = page.locator('.book-list-item');
    const count = await bookItems.count();
    expect(count).toBeGreaterThan(0);
  });
});
