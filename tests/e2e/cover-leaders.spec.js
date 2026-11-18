// The cover's scoring leaders tile names every player, whichever page the reader opened first: the roster lands after the first
// paint, and a reader who came in on another page and then went to the cover once saw "…" in place of all five names.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled} from './site.js';

const names = page => page.locator('.cv-lead .cv-list a').evaluateAll(as => as.map(a => ({
  name: (a.querySelector('.who b') || {}).textContent || '', club: (a.querySelector('.who small') || {}).textContent || '', href: a.getAttribute('href')})));

for (const [name, view] of [['desktop', DESKTOP], ['phone', PHONE]]) test.describe(name, () => {
  test.use(view);
  for (const start of ['', 'standings', 'leaders', 'game']) test(`leaders named on the cover, first page ${start || 'the cover'}`, async ({page}) => {
    const problems = await prepare(page);
    await page.goto('./');
    await settled(page);
    if (start) {
      const to = start === 'game' ? await page.locator('.cv-game').first().getAttribute('href') : '#' + start;
      await page.goto('./' + to);
      await page.reload();   // a fresh tab that opens on this page
      await settled(page);
      await expect(page.locator('body')).not.toHaveClass(/cv-on/);
      await page.evaluate(() => { location.hash = ''; });
    }
    await expect(page.locator('body')).toHaveClass(/cv-on/);
    await expect.poll(async () => (await names(page)).filter(r => r.name && r.name !== '…' && r.club && /^#[A-Z]{3}\/P\d+$/.test(r.href)).length, {timeout: 8000}).toBe(5);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
