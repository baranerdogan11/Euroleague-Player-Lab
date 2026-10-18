// Zones above and below the league are drawn in one orange and one blue for every club, a pair colour-blind readers
// can tell apart, and never in the club's own accent: Anadolu Efes' accent is a light blue that would read as "cold".
import {test, expect} from '@playwright/test';
import {DESKTOP, prepare, settled, go} from './site.js';

const ALLOWED = ['242,111,33', '79,142,247', '120,128,144'];   // hot, cold, too few attempts

test.use(DESKTOP);
test('zone colours do not follow the club accent', async ({page}) => {
  const problems = await prepare(page);
  await page.goto('./');
  await settled(page);
  const club = 'IST';
  await go(page, `#${club}`, () => document.body.classList.contains('cb-on'));
  // Efes players by shot count, until one has a zone above the league (a hot fill) to check
  const pids = await page.evaluate(async c => {
    const d = await (await fetch(`teams/E2026/${c}.json`)).json();
    return d.players.map(p => [p.pid, (p.cur?.shots || []).length]).filter(x => x[1] >= 20).sort((a, b) => b[1] - a[1]).map(x => x[0]);
  }, club);
  let hot = 0;
  for (const pid of pids) {
    await go(page, `#${club}/${pid}/zones`, () => document.querySelectorAll('#zones-layer .zone').length > 0);
    const fills = await page.evaluate(() => [...document.querySelectorAll('#zones-layer .zone'), ...document.querySelectorAll('#zones .cell')]
      .map(el => el.getAttribute('fill') || el.style.background).filter(f => f && f !== 'transparent'));
    for (const f of fills) {
      const rgb = (f.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/) || []).slice(1, 4).join(',');
      expect(ALLOWED, `${pid}: zone fill ${f} is not the fixed orange, blue or grey`).toContain(rgb);
      if (rgb === ALLOWED[0]) hot++;
    }
    if (hot) break;
  }
  expect(hot, 'no Efes player has a zone above the league to check').toBeGreaterThan(0);
  expect(problems, 'the page reported errors').toEqual([]);
});
