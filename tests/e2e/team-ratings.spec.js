// The standings Ratings view ranks every club by offensive, defensive and net rating and pace. Each club's value and place
// there must read exactly as on its club page's Ratings tiles, and a tile's rank opens the table sorted by that rating.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled, go, noSidewaysScroll} from './site.js';

const KEYS = ['ortg', 'drtg', 'net', 'pace'];
const readTable = page => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#st-rt-body tr')].map(tr => [tr.dataset.club,
  {rank: tr.children[0].textContent.trim(), ...Object.fromEntries([...tr.querySelectorAll('td[data-k]')].map(td => [td.dataset.k, td.textContent.trim()]))}])));

test.describe('desktop', () => {
  test.use(DESKTOP);
  test('ratings table agrees with every club page', async ({page}) => {
    test.setTimeout(180000);
    const problems = await prepare(page);
    await page.goto('./#standings');
    await settled(page);
    await page.click('#st-view button[data-v="ratings"]');
    await expect(page).toHaveURL(/#standings\/ratings\/net$/);
    const n = await page.evaluate(() => Object.values(META.ratings).filter(r => r.g).length);
    await expect(page.locator('#st-rt-body tr')).toHaveCount(n);
    const vals = {}, ranks = {};
    for (const k of KEYS) {
      await page.click(`#st-rt th[data-k="${k}"] button`);
      await expect(page).toHaveURL(new RegExp(`#standings/ratings/${k}$`));
      const tab = await readTable(page);
      const order = Object.keys(tab).map(c => parseFloat(tab[c][k]));
      for (let i = 1; i < order.length; i++) expect(k === 'drtg' ? order[i] >= order[i - 1] : order[i] <= order[i - 1], `${k} sorted best first`).toBe(true);
      for (const [c, r] of Object.entries(tab)) { (vals[c] ||= {})[k] = r[k]; (ranks[c] ||= {})[k] = r.rank; }
    }
    const mismatches = [];
    for (const club of Object.keys(vals)) {
      await go(page, `#${club}`, () => document.querySelectorAll('#club .cb-tiles .st-tile').length === 4);
      const tiles = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#club .cb-tiles .st-tile')].map(el => [el.dataset.k, {val: el.querySelector('.val').textContent.trim(), rank: el.querySelector('.note a').textContent.trim(), href: el.querySelector('.note a').getAttribute('href')}])));
      for (const k of KEYS) {
        if (tiles[k].val !== vals[club][k]) mismatches.push(`${club} ${k}: club page ${tiles[k].val} vs table ${vals[club][k]}`);
        if (parseInt(tiles[k].rank, 10) !== parseInt(ranks[club][k], 10)) mismatches.push(`${club} ${k} rank: club page ${tiles[k].rank} vs table ${ranks[club][k]}`);
        expect(tiles[k].href).toBe(`#standings/ratings/${k}`);
      }
    }
    expect(mismatches).toEqual([]);
    // a tile's rank opens the table on that rating, the club marked
    const club = Object.keys(vals)[0];
    await go(page, `#${club}`, () => document.querySelectorAll('#club .cb-tiles .st-tile').length === 4);
    await page.click('#club .cb-tiles .st-tile[data-k="drtg"] .note a');
    await settled(page);
    await expect(page.locator('#st-rt')).toBeVisible();
    await expect(page.locator('#st-rt th.on')).toHaveAttribute('data-k', 'drtg');
    await expect(page.locator(`#st-rt-body tr.me[data-club="${club}"]`)).toHaveCount(1);
    await page.click('#st-view button[data-v="table"]');
    await expect(page.locator('#st-table')).toBeVisible();
    await expect(page.locator('#st-rt')).toBeHidden();
    expect(problems, 'the page reported errors').toEqual([]);
  });
});

for (const lang of ['en', 'tr']) test.describe(`phone ${lang}`, () => {
  test.use(PHONE);
  test('ratings table fits a phone with every rating in view', async ({page}) => {
    const problems = await prepare(page, {lang});
    await page.goto('./#standings/ratings/pace');
    await settled(page);
    await expect(page.locator('#st-rt-body tr').first()).toBeVisible();
    await noSidewaysScroll(page, 'standings ratings');
    const box = await page.locator('#st-rt .scroll').boundingBox();
    for (const k of KEYS) {
      const th = await page.locator(`#st-rt th[data-k="${k}"]`).boundingBox();
      expect(th && th.x + th.width <= box.x + box.width + 1, `${k} column in view without scrolling`).toBe(true);
    }
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
