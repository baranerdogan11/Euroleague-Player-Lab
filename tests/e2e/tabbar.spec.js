// The phone tab bar at 390px: five tabs, Lineups no longer among them, and every label in English and Turkish fits its tab
// without being cut off. The #lineups page stays reachable from the See all fives control on a club page.
import {test, expect} from '@playwright/test';
import {PHONE, prepare, settled, go} from './site.js';

for (const lang of ['en', 'tr']) {
  test.describe(`phone · ${lang}`, () => {
    test.use(PHONE);
    test('the bar sits on the opening page too, with no tab lit and nothing hidden under it', async ({page}) => {
      const problems = await prepare(page, {lang});
      await page.goto('./');
      await settled(page);
      await page.waitForFunction(() => document.body.classList.contains('cv-on'));
      await expect(page.locator('#tabbar')).toBeVisible();
      const lit = await page.evaluate(() => [...document.querySelectorAll('#tabbar > *')].filter(el => !['none', 'normal'].includes(getComputedStyle(el, '::before').content)).map(el => el.id));
      expect(lit, 'no tab is lit on the cover').toEqual([]);
      await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
      const gap = await page.evaluate(() => document.querySelector('#tabbar').getBoundingClientRect().top - document.querySelector('.cv-foot').getBoundingClientRect().bottom);
      expect(gap, 'the cover footer clears the bar').toBeGreaterThanOrEqual(0);
      await page.click('#tb-standings');
      await page.waitForFunction(() => document.body.classList.contains('st-on'));
      expect(problems, 'the page reported errors').toEqual([]);
    });
    test('five tabs whose labels fit', async ({page}) => {
      const problems = await prepare(page, {lang});
      await page.goto('./');
      await settled(page);
      const code = await page.evaluate(() => META.clubs[0].code);
      await go(page, `#${code}`, () => document.body.classList.contains('cb-on') && !!document.querySelector('#club .see-all'));
      const tabs = await page.evaluate(() => [...document.querySelectorAll('#tabbar > *')].map(el => {
        const s = el.querySelector('span'), r = el.getBoundingClientRect(), sr = s.getBoundingClientRect();
        return {id: el.id, text: s.textContent.trim(), cut: s.scrollWidth > s.clientWidth + 1 || sr.left < r.left - 1 || sr.right > r.right + 1, w: r.width};
      }));
      expect(tabs.map(x => x.id)).toEqual(['tb-player', 'tb-compare', 'tb-standings', 'tb-games', 'tb-leaders']);
      for (const x of tabs) {
        expect(x.text.length, `${x.id} has a label`).toBeGreaterThan(0);
        expect(x.cut, `${x.id} label "${x.text}" is cut off at 390px`).toBe(false);
      }
      await page.click('#club .see-all');
      await page.waitForFunction(c => document.body.classList.contains('ln-on') && document.querySelector('#ln-club')?.value === c, code);
      expect(problems, 'the page reported errors').toEqual([]);
    });
  });
}
