// A player link opened in a new tab ("Open link in new tab", ctrl/cmd-click) opens that player's page. The new tab
// starts with an empty sessionStorage, which used to send it to the opening page as if it were a fresh visit.
import {test, expect} from '@playwright/test';
import {DESKTOP, settled} from './site.js';

test.use(DESKTOP);

test('a player link opened in a new tab opens the player page', async ({page, context}) => {
  const problems = [];
  context.on('page', p => p.on('pageerror', e => problems.push(`uncaught: ${e.message}`)));
  page.on('pageerror', e => problems.push(`uncaught: ${e.message}`));
  await page.goto('./');
  await settled(page);
  await expect(page.locator('body')).toHaveClass(/cv-on/);
  const hash = await page.evaluate(() => { const r = ROSTER.list.find(x => CLUBS[x.club]); return `#${r.club}/${r.pid}`; });
  // a link that keeps no opener, as a middle click or "Open link in new tab" does: nothing is copied into the new tab
  await page.evaluate(h => { const a = document.createElement('a'); a.id = 'nt'; a.href = h; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'x'; document.body.append(a); }, hash);
  const [tab] = await Promise.all([context.waitForEvent('page'), page.click('#nt')]);
  await tab.waitForLoadState();
  await settled(tab);
  await expect(tab.locator('body')).not.toHaveClass(/cv-on/);
  expect(await tab.evaluate(() => location.hash)).toContain(hash);
  expect(await tab.evaluate(() => `#${state.team}/${team().players[state.player].pid}`)).toBe(hash);
  expect(problems, 'the page reported errors').toEqual([]);
});

test('a fresh visit from outside the site still opens on the opening page', async ({page}) => {
  await page.goto('./');
  await settled(page);
  const hash = await page.evaluate(() => { const r = ROSTER.list.find(x => CLUBS[x.club]); return `#${r.club}/${r.pid}`; });
  const fresh = await page.context().newPage();
  await fresh.goto('./' + hash);
  await settled(fresh);
  await expect(fresh.locator('body')).toHaveClass(/cv-on/);
});
