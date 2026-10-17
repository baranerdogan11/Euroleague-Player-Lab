// Every page type, at phone and desktop width, in English and Turkish, light and dark: each must draw without an error
// and without scrolling sideways. A screenshot of each is attached to the test, so a PR's look can be reviewed from the
// CI run without building the site.
import {test, expect} from '@playwright/test';
import {PHONE, DESKTOP, prepare, settled, go, noSidewaysScroll} from './site.js';

// [name, hash or a function of the loaded META that returns one, the condition that says the page is drawn]
const PAGES = [
  ['cover', '', () => document.body.classList.contains('cv-on') && document.querySelectorAll('#cv-clubs a').length === META.clubs.length],
  ['club', m => `#${m.clubs[0].code}`, () => document.body.classList.contains('cb-on') && document.querySelectorAll('#club .cb-tab tbody tr').length >= 8],
  ['player', m => `#${m.clubs[0].code}/`, () => document.querySelector('#nm')?.textContent.trim().length > 1 && document.querySelector('#court')?.childElementCount > 3 && document.querySelectorAll('#log tbody tr').length >= 1],
  // META.games rows are compact: [code, round, date, home, away, ...], newest first
  ['game', m => `#game/${m.games[0][0]}`, () => document.body.classList.contains('gm-on') && document.querySelectorAll('#game .gm-ldr-c').length === 4 && !!document.querySelector('#gm-wp svg path.ln')],
  ['game-box', m => `#game/${m.games[0][0]}/box`, () => document.querySelectorAll('#game .gm-box tbody tr').length >= 16],
  ['games', '#games', () => document.querySelectorAll('#gs-list a.cv-game').length === META.games.length],
  ['standings', '#standings', () => document.querySelectorAll('#standings .st-tab tbody tr').length >= META.clubs.length],
  ['leaders', '#leaders', () => document.querySelectorAll('#ld-wrap tbody tr').length >= 10],
  ['compare', '#compare', () => document.querySelector('#cmp-panel')?.getBoundingClientRect().height > 200],
  ['lineups', '#lineups', () => document.querySelector('#lineups')?.getBoundingClientRect().height > 300],
];

for (const [device, opts] of [['phone', PHONE], ['desktop', DESKTOP]]) {
  for (const lang of ['en', 'tr']) {
    for (const theme of ['light', 'dark']) {
      test.describe(`${device} · ${lang} · ${theme}`, () => {
        test.use(opts);
        test('every page draws cleanly', async ({page}, info) => {
          const problems = await prepare(page, {lang, theme});
          await page.goto('./');
          await settled(page);
          const meta = await page.evaluate(() => ({clubs: META.clubs, games: META.games}));
          for (const [name, where, probe] of PAGES) {
            await test.step(name, async () => {
              let hash = typeof where === 'function' ? where(meta) : where;
              // a player page needs a real player: the club's first, read from the club once it has loaded
              if (name === 'player') hash += await page.evaluate(() => team().players[0].pid);
              await go(page, hash || '#', probe);
              await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
              expect(await page.evaluate(() => LANG)).toBe(lang);
              await noSidewaysScroll(page, `${name} (${device}, ${lang}, ${theme})`);
              await info.attach(`${name}-${device}-${lang}-${theme}`, {body: await page.screenshot(), contentType: 'image/png'});
            });
          }
          expect(problems, 'the page reported errors').toEqual([]);
        });
      });
    }
  }
}
