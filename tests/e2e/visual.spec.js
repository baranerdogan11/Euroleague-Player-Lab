// Screenshot tests: the cover and the phone bar are compared picture by picture with baselines, so a layout break
// (a collapsed tile, overlapping text, a label cut off) fails CI even when the page throws no error.
// - Data is frozen (tests/e2e/visual/data, made by freeze.py): the HTML's META line and the files these pages fetch are
//   served from there, and the clock is fixed, so nightly data commits do not change the pictures. Photos are masked.
// - Pictures depend on the browser and the machine's fonts, so the baselines are made in CI, on Playwright's own
//   Chromium: these tests run only where PL_VISUAL=1 (the CI browser job). To refresh the baselines after an intended
//   design change, push a commit whose message contains [update visuals]; visual.yml redraws them and commits them back.
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {PHONE, DESKTOP, prepare, settled, go} from './site.js';

const DATA = path.join(path.dirname(fileURLToPath(import.meta.url)), 'visual', 'data');
const META = fs.readFileSync(path.join(DATA, 'meta.json'), 'utf8');
const SEASON = JSON.parse(META).season;
const CLUB = 'ULK', PLAYER = 'P007200';

test.skip(process.env.PL_VISUAL !== '1', 'screenshot baselines are made and checked in CI only (PL_VISUAL=1)');
test.use({launchOptions: {}});   // Playwright's own Chromium, pinned by its version, not the runner's Chrome

async function frozen(page, lang) {
  const problems = await prepare(page, {lang});
  await page.clock.setFixedTime(new Date('2026-10-21T12:00:00Z'));
  await page.route(/\/(index\.html)?(\?.*)?$/, async route => {
    const res = await route.fetch();
    const html = (await res.text()).replace(/^const META = .*;$/m, () => `const META = ${META};`);
    await route.fulfill({response: res, body: html});
  });
  await page.route(new RegExp(`/teams/${SEASON}/(.+\\.json)`), route => {
    const f = path.join(DATA, new URL(route.request().url()).pathname.split(`/teams/${SEASON}/`)[1]);
    return fs.existsSync(f) ? route.fulfill({path: f, contentType: 'application/json'}) : route.continue();
  });
  return problems;
}
// lazy images below the fold would load in one run and not the next: load them all before the picture
const images = page => page.evaluate(() => Promise.all([...document.images].map(i => { i.loading = 'eager'; return i.complete ? null : new Promise(r => { i.onload = i.onerror = r; }); })));
const shot = async (page, name, fullPage = true) => { await images(page); await page.evaluate(() => document.fonts.ready); return expect(page).toHaveScreenshot(name, {fullPage, animations: 'disabled', mask: [page.locator('img[src*="photos/"]')], maxDiffPixelRatio: 0.002}); };

for (const [size, use] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  test.describe(size, () => {
    test.use(use);
    test(`cover · ${size}`, async ({page}) => {
      const problems = await frozen(page, 'en');
      await page.goto('./');
      await settled(page);
      await shot(page, `cover-${size}.png`);
      expect(problems).toEqual([]);
    });
  });
}

// the phone bar on the pages it sits under, in both languages (Turkish labels are the longest)
test.describe('phone bar', () => {
  test.use(PHONE);
  for (const lang of ['en', 'tr']) {
    test(`club and player pages · ${lang}`, async ({page}) => {
      const problems = await frozen(page, lang);
      await page.goto('./');
      await settled(page);
      await go(page, `#${CLUB}`, () => !document.querySelector('#club').textContent.includes('…'));
      await expect(page.locator('.tabbar')).toBeVisible();
      await shot(page, `club-${lang}.png`, false);   // the screen as a phone shows it, bar fixed at the bottom
      await go(page, `#${CLUB}/${PLAYER}`);
      await shot(page, `player-${lang}.png`, false);
      expect(problems).toEqual([]);
    });
  }
});
