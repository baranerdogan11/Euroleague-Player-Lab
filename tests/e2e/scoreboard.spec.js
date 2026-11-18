// The opening page is the scoreboard of the latest round: one card per game, finals first in date order, each opening its game
// page and showing that game's best line, then the round's games still to play with names only. The game of the round (the
// closest finish) is named only once the round is over: then it is printed red and its one-line story opens the same game;
// while the round is still being played no card is red and the story tells the previous round's game of the round. The band's
// next-round box jumps to the next round's games. On a phone the cards stack, the portrait stays inside its card and nothing
// scrolls sideways. Every count of finals is drawn from the real round by replaying it with fewer games played.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled, noSidewaysScroll} from './site.js';

const closest = G => [...G].sort((a, b) => Math.abs(a[5] - a[6]) - Math.abs(b[5] - b[6]) || b[0] - a[0])[0];
const round = page => page.evaluate(() => {
  const G = META.games, R = Math.max(...G.map(g => g[1])), RG = G.filter(g => g[1] === R), done = META.round_open ? R - 1 : R;
  return {R, done, codes: RG.map(g => g[0]), rest: (META.round_rest || []).filter(g => g[1] === R).length, played: G.filter(g => g[1] === done), next: (META.next_round || []).length};
});

// the latest full round replayed with only its first k games final, the rest still to play
async function replay(page, k) {
  await page.route(/\/(index\.html)?(\?.*)?$/, async route => {
    const res = await route.fetch(), html = await res.text();
    const M = JSON.parse(html.match(/^const META = (.*);$/m)[1]);
    const rounds = [...new Set(M.games.map(g => g[1]))].sort((a, b) => b - a);
    const full = rounds.find(r => M.games.filter(g => g[1] === r).length >= 9 && !(M.round_rest || []).some(g => g[1] === r));
    const order = (a, b) => a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : a[0] - b[0];
    const R = M.games.filter(g => g[1] === full).sort(order), keep = R.slice(0, k), todo = R.slice(k);
    M.games = [...keep].reverse().concat(M.games.filter(g => g[1] < full));
    M.round_rest = M.next_round = todo.map(g => g.slice(0, 5));
    M.round_open = todo.length > 0;
    await route.fulfill({response: res, body: html.replace(/^const META = .*;$/m, () => `const META = ${JSON.stringify(M)};`)});
  });
}

async function check(page) {
  const r = await round(page), cards = page.locator('#cv-games a.cv-game');
  await expect(cards).toHaveCount(r.codes.length + r.rest);
  const finals = page.locator('#cv-games a.cv-game:not(.up)');
  const hrefs = await finals.evaluateAll(as => as.map(a => a.getAttribute('href')));
  expect(hrefs.map(h => +h.split('/')[1]).sort(), 'every final of the round has its card').toEqual([...r.codes].sort());
  await expect(page.locator('#cv-games a.cv-game.up')).toHaveCount(r.rest);
  for (const c of await finals.all()) await expect(c.locator('.who b'), 'each final shows its best line').not.toBeEmpty();
  // no card's content runs past its edge
  const spill = await cards.evaluateAll(as => as.filter(a => a.scrollWidth > a.clientWidth + 1).map(a => a.getAttribute('href')));
  expect(spill, 'cards whose content spills out').toEqual([]);
  const red = page.locator('#cv-games a.cv-game.gor');
  if (r.done === r.R) {
    const f = closest(r.played)[0];
    await expect(red, 'one game of the round').toHaveCount(1);
    await expect(red).toHaveAttribute('href', `#game/${f}`);
    await expect(page.locator('#cv-story')).toHaveAttribute('href', `#game/${f}`);
  } else {
    await expect(red, 'no game of the round while the round is being played').toHaveCount(0);
    if (r.played.length) {
      await expect(page.locator('#cv-story')).toHaveAttribute('href', `#game/${closest(r.played)[0]}`);
      await expect(page.locator('#cv-story .cv-th')).toContainText(String(r.done));
    } else await expect(page.locator('#cv-story')).toBeHidden();
  }
  return r;
}

test.describe('desktop', () => {
  test.use(DESKTOP);
  for (const lang of ['en', 'tr']) test(`one card per game, the game of the round in red once the round is over (${lang})`, async ({page}) => {
    const problems = await prepare(page, {lang});
    await page.goto('./');
    await settled(page);
    const r = await check(page);
    if (r.next) {
      await expect(page.locator('#cv-next .cv-fix a')).toHaveCount(r.next);
      await page.locator('#cv-tonight').click();
      await expect(page.locator('#cv-next')).toBeFocused();
      await expect(page.locator('#cv-next')).toBeInViewport();
    } else await expect(page.locator('#cv-tonight')).toBeHidden();
    const first = page.locator('#cv-games a.cv-game:not(.up)').first(), href = await first.getAttribute('href');
    await first.click();
    await page.waitForFunction(h => location.hash === h, href);
    expect(problems, 'the page reported errors').toEqual([]);
  });
  for (const k of [1, 2, 5, 9, 10]) test(`a round with ${k} final${k > 1 ? 's' : ''}`, async ({page}) => {
    const problems = await prepare(page, {lang: k % 2 ? 'tr' : 'en', theme: k % 2 ? 'dark' : 'light'});
    await replay(page, k);
    await page.goto('./');
    await settled(page);
    const r = await check(page);
    expect(r.codes.length + r.rest, 'the whole round is on the board').toBeGreaterThanOrEqual(9);
    expect(r.done === r.R, 'the round is over only when every game is final').toBe(k >= r.codes.length + r.rest);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});

test.describe('phone', () => {
  test.use(PHONE);
  for (const k of [null, 2]) test(`cards stack and each portrait stays inside its card${k ? ` (${k} finals)` : ''}`, async ({page}) => {
    const problems = await prepare(page, {lang: 'tr', theme: 'dark'});
    if (k) await replay(page, k);
    await page.goto('./');
    await settled(page);
    const cards = page.locator('#cv-games a.cv-game');
    if (await cards.count() > 1) {
      const first = await cards.nth(0).boundingBox(), second = await cards.nth(1).boundingBox();
      expect(second.y, 'the cards stack').toBeGreaterThanOrEqual(first.y + first.height - 3);
    }
    for (const c of await page.locator('#cv-games a.cv-game:not(.up)').all()) {
      const box = await c.boundingBox(), ph = await c.locator('.who').boundingBox();
      expect(ph.x + ph.width, 'the portrait ends inside the card').toBeLessThanOrEqual(box.x + box.width + 1);
      expect(ph.y + ph.height, 'the portrait ends inside the card').toBeLessThanOrEqual(box.y + box.height + 1);
    }
    await noSidewaysScroll(page, 'the opening page');
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
