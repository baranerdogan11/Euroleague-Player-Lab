// Size budget: no single file the opening page or a club page fetches may pass 150 KB gzipped. The league-wide lineups
// file grows every round, so the club page reads its own slice (lineups/<CODE>.json); this keeps it that way.
import {test, expect} from '@playwright/test';
import {gzipSync} from 'node:zlib';
import {DESKTOP, prepare, settled, go} from './site.js';

const BUDGET = 150 * 1024;

test.use(DESKTOP);
test('cover and club page files stay under 150 KB gzipped', async ({page}) => {
  const problems = await prepare(page);
  const sizes = {}, pending = [];
  page.on('response', r => {
    if (r.request().method() !== 'GET' || !r.ok() || !r.url().startsWith('http://127.0.0.1')) return;
    pending.push(r.body().then(b => { sizes[new URL(r.url()).pathname] = gzipSync(b).length; }, () => {}));
  });
  await page.goto('./');
  await settled(page);
  const code = await page.evaluate(() => Object.keys(CLUBS)[0]);
  await go(page, `#${code}`, () => !document.querySelector('#club').textContent.includes('Loading…'));
  await expect(page.locator('#club .cb-two tbody tr').first(), 'the club page drew its fives').not.toContainText('No games yet');
  await page.waitForLoadState('networkidle');
  await Promise.all(pending);
  expect(Object.keys(sizes).some(p => p.endsWith(`/lineups/${code}.json`)), 'the club page read its own lineups slice').toBe(true);
  expect(Object.keys(sizes).some(p => p.endsWith('/lineups.json')), 'the club page skipped the league-wide lineups file').toBe(false);
  const over = Object.entries(sizes).filter(([, n]) => n > BUDGET).map(([p, n]) => `${p} ${Math.round(n / 1024)} KB`);
  expect(over, 'files over the 150 KB gzipped budget').toEqual([]);
  expect(problems, 'the page reported errors').toEqual([]);
});
