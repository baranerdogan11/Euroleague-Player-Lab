// The opening page is the scoreboard of the latest round: one card per game, in date order, each opening its game page and
// showing that game's best line; the game of the round (the closest finish) is printed red and its one-line story opens the
// same game; the band's next-round box jumps to the next round's games. On a phone the cards stack, the portrait stays
// inside its card and nothing scrolls sideways.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled, noSidewaysScroll} from './site.js';

const round = page => page.evaluate(() => {
  const G = META.games, R = Math.max(...G.map(g => g[1])), RG = G.filter(g => g[1] === R);
  const feature = [...RG].sort((a, b) => Math.abs(a[5] - a[6]) - Math.abs(b[5] - b[6]) || b[0] - a[0])[0];
  return {codes: RG.map(g => g[0]), feature: feature[0], next: (META.next_round || []).length};
});

test.describe('desktop', () => {
  test.use(DESKTOP);
  for (const lang of ['en', 'tr']) test(`one card per game and the game of the round in red (${lang})`, async ({page}) => {
    const problems = await prepare(page, {lang});
    await page.goto('./');
    await settled(page);
    const r = await round(page), cards = page.locator('#cv-games a.cv-game');
    await expect(cards).toHaveCount(r.codes.length);
    const hrefs = await cards.evaluateAll(as => as.map(a => a.getAttribute('href')));
    expect(hrefs.map(h => +h.split('/')[1]).sort(), 'every game of the round has its card').toEqual([...r.codes].sort());
    const red = page.locator('#cv-games a.cv-game.gor');
    await expect(red, 'one game of the round').toHaveCount(1);
    await expect(red).toHaveAttribute('href', `#game/${r.feature}`);
    await expect(page.locator('#cv-story')).toHaveAttribute('href', `#game/${r.feature}`);
    await expect(page.locator('#cv-story b')).not.toBeEmpty();
    for (const c of await cards.all()) await expect(c.locator('.who b'), 'each card shows its best line').not.toBeEmpty();
    if (r.next) {
      await expect(page.locator('#cv-next .cv-fix a')).toHaveCount(r.next);
      await page.locator('#cv-tonight').click();
      await expect(page.locator('#cv-next')).toBeFocused();
      await expect(page.locator('#cv-next')).toBeInViewport();
    } else await expect(page.locator('#cv-tonight')).toBeHidden();
    await red.click();
    await page.waitForFunction(code => location.hash === `#game/${code}`, r.feature);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});

test.describe('phone', () => {
  test.use(PHONE);
  test('cards stack and each portrait stays inside its card', async ({page}) => {
    const problems = await prepare(page, {lang: 'tr', theme: 'dark'});
    await page.goto('./');
    await settled(page);
    const cards = page.locator('#cv-games a.cv-game');
    if (await cards.count() > 1) {
      const first = await cards.nth(0).boundingBox(), second = await cards.nth(1).boundingBox();
      expect(second.y, 'the cards stack').toBeGreaterThanOrEqual(first.y + first.height - 3);
    }
    for (const c of await cards.all()) {
      const box = await c.boundingBox(), ph = await c.locator('.who').boundingBox();
      expect(ph.x + ph.width, 'the portrait ends inside the card').toBeLessThanOrEqual(box.x + box.width + 1);
      expect(ph.y + ph.height, 'the portrait ends inside the card').toBeLessThanOrEqual(box.y + box.height + 1);
    }
    await noSidewaysScroll(page, 'the opening page');
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
