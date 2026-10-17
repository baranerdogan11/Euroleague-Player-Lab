// A reader who keeps the page open while a new build lands is told so: the page polls status.json and, when the data is
// newer than the page, shows a notice with a Refresh button.
import {test, expect} from '@playwright/test';
import {DESKTOP, prepare, settled} from './site.js';

test.use(DESKTOP);

test('the New data notice shows when a newer build lands', async ({page}) => {
  const problems = await prepare(page);
  await page.goto('./');
  await settled(page);
  await page.route('**/status.json', async route => {
    const r = await route.fetch(), st = await r.json();
    await route.fulfill({response: r, json: {...st, checked_at: '9999-12-31 23:59 UTC'}});
  });
  await page.evaluate(() => checkFresh());
  await expect(page.locator('#toast')).toContainText('New data since you opened this page');
  await expect(page.locator('#toast #refresh')).toBeVisible();
  expect(problems, 'the page reported errors').toEqual([]);
});
