import { test, expect, type Page } from '@playwright/test';

async function openLibrary(page: Page) {
  await page.locator('.btn-filter', { hasText: 'Objects' }).click();
  await page.locator('.npc-row', { hasText: 'BASEBOOK' }).click();
  await page.locator('button', { hasText: 'Read Books' }).click();

  const dialog = page.locator('.book-dialog[open]');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.book-list-item').first()).toBeVisible({ timeout: 10000 });
  return dialog;
}

test.describe('Book panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.npc-row');
  });

  test('BASEBOOK is the sole book entry and library launcher', async ({ page }) => {
    await page.locator('.btn-filter', { hasText: 'Objects' }).click();

    const objectRows = page.locator('.npc-list .npc-row');
    const basebook = objectRows.filter({ hasText: 'BASEBOOK' });
    await expect(objectRows.first().locator('.npc-name')).toContainText('BASEBOOK');
    await expect(basebook.locator('.npc-leading-icon')).toHaveText('📖');

    const librarySources = ['BASEBOOK', 'BASESCRL', 'GRAVE_NS', 'PLAQUENS', 'KEYONEC', 'PENT', 'NEC1', 'SCROLL1', 'EARTHMAG'];
    for (const className of librarySources) {
      const row = objectRows.filter({ hasText: className });
      await expect(row.locator('.tag', { hasText: 'library' })).toHaveCount(1);
      await expect(row.locator('.npc-leading-icon')).toHaveCount(className === 'BASEBOOK' ? 1 : 0);
    }

    await basebook.click();
    await expect(page.getByRole('button', { name: /Read Books/ })).toBeVisible();

    await objectRows.filter({ hasText: 'BASESCRL' }).click();
    await expect(page.getByRole('button', { name: /Read Books|Open Library/ })).toHaveCount(0);
  });

  test('Read Books opens modal and shows book list entries', async ({ page }) => {
    const dialog = await openLibrary(page);
    await expect(dialog.locator('.book-list-item')).not.toHaveCount(0);
  });

  test('spell catalog exposes all schools, slots, and mana costs', async ({ page }) => {
    const dialog = await openLibrary(page);
    await dialog.getByRole('tab', { name: /Spell Catalog/ }).click();

    await expect(dialog.locator('.book-count')).toHaveText('36 of 36 spell catalog');
    await expect(dialog.locator('.book-count')).not.toContainText('readable text');
    await expect(dialog.locator('.book-list-item')).toHaveCount(36);

    const schoolCounts: Record<string, number> = {
      Necromancy: 9,
      Sorcery: 12,
      Thaumaturgy: 6,
      Theurgy: 9,
    };
    for (const [school, count] of Object.entries(schoolCounts)) {
      await dialog.locator('.book-category-select').selectOption({ label: school });
      await expect(dialog.locator('.book-list-item')).toHaveCount(count);
    }

    await dialog.locator('.book-category-select').selectOption({ label: 'Sorcery' });
    await dialog.getByRole('button', { name: /Flame Bolt/ }).click();

    const reader = dialog.locator('.book-reader');
    await expect(reader.locator('.book-reader-quality')).toHaveText('Slot: 3');
    await expect(reader.locator('.book-reader-quality')).not.toContainText('Quality');

    const detailValue = (label: string) => reader
      .getByText(label, { exact: true })
      .locator('xpath=following-sibling::dd');
    await expect(detailValue('mana Cost')).toHaveText('8–10');
    await expect(detailValue('mana Cost Context')).toHaveText('When enchanting a focus');
    await expect(detailValue('incantation')).toHaveText('In Ort Flam');
  });

  test('Resurrection book uses its own text and is not a castable spell', async ({ page }) => {
    const dialog = await openLibrary(page);
    await dialog.locator('.book-search').fill('Resurrection');
    await expect(dialog.locator('.book-list-item')).toHaveCount(1);
    await dialog.getByRole('button', { name: /Resurrection/ }).click();

    const content = dialog.locator('.book-reader-content');
    await expect(content).toContainText('The Spell of Resurrection');
    await expect(content).toContainText('no focus or words of power');
    await expect(content).not.toContainText('The spell of Intervention');

    await dialog.locator('button[title="Back to list"]').click();
    await dialog.getByRole('tab', { name: /Spell Catalog/ }).click();
    await dialog.locator('.book-search').fill('Resurrection');
    await expect(dialog.locator('.book-list-item')).toHaveCount(0);
  });
});
