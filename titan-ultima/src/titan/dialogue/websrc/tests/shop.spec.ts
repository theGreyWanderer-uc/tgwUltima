import { test, expect } from '@playwright/test';

test.describe('Shop panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait for NPC list to load
    await page.waitForSelector('.npc-row');
  });

  async function openShop(page: import('@playwright/test').Page, npcName: string) {
    // Click the NPC row in the sidebar
    await page.locator('.npc-row', { hasText: npcName }).click();
    // Click the Shop button
    const shopBtn = page.locator('button', { hasText: new RegExp(`${npcName}.*Shop|Shop`) });
    await shopBtn.click();
    // Wait for the shop dialog to appear
    await page.waitForSelector('.shop-dialog[open]');
  }

  test('JENNA has 2 shop functions with 12 items total', async ({ page }) => {
    await openShop(page, 'JENNA');

    const sections = page.locator('.shop-section');
    await expect(sections).toHaveCount(2);

    const rows = page.locator('.shop-table tbody tr');
    await expect(rows).toHaveCount(12);
  });

  test('JENNA drinks shop has correct items and prices', async ({ page }) => {
    await openShop(page, 'JENNA');

    // First section (func0C3E) should have drink items
    const firstTable = page.locator('.shop-table').first();
    const firstRows = firstTable.locator('tbody tr');
    await expect(firstRows).toHaveCount(5);

    // Verify specific items by targeting name and price cells
    const names = await firstTable.locator('.shop-item-name').allTextContents();
    expect(names).toEqual(['Tenebraean Ale', 'Black Wine', 'Hurricane', "Breath O'Spirit", 'Cloven Hoof']);
    const prices = await firstTable.locator('.shop-item-price').allTextContents();
    expect(prices).toEqual(['1 obs', '3 obs', '2 obs', '2 obs', '5 obs']);
  });

  test('JENNA food shop has correct items', async ({ page }) => {
    await openShop(page, 'JENNA');

    const secondTable = page.locator('.shop-table').nth(1);
    const rows = secondTable.locator('tbody tr');
    await expect(rows).toHaveCount(7);

    await expect(secondTable.locator('text=fish')).toBeVisible();
    await expect(secondTable.locator('text=Kith filet')).toBeVisible();
    await expect(secondTable.locator('text=8 obs')).toBeVisible();
  });

  test('ORLOK has 1 shop function with 5 drinks', async ({ page }) => {
    await openShop(page, 'ORLOK');

    const sections = page.locator('.shop-section');
    await expect(sections).toHaveCount(1);

    const rows = page.locator('.shop-table tbody tr');
    await expect(rows).toHaveCount(5);

    await expect(page.locator('text=Tenebraen Ale')).toBeVisible();
    await expect(page.locator('text=Blackwine')).toBeVisible();
    await expect(page.locator('text=Cloven Hoof')).toBeVisible();
  });

  test('ORLOK drink prices are correct', async ({ page }) => {
    await openShop(page, 'ORLOK');

    const table = page.locator('.shop-table').first();
    // Tenebraen Ale = 2 obs, Blackwine = 3 obs, Cloven Hoof = 5 obs
    const priceTexts = await table.locator('.shop-item-price').allTextContents();
    expect(priceTexts).toEqual(['2 obs', '3 obs', '2 obs', '2 obs', '5 obs']);
  });

  test('KORICK has 2 shop functions (armor + weapons)', async ({ page }) => {
    await openShop(page, 'KORICK');

    const sections = page.locator('.shop-section');
    await expect(sections).toHaveCount(2);

    const rows = page.locator('.shop-table tbody tr');
    await expect(rows).toHaveCount(10);
  });

  test('KORICK armor prices are correct', async ({ page }) => {
    await openShop(page, 'KORICK');

    const firstTable = page.locator('.shop-table').first();
    const priceTexts = await firstTable.locator('.shop-item-price').allTextContents();
    expect(priceTexts).toEqual(['12 obs', '11 obs', '12 obs', '13 obs']);
  });

  test('KORICK weapons have correct items and prices', async ({ page }) => {
    await openShop(page, 'KORICK');

    const secondTable = page.locator('.shop-table').nth(1);
    const rows = secondTable.locator('tbody tr');
    await expect(rows).toHaveCount(6);

    const names = await secondTable.locator('.shop-item-name').allTextContents();
    expect(names).toEqual(['Sabre', 'Scimitar', 'Mace', 'Dagger', 'Axe', 'Broadsword']);
    const prices = await secondTable.locator('.shop-item-price').allTextContents();
    expect(prices).toEqual(['75 obs', '90 obs', '15 obs', '5 obs', '25 obs', '125 obs']);
  });

  test('MYTHRAN has shop functions with reagent schools', async ({ page }) => {
    await openShop(page, 'MYTHRAN');

    // Mythran has nested shop structure; at least func08A6 should have items
    const rows = page.locator('.shop-table tbody tr');
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(3);

    await expect(page.locator('text=Necromancy')).toBeVisible();
    await expect(page.locator('text=Sorcery')).toBeVisible();
    await expect(page.locator('text=Thaumaturgy')).toBeVisible();
  });

  test('shop dialog can be closed', async ({ page }) => {
    await openShop(page, 'JENNA');
    await expect(page.locator('.shop-dialog[open]')).toBeVisible();

    // Close via the close button
    await page.locator('.shop-dialog .look-close').click();
    await expect(page.locator('.shop-dialog[open]')).toHaveCount(0);
  });
});
