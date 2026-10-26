// The cover's standings tile: every row opens its club, wherever on the row the reader taps, on a laptop and a phone.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled} from './site.js';

for (const [name, view] of [['desktop', DESKTOP], ['phone', PHONE]]) test.describe(name, () => {
  test.use(view);
  test('a tap anywhere on a standings row opens that club', async ({page}) => {
    const problems = await prepare(page);
    await page.goto('./');
    await settled(page);
    const rows = page.locator('.cv-stand tbody tr');
    const n = await rows.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) expect(await rows.nth(i).locator('a.cv-tl').getAttribute('href')).toMatch(/^#[A-Z]{3}$/);
    const row = rows.nth(1), href = await row.locator('a.cv-tl').getAttribute('href');
    await row.evaluate(r => r.scrollIntoView({block: 'center'}));
    const box = await row.locator('td').nth(2).boundingBox();   // the W–L cell, away from the club name; the stretched link covers it
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await expect(page).toHaveURL(new RegExp(href + '$'));
    await expect(page.locator('body')).toHaveClass(/cb-on/);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
