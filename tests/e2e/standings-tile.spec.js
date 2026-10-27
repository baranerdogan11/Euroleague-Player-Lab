// The cover's standings tile: every row opens its own club, wherever on the row the reader taps, on a laptop and a phone.
// Nothing laid over the tile may catch a row's tap: Safari once let the last row's link cover every row (all went to #VIR).
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled} from './site.js';

for (const [name, view] of [['desktop', DESKTOP], ['phone', PHONE]]) test.describe(name, () => {
  test.use(view);
  test('a tap anywhere on a standings row opens that club', async ({page}) => {
    const problems = await prepare(page);
    await page.goto('./');
    await settled(page);
    const codes = await page.locator('.cv-stand tbody tr a.cv-tl').evaluateAll(as => as.map(a => a.getAttribute('href')));
    expect(codes.length).toBeGreaterThan(1);
    expect(new Set(codes).size, 'every row links its own club').toBe(codes.length);
    for (let i = 0; i < codes.length; i++) {
      expect(codes[i]).toMatch(/^#[A-Z]{3}$/);
      const row = page.locator('.cv-stand tbody tr').nth(i);
      await row.evaluate(r => r.scrollIntoView({block: 'center'}));
      for (const cell of [1, 2]) {   // the club name, then the W–L cell away from it
        const box = await row.locator('td').nth(cell).boundingBox();
        const x = box.x + (cell === 1 ? 12 : box.width / 2), y = box.y + box.height / 2;
        const hit = await page.evaluate(([x, y, i]) => { const e = document.elementFromPoint(x, y); return !!e && e.closest('.cv-stand tbody tr') === document.querySelectorAll('.cv-stand tbody tr')[i]; }, [x, y, i]);
        expect(hit, `row ${i + 1} catches its own tap`).toBe(true);
      }
      const box = await row.locator('td').nth(2).boundingBox();
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await expect(page).toHaveURL(new RegExp(codes[i] + '$'));
      await expect(page.locator('body')).toHaveClass(/cb-on/);
      await page.goto('./');
      await settled(page);
    }
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
