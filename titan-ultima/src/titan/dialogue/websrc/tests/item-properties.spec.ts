import { test, expect } from '@playwright/test';

test.describe('Item properties in Look panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.npc-row');
    // Switch to Objects view (items are non-dialogue objects)
    await page.locator('.btn-filter', { hasText: 'Objects' }).click();
    await page.waitForSelector('.npc-row');
  });

  async function openLook(page: import('@playwright/test').Page, npcName: string) {
    await page.locator('.npc-row', { hasText: npcName }).click();
    const lookBtn = page.locator('button', { hasText: `Look at ${npcName}` });
    await lookBtn.click();
    await page.waitForSelector('.look-dialog[open]');
  }

  test('HAMOSTR (Bone Crusher) shows special weapon stats', async ({ page }) => {
    await openLook(page, 'HAMOSTR');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('.item-stats-heading')).toContainText('Special Weapon');
    await expect(stats.locator('text=11')).toBeVisible(); // baseDamage
    await expect(stats.locator('.dmg-blunt')).toBeVisible();
    await expect(stats.locator('.dmg-magic')).toBeVisible();
  });

  test('FLAMSTNG (Flame Sting) shows fire + blade + magic damage types', async ({ page }) => {
    await openLook(page, 'FLAMSTNG');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('.dmg-blade')).toBeVisible();
    await expect(stats.locator('.dmg-fire')).toBeVisible();
    await expect(stats.locator('.dmg-magic')).toBeVisible();
    await expect(stats.locator('text=Attack DEX Bonus')).toBeVisible();
  });

  test('SLAYER shows slayer damage type', async ({ page }) => {
    await openLook(page, 'SLAYER');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('.dmg-slayer')).toBeVisible();
    await expect(stats.locator('.dmg-magic')).toBeVisible();
  });

  test('SCIMOKG (Khumash-Gor) shows undead damage type', async ({ page }) => {
    await openLook(page, 'SCIMOKG');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('.dmg-undead')).toBeVisible();
    await expect(stats.locator('.dmg-blade')).toBeVisible();
  });

  test('SCIMITAR shows non-special weapon (no magic flag)', async ({ page }) => {
    await openLook(page, 'SCIMITAR');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    // Generic weapon - heading should NOT say "Special"
    await expect(stats.locator('.item-stats-heading')).toContainText('Weapon');
    await expect(stats.locator('.item-stats-heading')).not.toContainText('Special');
    await expect(stats.locator('.dmg-blade')).toBeVisible();
    await expect(stats.locator('text=Treasure Chance')).toBeVisible();
  });

  test('ARMOR shows armour class', async ({ page }) => {
    await openLook(page, 'ARMOR');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('.item-stats-heading')).toContainText('Armour');
    await expect(stats.locator('text=Armour Class')).toBeVisible();
  });

  test('MAGSHLD shows armour with fire defense type', async ({ page }) => {
    await openLook(page, 'MAGSHLD');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('text=Defense Type')).toBeVisible();
    await expect(stats.locator('.dmg-fire')).toBeVisible();
  });

  test('NPC without item properties shows no stats section', async ({ page }) => {
    // Switch back to NPC view for this test
    await page.locator('.btn-filter', { hasText: 'NPCs' }).click();
    await page.waitForSelector('.npc-row');
    await page.locator('.npc-row', { hasText: 'DEVON' }).click();
    const lookBtn = page.locator('button', { hasText: 'Look at DEVON' });
    await lookBtn.click();
    await page.waitForSelector('.look-dialog[open]');
    await expect(page.locator('.item-stats')).not.toBeVisible();
  });

  test('SWORD shows weapon overlay with animation style and used-by list', async ({ page }) => {
    await page.getByRole('button', { name: 'SWORD look', exact: true }).click();
    await page.getByRole('button', { name: 'Look at SWORD', exact: true }).click();
    await page.waitForSelector('.look-dialog[open]');
    const stats = page.locator('.item-stats');
    await expect(stats).toBeVisible();
    await expect(stats.locator('text=Weapon Overlay (sword)')).toBeVisible();
    await expect(stats.locator('.overlay-weapon-list li')).toHaveCount(7);
  });
});
