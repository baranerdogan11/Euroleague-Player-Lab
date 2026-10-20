// Player search folds Turkish letters: the feed spells names in plain ASCII (SANLI, SERTAC), and a Turkish keyboard types
// the dotless ı, which has no accent for NFD to strip. Typing the name the Turkish way must still find the player.
import {test, expect} from '@playwright/test';
import {DESKTOP, prepare, settled} from './site.js';

test.use(DESKTOP);
for (const lang of ['en', 'tr']) {
  test(`search finds Turkish spellings · ${lang}`, async ({page}) => {
    const problems = await prepare(page, {lang});
    await page.goto('./');
    await settled(page);
    await page.waitForFunction(() => ROSTER.loaded);
    const pid = await page.evaluate(() => ROSTER.list.find(r => r.name === 'SANLI, SERTAC')?.pid);
    expect(pid, 'Sertac Sanli is on a roster').toBeTruthy();
    for (const typed of ['Şanlı', 'SERTAÇ ŞANLI', 'sertac sanli']) {
      expect(await page.evaluate(q => findPlayers(q).map(x => x.r.pid), typed), `searching "${typed}"`).toContain(pid);
    }
    await page.fill('#cq', 'Şanlı');   // the cover's own search box
    await expect(page.locator('#cq-list li').first()).toContainText(/sanli/i);
    expect(problems, 'the page reported errors').toEqual([]);
  });
}
