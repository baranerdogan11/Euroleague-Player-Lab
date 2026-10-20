// The game of the round tile steps through every game of the latest round: the arrows, the arrow keys and a swipe each
// move one game, the count follows, every game gets its own headline, and on a phone the player stays inside the tile.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled} from './site.js';

test.describe('desktop', () => {
  test.use(DESKTOP);
  for (const lang of ['en', 'tr']) test(`arrows and keys step through the round (${lang})`, async ({page}) => {
    const problems = await prepare(page, {lang});
    await page.goto('./');
    await settled(page);
    const hero = page.locator('#cv-hero'), count = hero.locator('.cv-hnav span');
    const n = await page.evaluate(() => { const G = META.games, R = Math.max(...G.map(g => g[1])); return G.filter(g => g[1] === R).length; });
    expect(n).toBeGreaterThan(1);
    const start = await count.textContent(), heads = new Set();
    for (let i = 0; i < n; i++) {
      heads.add(await hero.locator('h2').textContent());
      await expect(hero.locator('p')).not.toBeEmpty();
      await hero.locator('button[data-d="1"]').click();
    }
    await expect(count, 'a full lap comes back to the game of the round').toHaveText(start);
    expect(heads.size, 'each game has its own headline').toBe(n);
    await page.keyboard.press('ArrowRight');
    await expect(count).not.toHaveText(start);
    await page.keyboard.press('ArrowLeft');
    await expect(count).toHaveText(start);
    expect(await hero.locator('.cv-hero-a').getAttribute('href')).toMatch(/^#game\/\d+$/);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});

test.describe('phone', () => {
  test.use(PHONE);
  test('a swipe steps and the player fits the tile', async ({page}) => {
    const problems = await prepare(page);
    await page.goto('./');
    await settled(page);
    const hero = page.locator('#cv-hero'), count = hero.locator('.cv-hnav span');
    await hero.scrollIntoViewIfNeeded();
    const start = await count.textContent(), box = await hero.boundingBox();
    const img = await hero.locator('img').boundingBox(), nav = await hero.locator('.cv-hnav').boundingBox();
    expect(img.y, 'the photo starts inside the tile').toBeGreaterThanOrEqual(box.y);
    expect(img.x + img.width, 'the photo ends inside the tile').toBeLessThanOrEqual(box.x + box.width);
    expect(img.x, 'the photo clears the arrows').toBeGreaterThan(nav.x + nav.width);
    const y = box.y + 60, touch = (type, x) => page.dispatchEvent('#cv-hero', type, {touches: type === 'touchend' ? [] : [{identifier: 1, clientX: x, clientY: y}], changedTouches: [{identifier: 1, clientX: x, clientY: y}]});
    await touch('touchstart', box.x + box.width - 40);
    await touch('touchend', box.x + 40);
    await expect(count).not.toHaveText(start);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
